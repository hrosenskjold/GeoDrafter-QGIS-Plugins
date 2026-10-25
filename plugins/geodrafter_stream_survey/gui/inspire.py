# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Watercourse centre lines from Dataforsyningen's INSPIRE Hydrography download service (WFS).

Dataforsyningen's INSPIRE OGC services need no token. The service address and
the feature type can be changed in the QGIS settings
(``geodrafter/stream_survey/inspire_url`` and ``inspire_typename``) without a new
version – the defaults below must be confirmed against the live
GetCapabilities (Henrik's test, TESTING.md), as they could not be checked from
the build environment. Anything that fails here is reported and the centre
line is built from the bed points instead.

Attribution as Dataforsyningen asks: "Indeholder data fra Klimadatastyrelsen, INSPIRE Hydrografi".
"""

import datetime

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDataSourceUri, QgsFeatureRequest, QgsProject,
    QgsRectangle, QgsVectorLayer)

from ..core.centerline_source import WatercourseFeature, watercourse_key
from .terrain_source import setting

DEFAULT_URL = "https://api.dataforsyningen.dk/hydrografi_inspire"
DEFAULT_TYPENAME = "hy-p:Watercourse"
SOURCE_NAME = "INSPIRE Hydrografi (Dataforsyningen)"
ATTRIBUTION = "Indeholder data fra Klimadatastyrelsen, INSPIRE Hydrografi"
CRS = "EPSG:25832"


def wfs_layer(url=None, typename=None):
    uri = QgsDataSourceUri()
    uri.setParam("url", url or setting("inspire_url", DEFAULT_URL))
    uri.setParam("typename", typename or setting("inspire_typename", DEFAULT_TYPENAME))
    uri.setParam("srsname", CRS)
    uri.setParam("version", "auto")
    uri.setParam("restrictToRequestBBOX", "1")
    return QgsVectorLayer(uri.uri(False), SOURCE_NAME, "WFS")


def features_in(layer, xmin, ymin, xmax, ymax, margin=200.0):
    """WatercourseFeatures of a line layer inside the rectangle (EPSG:25832) plus ``margin``."""
    target = QgsCoordinateReferenceSystem(CRS)
    rect = QgsRectangle(xmin - margin, ymin - margin, xmax + margin, ymax + margin)
    to_layer = QgsCoordinateTransform(target, layer.crs(), QgsProject.instance().transformContext())
    to_target = QgsCoordinateTransform(layer.crs(), target, QgsProject.instance().transformContext())
    req = QgsFeatureRequest().setFilterRect(to_layer.transformBoundingBox(rect))
    names = layer.fields().names()
    out = []
    for f in layer.getFeatures(req):
        g = f.geometry()
        if g is None or g.isEmpty():
            continue
        g.transform(to_target)
        attrs = {n: f[n] for n in names}
        attrs.setdefault("fid", f.id())
        key = watercourse_key(attrs) or "feature:%d" % f.id()
        parts = g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()]
        for part in parts:
            coords = [(p.x(), p.y()) for p in part]
            if len(coords) >= 2:
                out.append(WatercourseFeature(coords, key, {k: str(v) for k, v in attrs.items()}))
    return out


def fetch(points, margin=200.0):
    """(features, source text, fetched date) for the survey's extent; raises RuntimeError when it fails."""
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    layer = wfs_layer()
    if not layer.isValid():
        why = layer.dataProvider().error().summary() if layer.dataProvider() else ""
        raise RuntimeError("The INSPIRE hydrography service could not be opened. %s" % why)
    feats = features_in(layer, min(xs), min(ys), max(xs), max(ys), margin)
    if not feats:
        raise RuntimeError("The INSPIRE hydrography service returned no watercourse near the survey.")
    today = datetime.date.today().isoformat()
    return feats, "%s, fetched %s" % (SOURCE_NAME, today), today
