# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""What the panel shows for one map position, and how typed text becomes a position.

``Readout`` turns a point in the map CRS into an ordered list of rows
``(key, label, text)``: the map CRS, a CRS the user chooses, and the WGS84-based
formats from ``coordfmt``. ``locate`` does the opposite for the Go to field.
Both are free of widgets so they can be tested on their own.
"""

import math

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCsException,
    QgsPointXY, QgsProject,
)

from . import coordfmt, coordparse

WGS84 = "EPSG:4326"


def _crs(text):
    return QgsCoordinateReferenceSystem(text)


def format_xy(point, crs):
    """'x, y' in a projected CRS (3 decimals) or 'lat, lon' in a geographic one (6)."""
    if crs.isGeographic():
        return "{:.6f}, {:.6f}".format(point.y(), point.x())
    return "{:.3f}, {:.3f}".format(point.x(), point.y())


class Readout:
    """Rows of text for a map position. Set ``map_crs`` and ``chosen_crs`` as they change."""

    def __init__(self, map_crs=None, chosen_crs=None):
        self.map_crs = map_crs or _crs(WGS84)
        self.chosen_crs = chosen_crs or _crs(WGS84)

    def keys_and_labels(self):
        """[(key, label)] in display order, independent of any point."""
        rows = [("map", "Map CRS"), ("chosen", "Chosen CRS")]
        rows += [(key, label) for key, label, _text in coordfmt.format_all(0.0, 0.0)]
        return rows

    def _to(self, point, crs):
        try:
            out = QgsCoordinateTransform(self.map_crs, crs, QgsProject.instance()).transform(point)
        except QgsCsException:
            return None
        if not (math.isfinite(out.x()) and math.isfinite(out.y())):
            return None
        return out

    def rows(self, point):
        """[(key, label, text)] for ``point`` (map CRS); text is '' where undefined."""
        texts = {"map": "%s  (%s)" % (format_xy(point, self.map_crs), self.map_crs.authid())}
        chosen = self._to(point, self.chosen_crs)
        texts["chosen"] = "" if chosen is None else "%s  (%s)" % (
            format_xy(chosen, self.chosen_crs), self.chosen_crs.authid())
        ll = self._to(point, _crs(WGS84))
        if ll is not None:
            for key, _label, text in coordfmt.format_all(ll.y(), ll.x()):
                texts[key] = text or ""
        return [(key, label, texts.get(key, "")) for key, label in self.keys_and_labels()]


def locate(text, chosen_crs, map_crs):
    """Typed coordinate -> (point in map CRS, how it was read). Raises ValueError."""
    parsed = coordparse.parse(text)
    kind = parsed["kind"]
    if kind == "wgs84":
        source, x, y, how = _crs(WGS84), parsed["lon"], parsed["lat"], "WGS84"
    elif kind == "utm":
        epsg = (32600 if parsed["north"] else 32700) + parsed["zone"]
        source, x, y = _crs("EPSG:%d" % epsg), parsed["easting"], parsed["northing"]
        how = "UTM zone %d%s (EPSG:%d)" % (parsed["zone"], "N" if parsed["north"] else "S", epsg)
    else:
        a, b = parsed["a"], parsed["b"]
        if chosen_crs.isGeographic():
            source, x, y, how = chosen_crs, b, a, chosen_crs.authid()
        elif coordparse.looks_like_lat_lon(a, b):
            # Two small numbers are hardly metres in a projected CRS: read them as lat, lon
            source, x, y, how = _crs(WGS84), b, a, "WGS84 (lat, lon)"
        else:
            source, x, y, how = chosen_crs, a, b, chosen_crs.authid()
        if source.isGeographic() and not (-90 <= y <= 90 and -180 <= x <= 180):
            raise ValueError("Latitude must be between -90 and 90 (order: lat, lon)")
    if not source.isValid():
        raise ValueError("Unknown CRS")
    try:
        point = QgsCoordinateTransform(source, map_crs, QgsProject.instance()).transform(QgsPointXY(x, y))
    except QgsCsException:
        raise ValueError("This position cannot be shown in the map CRS")
    if not (math.isfinite(point.x()) and math.isfinite(point.y())):
        raise ValueError("This position cannot be shown in the map CRS")
    return point, how
