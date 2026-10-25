# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Survey points from an ASCII DXF (Emlid Flow DXF export) without extra libraries.

What is read:

* ``POINT`` entities (X, Y, Z) in file order = survey order.
* The code: since Emlid Flow 15.12 each code has its own layers ("points,
  names and lines per code"), so a point's layer name, minus a trailing
  "points"/"point"/"pts" word, is its code. Points on a generic layer
  ("0", "points", …) get their code from a nearby label instead.
* Labels (``TEXT``/``MTEXT``, with "Include point labels"): every label is given
  to the nearest point within ``label_radius``. A label equal to the point's
  elevation is ignored; a label on a "name" layer, or the first label, is the
  name; a label that is a known code (when a code table is given) is the code;
  the rest is the description.
* ``INSERT`` blocks with ``ATTRIB`` tags NAME / CODE / DESCRIPTION / ELEVATION
  (other CAD exports) at the insertion point.

The exact layer and label layout of Emlid's export must be checked against a
real file; the rules above are deliberately tolerant.
"""

import math
import os
import re

from ..model import Survey, SurveyPoint
from .common import decode_bytes, parse_float

GENERIC_LAYERS = {"0", "points", "point", "pts", "survey points", "defpoints", "punkter"}
_LAYER_SUFFIX = re.compile(r"[\s_\-.]*(points?|pts|punkter)$", re.I)
_NAME_LAYER = re.compile(r"(^|[\s_\-.])(names?|labels?|navn)$", re.I)


def _pairs(text):
    lines = text.splitlines()
    for i in range(0, len(lines) - 1, 2):
        try:
            code = int(lines[i].strip())
        except ValueError:
            continue
        yield code, lines[i + 1].strip()


def _entities(text):
    """[(type, {group code: [values]})] from the ENTITIES section."""
    in_entities = False
    section_next = False
    current = None
    out = []
    for code, value in _pairs(text):
        if code == 0:
            if current is not None:
                out.append(current)
                current = None
            if value == "SECTION":
                section_next = True
                continue
            if value == "ENDSEC":
                in_entities = False
                continue
            if in_entities and value != "EOF":
                current = (value, {})
            continue
        if section_next and code == 2:
            in_entities = value == "ENTITIES"
            section_next = False
            continue
        if current is not None:
            current[1].setdefault(code, []).append(value)
    if current is not None:
        out.append(current)
    return out


def _first(d, code, default=None):
    v = d.get(code)
    return v[0] if v else default


def _clean_mtext(s):
    s = re.sub(r"\\[A-Za-z][^;\\]*;", "", s)
    s = s.replace("\\P", " ").replace("{", "").replace("}", "")
    return s.strip()


def layer_code(layer):
    """Code from a per-code layer name ('' for generic layers)."""
    name = (layer or "").strip()
    if name.lower() in GENERIC_LAYERS:
        return ""
    stripped = _LAYER_SUFFIX.sub("", name).strip(" _-.")
    return "" if stripped.lower() in GENERIC_LAYERS else stripped


def read_dxf(path, code_table=None, label_radius=1.5, text=None):
    if text is None:
        with open(path, "rb") as f:
            text = decode_bytes(f.read())
    if text.lstrip().startswith("AutoCAD Binary DXF"):
        raise ValueError("Binary DXF is not supported – export as ASCII DXF.")
    survey = Survey(source=os.path.basename(path), reader="dxf")
    labels = []          # (x, y, text, layer)
    inserts = []         # pending INSERT with attribs
    pending = None
    for etype, d in _entities(text):
        if etype == "POINT":
            x, y = parse_float(_first(d, 10)), parse_float(_first(d, 20))
            if x is None or y is None:
                continue
            layer = _first(d, 8, "")
            survey.points.append(SurveyPoint(
                seq=len(survey.points), name="", x=x, y=y, z=parse_float(_first(d, 30)),
                code=layer_code(layer), extra={"layer": layer}))
        elif etype in ("TEXT", "MTEXT"):
            x, y = parse_float(_first(d, 10)), parse_float(_first(d, 20))
            t = "".join(d.get(3, [])) + _first(d, 1, "") if etype == "MTEXT" else _first(d, 1, "")
            t = _clean_mtext(t) if etype == "MTEXT" else t.strip()
            if x is not None and y is not None and t:
                labels.append((x, y, t, _first(d, 8, "")))
        elif etype == "INSERT":
            pending = {"x": parse_float(_first(d, 10)), "y": parse_float(_first(d, 20)),
                       "z": parse_float(_first(d, 30)), "layer": _first(d, 8, ""), "attribs": {}}
            inserts.append(pending)
        elif etype == "ATTRIB" and pending is not None:
            pending["attribs"][(_first(d, 2, "") or "").upper()] = _first(d, 1, "")
        elif etype == "SEQEND":
            pending = None
    for ins in inserts:
        a = ins["attribs"]
        if not a or ins["x"] is None:
            continue
        z = parse_float(a.get("ELEVATION") or a.get("Z") or a.get("HEIGHT"))
        survey.points.append(SurveyPoint(
            seq=len(survey.points), name=a.get("NAME") or a.get("POINT") or a.get("ID") or "",
            x=ins["x"], y=ins["y"], z=z if z is not None else ins["z"],
            code=a.get("CODE") or layer_code(ins["layer"]),
            description=a.get("DESCRIPTION") or a.get("DESC") or "", extra={"layer": ins["layer"]}))
    _attach_labels(survey.points, labels, code_table, label_radius)
    for p in survey.points:
        if not p.name:
            p.name = str(p.seq + 1)
    if not survey.points:
        survey.warnings.append("No POINT entities in the DXF (lines alone cannot be used).")
    elif all(p.z is None or p.z == 0 for p in survey.points):
        survey.warnings.append("The DXF points have no elevations (Z = 0).")
    return survey


def _label_stem(layer):
    """Code part of a per-code label layer ("KK_names" → "KK"), '' otherwise."""
    if not _NAME_LAYER.search(layer or ""):
        return ""
    stem = _NAME_LAYER.sub("", layer).strip(" _-.")
    return "" if stem.lower() in GENERIC_LAYERS else stem


def _nearest(grid, cell, x, y, radius, accept):
    gx, gy = int(x // cell), int(y // cell)
    best, bd = None, radius
    reach = int(math.ceil(radius / cell))
    for i in range(-reach, reach + 1):
        for j in range(-reach, reach + 1):
            for p in grid.get((gx + i, gy + j), ()):
                dd = math.hypot(p.x - x, p.y - y)
                if dd <= bd and accept(p):
                    best, bd = p, dd
    return best


def _median(v):
    v = sorted(v)
    n = len(v)
    return 0.0 if not n else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0)


def _attach_labels(points, labels, code_table, radius):
    """Give each label to a point. CAD exports put labels at a fixed offset from
    their point, so the typical offset is estimated first (median of the
    nearest-point offsets) and labels are matched after removing it; a label on a
    per-code layer ("KK_names") only goes to a point with that code."""
    if not points or not labels:
        return
    cell = max(radius, 0.01)
    grid = {}
    for p in points:
        grid.setdefault((int(p.x // cell), int(p.y // cell)), []).append(p)
    offs = []
    for x, y, _t, layer in labels:
        stem = _label_stem(layer)
        p = _nearest(grid, cell, x, y, radius, lambda q: not stem or q.code == stem)
        if p is not None:
            offs.append((x - p.x, y - p.y))
    ox, oy = _median([o[0] for o in offs]), _median([o[1] for o in offs])
    got = {}
    for x, y, t, layer in labels:
        stem = _label_stem(layer)
        p = _nearest(grid, cell, x - ox, y - oy, radius, lambda q: not stem or q.code == stem)
        if p is not None:
            got.setdefault(p.seq, []).append((t, layer))
    for p in points:
        rest = []
        for t, layer in got.get(p.seq, []):
            v = parse_float(t)
            if v is not None and p.z is not None and re.fullmatch(r"[+-]?\d+([.,]\d+)?", t) \
                    and abs(v - p.z) < 0.006:
                continue  # elevation label
            if _NAME_LAYER.search(layer or "") and not p.name:
                p.name = t
            elif not p.code and code_table is not None and code_table.lookup(t) is not None:
                p.code = t
            else:
                rest.append(t)
        if not p.name and rest:
            p.name = rest.pop(0)
        if not p.code and rest and code_table is None:
            p.code = rest.pop(0)
        if rest:
            p.description = " ".join(rest)
