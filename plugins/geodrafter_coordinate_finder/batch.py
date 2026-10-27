# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Coordinates for many points at once: a point layer's features or every vertex of a layer.

Three outputs:

* ``write_to_layer`` adds coordinate fields to a point layer and fills them
  (one undoable edit command; the layer is left in edit mode for the user to save),
* ``vertices_layer`` makes a new point layer with one point per vertex,
* ``as_table`` returns tab-separated text to paste into a spreadsheet.

Formats are keys of ``FORMATS``. "chosen" is the CRS chosen in the panel.
"""

import math
import re

from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCsException,
    QgsFeature, QgsFeatureRequest, QgsField, QgsFields, QgsGeometry, QgsPointXY,
    QgsProject, QgsVectorLayer, QgsWkbTypes,
)

from . import coordfmt

WGS84 = "EPSG:4326"

#: key -> label shown in the dialog, in display order
FORMATS = {
    "chosen": "Chosen CRS (x, y)",
    "dd": "Decimal degrees (lat, lon)",
    "dms": "Degrees minutes seconds",
    "ddm": "Degrees decimal minutes",
    "utm": "UTM (WGS84)",
    "mgrs": "MGRS",
}
DEFAULT_FORMATS = ("chosen", "dd")


def _field(name, kind):
    """QgsField with QMetaType (QGIS >= 3.38, required on QGIS 4) or QVariant (older)."""
    try:
        from qgis.PyQt.QtCore import QMetaType
        types = {"double": QMetaType.Type.Double, "int": QMetaType.Type.Int, "string": QMetaType.Type.QString}
        return QgsField(name, types[kind])
    except (TypeError, AttributeError):
        from qgis.PyQt.QtCore import QVariant
        types = {"double": QVariant.Double, "int": QVariant.Int, "string": QVariant.String}
        return QgsField(name, types[kind])


def crs_suffix(crs):
    """'EPSG:25832' -> '25832'; anything else -> 'crs'. Keeps field names <= 10 characters."""
    m = re.fullmatch(r"EPSG:(\d{1,8})", crs.authid() or "")
    return m.group(1) if m else "crs"


def field_specs(formats, chosen_crs):
    """[(name, kind)] for the selected formats, in a fixed order."""
    specs = []
    for key in FORMATS:
        if key not in formats:
            continue
        if key == "chosen":
            s = crs_suffix(chosen_crs)
            specs += [("x_" + s, "double"), ("y_" + s, "double")]
        elif key == "dd":
            specs += [("lat", "double"), ("lon", "double")]
        elif key in ("dms", "ddm"):
            specs += [("lat_" + key, "string"), ("lon_" + key, "string")]
        else:
            specs.append((key, "string"))
    return specs


class Converter:
    """Turns points in a source CRS into field values for the selected formats."""

    def __init__(self, source_crs, chosen_crs, formats):
        project = QgsProject.instance()
        self.formats = [k for k in FORMATS if k in formats]
        self.chosen_crs = chosen_crs
        self.specs = field_specs(self.formats, chosen_crs)
        self.to_chosen = QgsCoordinateTransform(source_crs, chosen_crs, project)
        self.to_wgs84 = QgsCoordinateTransform(source_crs, QgsCoordinateReferenceSystem(WGS84), project)

    def _transform(self, xform, point):
        try:
            out = xform.transform(point)
        except QgsCsException:
            return None
        return out if math.isfinite(out.x()) and math.isfinite(out.y()) else None

    def values(self, point):
        """{field name: value} for one point (source CRS); None where it cannot be computed."""
        out = {}
        digits = 8 if self.chosen_crs.isGeographic() else 3
        if "chosen" in self.formats:
            p = self._transform(self.to_chosen, point)
            names = [n for n, _k in self.specs[:2]]
            out[names[0]] = round(p.x(), digits) if p else None
            out[names[1]] = round(p.y(), digits) if p else None
        ll = None
        if any(k in self.formats for k in ("dd", "dms", "ddm", "utm", "mgrs")):
            ll = self._transform(self.to_wgs84, point)
        lat, lon = (ll.y(), coordfmt.norm_lon(ll.x())) if ll else (None, None)
        if "dd" in self.formats:
            out["lat"] = round(lat, 8) if ll else None
            out["lon"] = round(lon, 8) if ll else None
        if "dms" in self.formats:
            out["lat_dms"] = coordfmt.to_dms(lat, True) if ll else None
            out["lon_dms"] = coordfmt.to_dms(lon, False) if ll else None
        if "ddm" in self.formats:
            out["lat_ddm"] = coordfmt.to_ddm(lat, True) if ll else None
            out["lon_ddm"] = coordfmt.to_ddm(lon, False) if ll else None
        if "utm" in self.formats:
            out["utm"] = coordfmt.fmt_utm(coordfmt.to_utm(lat, lon)) if ll else None
        if "mgrs" in self.formats:
            out["mgrs"] = coordfmt.to_mgrs(lat, lon) if ll else None
        return out


def is_point_layer(layer):
    return isinstance(layer, QgsVectorLayer) and \
        QgsWkbTypes.geometryType(layer.wkbType()) == Qgis.GeometryType.Point


def _features(layer, selected_only):
    if selected_only:
        return layer.getSelectedFeatures()
    return layer.getFeatures(QgsFeatureRequest())


def feature_point(geometry):
    """The point of a point feature (first part of a multipoint), or None."""
    if geometry is None or geometry.isNull() or geometry.isEmpty():
        return None
    if geometry.isMultipart():
        parts = geometry.asMultiPoint()
        return QgsPointXY(parts[0]) if parts else None
    return QgsPointXY(geometry.asPoint())


def vertices(geometry):
    """[(part, ring, vertex, QgsPointXY)] – every vertex, without the repeated closing vertex of rings."""
    out = []
    if geometry is None or geometry.isNull() or geometry.isEmpty():
        return out
    previous_ring = None
    ring_start = None
    for nr, v in enumerate(geometry.vertices()):
        ok, vid = geometry.vertexIdFromVertexNr(nr)
        if not ok:
            continue
        key = (vid.part, vid.ring)
        point = QgsPointXY(v.x(), v.y())
        if key != previous_ring:
            previous_ring, ring_start = key, point
        elif QgsWkbTypes.geometryType(geometry.wkbType()) == Qgis.GeometryType.Polygon and \
                point == ring_start and _is_last_of_ring(geometry, nr):
            continue
        out.append((vid.part, vid.ring, vid.vertex, point))
    return out


def _is_last_of_ring(geometry, nr):
    ok, nxt = geometry.vertexIdFromVertexNr(nr + 1)
    if not ok:
        return True
    _ok, cur = geometry.vertexIdFromVertexNr(nr)
    return (nxt.part, nxt.ring) != (cur.part, cur.ring)


# -------------------------------------------------------------------- outputs

def write_to_layer(layer, formats, chosen_crs, selected_only=False):
    """Add/fill coordinate fields on a point layer. Returns the number of features written.

    The layer is put in edit mode and left there (the user saves or rolls back);
    everything is one edit command, so Ctrl+Z undoes it.
    """
    if not is_point_layer(layer):
        raise ValueError("Writing to the attribute table needs a point layer")
    if not formats:
        raise ValueError("Choose at least one format")
    if not layer.isEditable() and not layer.startEditing():
        raise ValueError('Layer "%s" cannot be edited' % layer.name())
    conv = Converter(layer.crs(), chosen_crs, formats)
    layer.beginEditCommand("Add coordinates")
    try:
        existing = {f.name().lower() for f in layer.fields()}
        for name, kind in conv.specs:
            if name.lower() not in existing:
                if not layer.addAttribute(_field(name, kind)):
                    raise ValueError('Field "%s" could not be added to the layer' % name)
        layer.updateFields()
        index = {name: layer.fields().lookupField(name) for name, _k in conv.specs}
        written = 0
        for feature in _features(layer, selected_only):
            point = feature_point(feature.geometry())
            if point is None:
                continue
            values = conv.values(point)
            layer.changeAttributeValues(feature.id(), {index[n]: values[n] for n in index})
            written += 1
    except Exception:
        layer.destroyEditCommand()
        raise
    layer.endEditCommand()
    return written


def vertices_layer(layer, formats, chosen_crs, selected_only=False):
    """A new memory point layer (layer CRS) with one point per vertex and its coordinates."""
    if not formats:
        raise ValueError("Choose at least one format")
    conv = Converter(layer.crs(), chosen_crs, formats)
    out = QgsVectorLayer("Point?crs=" + layer.crs().toWkt(), "%s vertices" % layer.name(), "memory")
    if not out.isValid():  # some CRSs do not round-trip as WKT in the URI
        out = QgsVectorLayer("Point", "%s vertices" % layer.name(), "memory")
        out.setCrs(layer.crs())
    fields = QgsFields()
    for name, kind in [("src_fid", "int"), ("part", "int"), ("ring", "int"), ("vertex", "int")] + conv.specs:
        fields.append(_field(name, kind))
    out.dataProvider().addAttributes(fields.toList())
    out.updateFields()
    features = []
    for src in _features(layer, selected_only):
        for part, ring, vertex, point in vertices(src.geometry()):
            f = QgsFeature(out.fields())
            f.setGeometry(QgsGeometry.fromPointXY(point))
            values = conv.values(point)
            f.setAttributes([src.id(), part, ring, vertex] + [values[n] for n, _k in conv.specs])
            features.append(f)
    out.dataProvider().addFeatures(features)
    out.updateExtents()
    return out


def as_table(layer, formats, chosen_crs, selected_only=False):
    """Tab-separated text with a header: one row per point feature, or per vertex otherwise."""
    if not formats:
        raise ValueError("Choose at least one format")
    conv = Converter(layer.crs(), chosen_crs, formats)
    names = [n for n, _k in conv.specs]

    def cell(v):
        return "" if v is None else str(v)

    if is_point_layer(layer):
        lines = ["\t".join(["fid"] + names)]
        for f in _features(layer, selected_only):
            point = feature_point(f.geometry())
            if point is not None:
                values = conv.values(point)
                lines.append("\t".join([str(f.id())] + [cell(values[n]) for n in names]))
    else:
        lines = ["\t".join(["fid", "part", "ring", "vertex"] + names)]
        for f in _features(layer, selected_only):
            for part, ring, vertex, point in vertices(f.geometry()):
                values = conv.values(point)
                lines.append("\t".join([str(f.id()), str(part), str(ring), str(vertex)]
                                       + [cell(values[n]) for n in names]))
    return "\n".join(lines) + "\n"
