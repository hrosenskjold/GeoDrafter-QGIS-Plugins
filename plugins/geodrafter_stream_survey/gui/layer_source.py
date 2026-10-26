# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Step 1 from the map: a point layer in the project, or a file/layer dropped on the field.

A layer is read like an Emlid export: its fields are matched by name (Name,
Code, Elevation, Solution status …) and its geometry gives the position, in
ETRS89 / UTM 32N (transformed when the layer has another CRS). The order of the
features is the survey order.
"""

import os

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QLineEdit
from qgis.core import (
    NULL, Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsMimeDataUtils, QgsProject,
    QgsVectorLayer)

from ..core.readers.common import check_crs
from ..core.readers.shapefile import survey_from_rows

CRS = "EPSG:25832"


def is_point_layer(layer):
    return isinstance(layer, QgsVectorLayer) and layer.isValid() and \
        layer.geometryType() == Qgis.GeometryType.Point


def _text(v):
    if v is None or v == NULL:
        return ""
    if isinstance(v, float):
        return repr(v)
    return str(v)


def layer_file(layer):
    """The file behind a layer (CSV, shapefile …), or "" for memory/database layers."""
    try:
        from qgis.core import QgsProviderRegistry
        parts = QgsProviderRegistry.instance().decodeUri(layer.providerType(), layer.source())
        path = parts.get("path") or ""
    except Exception:   # noqa: BLE001 – providers without decodeUri
        path = ""
    return path if path and os.path.exists(path) else ""


def survey_from_layer(layer, code_table=None, project=None):
    """A Survey from a point layer of the project (any CRS, file-backed or not)."""
    project = project or QgsProject.instance()
    target = QgsCoordinateReferenceSystem(CRS)
    transform = None
    cs = ""
    if layer.crs().isValid() and layer.crs() != target and layer.crs().authid() != CRS:
        transform = QgsCoordinateTransform(layer.crs(), target, project)
        cs = "ETRS89 / UTM zone 32N (transformed from %s; heights as in the layer)" % layer.crs().authid()
    headers = [f.name() for f in layer.fields()]
    records, pts = [], []
    for f in layer.getFeatures():
        g = f.geometry()
        if g is None or g.isEmpty():
            continue
        geom = g.constGet()
        p = geom if not g.isMultipart() else geom.geometryN(0)
        x, y = p.x(), p.y()
        if transform is not None:
            q = transform.transform(x, y)
            x, y = q.x(), q.y()
        z = p.z() if p.is3D() else None
        if z is not None and z != z:   # NaN
            z = None
        pts.append((x, y, z))
        records.append([_text(v) for v in f.attributes()])
    survey = survey_from_rows(headers, records, pts, layer.name(), "layer", cs)
    if survey.points and all(pt.z is None for pt in survey.points):
        survey.warnings.append("The layer has no elevations (no Z and no Elevation field).")
    if code_table is not None:
        survey.apply_code_table(code_table)
    check_crs(survey)
    return survey


class DropLineEdit(QLineEdit):
    """A line edit that takes a dropped file (Explorer/Finder) or a layer from the Layers panel."""

    layerDropped = pyqtSignal(str)   # layer id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def _decode(self, mime):
        """("layer", id) or ("file", path) or None."""
        if QgsMimeDataUtils.isUriList(mime):
            for uri in QgsMimeDataUtils.decodeUriList(mime):
                lid = getattr(uri, "layerId", "")
                if lid and QgsProject.instance().mapLayer(lid) is not None:
                    return "layer", lid
                if uri.uri:
                    path = uri.uri.split("|", 1)[0]
                    if path.startswith("file://"):
                        path = path[7:].split("?", 1)[0]
                    if os.path.exists(path):
                        return "file", path
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile() and os.path.isfile(url.toLocalFile()):
                    return "file", url.toLocalFile()
        return None

    def dragEnterEvent(self, e):  # noqa: N802
        if self._decode(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):  # noqa: N802
        if self._decode(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):  # noqa: N802
        hit = self._decode(e.mimeData())
        if hit is None:
            super().dropEvent(e)
            return
        kind, value = hit
        if kind == "layer":
            self.layerDropped.emit(value)
        else:
            self.setText(value)
        e.acceptProposedAction()
