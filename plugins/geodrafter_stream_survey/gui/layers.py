# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Results → GeoPackage layers, and their map styles.

One GeoPackage per survey, all in EPSG:25832:

points            surveyed points in survey order, with code, type and GNSS quality
centerline        the stream centre line (downstream) with its stationing
profiles          section lines with station and join status
profile_points    measured and terrain-model points of every section (station, offset, source)
extensions        the terrain-model part of each section, as lines (dashed on the map)
structures        structures and drains located on station
checks            errors, warnings and control points (red rings on the map)
"""

import os

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCategorizedSymbolRenderer, QgsFeature, QgsGeometry,
    QgsLineSymbol, QgsMarkerSymbol, QgsPointXY, QgsProject, QgsRendererCategory, QgsRuleBasedRenderer,
    QgsVectorFileWriter, QgsVectorLayer, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling)

from ..core.codes import TYPE_COLORS
from .i18n import tr

CRS = "EPSG:25832"
GROUP_NAME = "GeoDrafter Stream Survey"

SCHEMAS = {
    "points": ("Point", [("seq", "int"), ("name", "str"), ("code", "str"), ("point_type", "str"),
                         ("code_known", "int"), ("z", "float"), ("description", "str"),
                         ("solution_status", "str"), ("rms_e", "float"), ("rms_n", "float"),
                         ("rms_z", "float"), ("antenna_height", "float"), ("time_start", "str"),
                         ("time_end", "str"), ("cs_name", "str"), ("profile_id", "str")]),
    "centerline": ("LineString", [("source", "str"), ("length", "float"), ("station_start", "float"),
                                  ("station_end", "float"), ("fetched", "str"), ("attribution", "str")]),
    "profiles": ("LineString", [("profile_id", "str"), ("station", "float"), ("status", "str"),
                                ("n_points", "int"), ("max_along", "float"), ("status_left", "str"),
                                ("dz_left", "float"), ("status_right", "str"), ("dz_right", "float"),
                                ("control_mean", "float"), ("control_max", "float"), ("dhm_version", "str")]),
    "profile_points": ("Point", [("profile_id", "str"), ("station", "float"), ("offset", "float"),
                                 ("side", "str"), ("z", "float"), ("name", "str"), ("code", "str"),
                                 ("point_type", "str"), ("source", "str"), ("dhm_version", "str"),
                                 ("along", "float"), ("shift", "float"), ("seq", "int")]),
    "extensions": ("LineString", [("profile_id", "str"), ("side", "str"), ("status", "str"),
                                  ("dz", "float"), ("dhm_version", "str")]),
    "structures": ("Point", [("name", "str"), ("code", "str"), ("point_type", "str"), ("station", "float"),
                             ("offset", "float"), ("z", "float"), ("description", "str"), ("bed_z", "float"),
                             ("water_z", "float"), ("above_bed", "float"), ("below_water", "float")]),
    "checks": ("Point", [("severity", "str"), ("kind", "str"), ("profile_id", "str"), ("message", "str"),
                         ("value", "float")]),
}


def _fields_spec(fields):
    out = []
    for name, t in fields:
        out.append("field=%s:%s" % (name, {"int": "integer", "float": "double", "str": "string"}[t]))
    return "&".join(out)


def memory_layer(name):
    geom, fields = SCHEMAS[name]
    uri = "%s?crs=%s&%s" % (geom, CRS, _fields_spec(fields))
    return QgsVectorLayer(uri, name, "memory")


def _num(v):
    return None if v is None else float(v)


def _feature(layer, geom, values):
    f = QgsFeature(layer.fields())
    f.setGeometry(geom)
    for k, v in values.items():
        f[k] = v
    return f


def build_layers(state):
    """Memory layers from a SurveyState (see project.py). Empty layers for steps not run yet."""
    layers = {n: memory_layer(n) for n in SCHEMAS}
    feats = {n: [] for n in SCHEMAS}
    pid_of = {}
    for pr in state.profiles or []:
        for pp in pr.points:
            pid_of[pp.point.seq] = pr.id
    if state.survey is not None:
        lay = layers["points"]
        for p in state.survey.points:
            feats["points"].append(_feature(lay, QgsGeometry.fromPointXY(QgsPointXY(p.x, p.y)), {
                "seq": p.seq, "name": p.name, "code": p.code, "point_type": p.point_type,
                "code_known": int(p.code_known), "z": _num(p.z), "description": p.description,
                "solution_status": p.solution_status, "rms_e": _num(p.rms_e), "rms_n": _num(p.rms_n),
                "rms_z": _num(p.rms_z), "antenna_height": _num(p.antenna_height), "time_start": p.time_start,
                "time_end": p.time_end, "cs_name": p.cs_name, "profile_id": pid_of.get(p.seq)}))
    cl = state.centerline
    if cl is not None:
        lay = layers["centerline"]
        feats["centerline"].append(_feature(
            lay, QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in cl.coords]),
            {"source": cl.source, "length": cl.length, "station_start": cl.station_shift,
             "station_end": cl.station_shift + cl.length, "fetched": getattr(state, "line_fetched", ""),
             "attribution": getattr(state, "line_attribution", "")}))
    ext_by_id = {e.profile.id: e for e in (state.extended or [])}
    for pr in state.profiles or []:
        ext = ext_by_id.get(pr.id)
        a, b = pr.line(extra=0.0)
        if ext and ext.points:
            nx, ny = pr.normal
            lo, hi = ext.points[0].offset, ext.points[-1].offset
            a = (pr.x + lo * nx, pr.y + lo * ny)
            b = (pr.x + hi * nx, pr.y + hi * ny)
        sides = ext.sides if ext else {}
        cd = ext.control_deviation() if ext else None
        feats["profiles"].append(_feature(layers["profiles"], QgsGeometry.fromPolylineXY(
            [QgsPointXY(*a), QgsPointXY(*b)]), {
                "profile_id": pr.id, "station": pr.station, "status": ext.status if ext else "",
                "n_points": len(pr.points), "max_along": pr.max_along(),
                "status_left": sides["left"].status if "left" in sides else "",
                "dz_left": _num(sides["left"].dz) if "left" in sides else None,
                "status_right": sides["right"].status if "right" in sides else "",
                "dz_right": _num(sides["right"].dz) if "right" in sides else None,
                "control_mean": cd[0] if cd else None, "control_max": cd[1] if cd else None,
                "dhm_version": ext.dhm_version if ext else ""}))
        pts = ext.points if ext else None
        lay = layers["profile_points"]
        if pts is None:
            for pp in pr.points:
                p = pp.point
                feats["profile_points"].append(_feature(lay, QgsGeometry.fromPointXY(QgsPointXY(p.x, p.y)), {
                    "profile_id": pr.id, "station": pr.station, "offset": pp.offset, "side": pp.side,
                    "z": _num(p.z), "name": p.name, "code": p.code, "point_type": p.point_type,
                    "source": "measured", "dhm_version": "", "along": pp.along, "shift": 0.0, "seq": p.seq}))
        else:
            along = {pp.point.seq: pp.along for pp in pr.points}
            for e in pts:
                p = e.point
                side = "center" if abs(e.offset) <= 0.005 else ("right" if e.offset > 0 else "left")
                feats["profile_points"].append(_feature(lay, QgsGeometry.fromPointXY(QgsPointXY(e.x, e.y)), {
                    "profile_id": pr.id, "station": pr.station, "offset": e.offset, "side": side,
                    "z": _num(e.z), "name": p.name if p else "", "code": p.code if p else "",
                    "point_type": e.point_type, "source": e.source, "dhm_version": e.dhm_version,
                    "along": along.get(p.seq, 0.0) if p else 0.0, "shift": e.shift,
                    "seq": p.seq if p else None}))
            for side, res in ext.sides.items():
                outer = [e for e in pts if e.source != "measured" and ((e.offset < 0) == (side == "left"))]
                if not outer or res.join_offset is None:
                    continue
                far = min(outer, key=lambda e: e.offset) if side == "left" else max(
                    outer, key=lambda e: e.offset)
                nx, ny = pr.normal
                start = (pr.x + res.join_offset * nx, pr.y + res.join_offset * ny)
                feats["extensions"].append(_feature(layers["extensions"], QgsGeometry.fromPolylineXY(
                    [QgsPointXY(*start), QgsPointXY(far.x, far.y)]), {
                        "profile_id": pr.id, "side": side, "status": res.status, "dz": _num(res.dz),
                        "dhm_version": ext.dhm_version}))
    by_seq = {s.point.seq: s for s in (getattr(state, "structures", None) or [])}
    for lp in state.located or []:
        p = lp.point
        sr = by_seq.get(p.seq)
        pt = QgsGeometry.fromPointXY(QgsPointXY(p.x, p.y))
        feats["structures"].append(_feature(layers["structures"], pt, {
            "name": p.name, "code": p.code, "point_type": p.point_type, "station": lp.station,
            "offset": lp.offset, "z": _num(p.z), "description": p.description,
            "bed_z": _num(sr.bed_z) if sr else None, "water_z": _num(sr.water_z) if sr else None,
            "above_bed": _num(sr.above_bed) if sr else None,
            "below_water": _num(sr.below_water) if sr else None}))
    for c in state.checks or []:
        feats["checks"].append(_feature(layers["checks"], QgsGeometry.fromPointXY(QgsPointXY(c.x, c.y)), {
            "severity": c.severity, "kind": c.kind, "profile_id": c.profile_id, "message": c.message,
            "value": _num(c.value)}))
    for n, lay in layers.items():
        lay.dataProvider().addFeatures(feats[n])
        lay.updateExtents()
    return layers


def write_geopackage(layers, path, transform_context=None):
    """Write all layers to ``path`` (overwriting the file). Returns a list of errors."""
    ctx = transform_context or QgsProject.instance().transformContext()
    errors = []
    first = True
    for name in SCHEMAS:
        lay = layers[name]
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = name
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile if first
            else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer)
        res = QgsVectorFileWriter.writeAsVectorFormatV3(lay, path, ctx, opts)
        code = res[0] if isinstance(res, tuple) else res
        code = getattr(code, "value", code)
        if int(code) != 0:
            errors.append("%s: %s" % (name, res[1] if isinstance(res, tuple) else code))
        first = False
    return errors


LAYER_TITLES = {
    "checks": "Data check", "structures": "Structures and drains", "profile_points": "Section points",
    "extensions": "Terrain extension", "profiles": "Cross-sections", "centerline": "Centre line",
    "points": "Survey points",
}
ORDER = ["checks", "structures", "profile_points", "extensions", "profiles", "centerline", "points"]


def load_geopackage(path, project=None, group_name=None):
    """Add (or refresh) the survey's layers in a layer tree group. Returns {name: layer}."""
    project = project or QgsProject.instance()
    root = project.layerTreeRoot()
    title = group_name or "%s – %s" % (GROUP_NAME, os.path.splitext(os.path.basename(path))[0])
    group = root.findGroup(title)
    if group is not None:
        for child in list(group.findLayers()):
            project.removeMapLayer(child.layerId())
    else:
        group = root.insertGroup(0, title)
    out = {}
    for name in ORDER:
        lay = QgsVectorLayer("%s|layername=%s" % (path, name), tr(LAYER_TITLES[name]), "ogr")
        if not lay.isValid():
            continue
        style_layer(name, lay)
        project.addMapLayer(lay, False)
        group.addLayer(lay)
        out[name] = lay
    return out


def _marker(color, size=2.4, shape="circle", outline="#ffffff"):
    return QgsMarkerSymbol.createSimple({"name": shape, "color": color, "size": str(size),
                                         "outline_color": outline, "outline_width": "0.2"})


def style_layer(name, layer):
    """Map style: types coloured as in the code library, terrain extension dashed, errors as red rings,
    the selected section highlighted by QGIS' selection colour."""
    if name in ("points", "profile_points", "structures"):
        cats = [QgsRendererCategory(t, _marker(col, 2.6), t) for t, col in TYPE_COLORS.items()]
        if name == "profile_points":
            rules = QgsRuleBasedRenderer(QgsRuleBasedRenderer.Rule(None))
            base = rules.rootRule()
            measured = QgsRuleBasedRenderer.Rule(_marker("#1f3a5f", 2.2), 0, 0, "\"source\" = 'measured'",
                                                 tr("Measured"))
            dhm = QgsRuleBasedRenderer.Rule(_marker("#ff6a00", 1.6, "diamond", "#ff6a00"), 0, 0,
                                            "\"source\" = 'dhm'", tr("Terrain model"))
            trans = QgsRuleBasedRenderer.Rule(_marker("#f1c40f", 1.8, "diamond", "#b7950b"), 0, 0,
                                              "\"source\" = 'transition'", tr("Transition"))
            for r in (measured, trans, dhm):
                base.appendChild(r)
            layer.setRenderer(rules)
        else:
            layer.setRenderer(QgsCategorizedSymbolRenderer("point_type", cats))
        if name == "structures":
            _label(layer, "name")
    elif name == "centerline":
        layer.setRenderer(_single(QgsLineSymbol.createSimple(
            {"line_color": "#2fa4e7", "line_width": "0.8"})))
    elif name == "profiles":
        rules = QgsRuleBasedRenderer(QgsRuleBasedRenderer.Rule(None))
        base = rules.rootRule()
        for expr, col, label in (("\"status\" = 'error'", "#c0392b", tr("Error")),
                                 ("\"status\" = 'review'", "#e67e22", tr("Review")),
                                 ("ELSE", "#1f3a5f", tr("Section"))):
            sym = QgsLineSymbol.createSimple({"line_color": col, "line_width": "0.5"})
            r = QgsRuleBasedRenderer.Rule(sym, 0, 0, None if expr == "ELSE" else expr, label)
            if expr == "ELSE":
                r.setIsElse(True)
            base.appendChild(r)
        layer.setRenderer(rules)
        _label(layer, "concat(\"profile_id\", '  st. ', format_number(\"station\", 1))", expression=True)
    elif name == "extensions":
        layer.setRenderer(_single(QgsLineSymbol.createSimple(
            {"line_color": "#ff6a00", "line_width": "0.5", "line_style": "dash"})))
    elif name == "checks":
        rules = QgsRuleBasedRenderer(QgsRuleBasedRenderer.Rule(None))
        base = rules.rootRule()
        ring = QgsMarkerSymbol.createSimple({"name": "circle", "color": "0,0,0,0", "size": "6",
                                             "outline_color": "#e3001b", "outline_width": "0.7"})
        warn = QgsMarkerSymbol.createSimple({"name": "circle", "color": "0,0,0,0", "size": "5",
                                             "outline_color": "#e67e22", "outline_width": "0.5"})
        ctrl = QgsMarkerSymbol.createSimple({"name": "cross2", "color": "#8c6d3f", "size": "3",
                                             "outline_color": "#8c6d3f", "outline_width": "0.4"})
        for sym, expr, label in ((ring, "\"severity\" = 'error'", tr("Error")),
                                 (warn, "\"severity\" = 'warning'", tr("Warning")),
                                 (ctrl, "\"severity\" = 'info'", tr("Control point"))):
            base.appendChild(QgsRuleBasedRenderer.Rule(sym, 0, 0, expr, label))
        layer.setRenderer(rules)
    if hasattr(layer, "setSelectionColor"):          # QGIS ≥ 3.38: the selected section stands out
        layer.setSelectionColor(QColor("#ffd400"))


def _single(symbol):
    from qgis.core import QgsSingleSymbolRenderer
    return QgsSingleSymbolRenderer(symbol)


def _label(layer, field, expression=False):
    s = QgsPalLayerSettings()
    s.fieldName = field
    s.isExpression = expression
    layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
    layer.setLabelsEnabled(True)
