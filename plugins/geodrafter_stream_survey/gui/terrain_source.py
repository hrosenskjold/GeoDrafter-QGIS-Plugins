# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Terrain model for the extension: a raster layer (local GeoTIFF/VRT or WCS).

Danmarks Højdemodel – Terræn is read from Dataforsyningen's WCS with the user's
own token. The token is stored in the QGIS password manager (QgsAuthManager)
as an "API Header" configuration, so QGIS sends it as an HTTP header; only the
configuration id is kept in the settings – the token is never written to the
project, the layer source, the code or a URL.
"""

import math

from qgis.core import (
    QgsApplication, QgsAuthMethodConfig, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsRasterLayer, QgsRectangle, QgsSettings)

from ..core.terrain import GridTerrain

SETTINGS_PREFIX = "geodrafter/stream_survey/"
DEFAULT_WCS_URL = "https://api.dataforsyningen.dk/dhm_wcs_DAF"
DEFAULT_COVERAGE = "dhm_terraen"
DEFAULT_HEADER = "token"
AUTH_NAME = "GeoDrafter Stream Survey – Dataforsyningen"


def setting(key, default=""):
    return QgsSettings().value(SETTINGS_PREFIX + key, default)


def set_setting(key, value):
    QgsSettings().setValue(SETTINGS_PREFIX + key, value)


def save_token(token, header=DEFAULT_HEADER, authcfg=None):
    """Store the token in the QGIS password manager; returns the configuration id.

    An existing configuration (``authcfg``) is updated. Raises RuntimeError
    when the password manager is not available (e.g. no master password).
    """
    token = (token or "").strip()
    if not token:
        raise ValueError("Empty token")
    am = QgsApplication.authManager()
    if am.isDisabled():
        raise RuntimeError("The QGIS password manager is disabled.")
    cfg = QgsAuthMethodConfig()
    if authcfg and authcfg in am.configIds():
        am.loadAuthenticationConfig(authcfg, cfg, True)
    cfg.setName(AUTH_NAME)
    cfg.setMethod("APIHeader")
    cfg.setConfigMap({header or DEFAULT_HEADER: token})
    ok = am.updateAuthenticationConfig(cfg) if cfg.id() else am.storeAuthenticationConfig(cfg)
    ok = ok[0] if isinstance(ok, tuple) else ok
    if not ok or not cfg.id():
        raise RuntimeError("The token could not be stored in the QGIS password manager.")
    set_setting("authcfg", cfg.id())
    return cfg.id()


def stored_authcfg():
    cid = setting("authcfg", "")
    if cid and cid in QgsApplication.authManager().configIds():
        return cid
    return ""


def wcs_uri(authcfg, url=DEFAULT_WCS_URL, coverage=DEFAULT_COVERAGE, crs="EPSG:25832"):
    """Data source of the WCS layer; carries only the configuration id, never the token."""
    parts = ["url=%s" % url, "identifier=%s" % coverage, "crs=%s" % crs, "format=GTiff",
             "cache=PreferNetwork"]
    if authcfg:
        parts.append("authcfg=%s" % authcfg)
    return "&".join(parts)


def dhm_layer(authcfg, url=DEFAULT_WCS_URL, coverage=DEFAULT_COVERAGE):
    layer = QgsRasterLayer(wcs_uri(authcfg, url, coverage), "DHM Terræn (Dataforsyningen)", "wcs")
    return layer


def file_layer(path):
    return QgsRasterLayer(path, "Terrain model", "gdal")


class RasterTerrain:
    """Callable terrain(x, y) for points in ``crs`` from a raster layer.

    For each section, ``for_extent`` reads the raster cells around it once (a
    block at the raster's own resolution, aligned to its grid) and samples them
    bilinearly with ``GridTerrain`` – the same bilinear rule the core tests use.
    """

    def __init__(self, layer, crs=None, band=1, margin=2.0):
        if layer is None or not layer.isValid():
            raise ValueError("The terrain model layer is not valid")
        self.layer = layer
        self.band = band
        self.margin = margin
        self.provider = layer.dataProvider()
        self.crs = crs or QgsCoordinateReferenceSystem("EPSG:25832")
        self.same_crs = layer.crs() == self.crs
        self.xform = None if self.same_crs else QgsCoordinateTransform(
            self.crs, layer.crs(), QgsProject.instance().transformContext())
        self.version = layer.name()
        ext = layer.extent()
        px = layer.rasterUnitsPerPixelX() or 0.4
        py = layer.rasterUnitsPerPixelY() or px
        self.px, self.py = abs(px), abs(py)
        self.ox, self.oy = ext.xMinimum(), ext.yMaximum()

    def for_extent(self, xmin, ymin, xmax, ymax):
        """A GridTerrain covering the rectangle (in ``crs``) plus the margin."""
        if not self.same_crs:
            r = self.xform.transformBoundingBox(QgsRectangle(xmin, ymin, xmax, ymax))
            xmin, ymin, xmax, ymax = r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()
        m = self.margin + 2 * max(self.px, self.py)
        c0 = math.floor((xmin - m - self.ox) / self.px)
        c1 = math.ceil((xmax + m - self.ox) / self.px)
        r0 = math.floor((self.oy - (ymax + m)) / self.py)
        r1 = math.ceil((self.oy - (ymin - m)) / self.py)
        cols, rows = max(c1 - c0, 2), max(r1 - r0, 2)
        x0, y0 = self.ox + c0 * self.px, self.oy - r0 * self.py
        rect = QgsRectangle(x0, y0 - rows * self.py, x0 + cols * self.px, y0)
        block = self.provider.block(self.band, rect, cols, rows)
        if block is None or not block.isValid():
            return None
        values = []
        for r in range(rows):
            row = []
            for c in range(cols):
                row.append(None if block.isNoData(r, c) else block.value(r, c))
            values.append(row)
        grid = GridTerrain(x0, y0, self.px, values)
        if self.same_crs:
            return grid
        xf = self.xform

        def sample(x, y):
            p = xf.transform(x, y)
            return grid(p.x(), p.y())
        return sample

    def for_profile(self, profile, length):
        """Terrain function covering a section, its extension and its points."""
        (ax, ay), (bx, by) = profile.line(extra=length + 1.0)
        xs = [ax, bx] + [pp.point.x for pp in profile.points]
        ys = [ay, by] + [pp.point.y for pp in profile.points]
        f = self.for_extent(min(xs), min(ys), max(xs), max(ys))
        return f if f is not None else (lambda x, y: None)
