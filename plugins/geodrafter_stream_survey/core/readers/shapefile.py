# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Point shapefiles (Emlid Flow shapefile export) without GDAL.

Reads Point, PointZ and PointM records from ``.shp`` with attributes from
``.dbf`` (field names are cut to 10 characters, matched as such) and the CRS
name from ``.prj``. A ``.zip`` (Emlid exports one) is opened and every point
shapefile inside is read; line shapefiles are ignored – the points carry the
survey. Record order = survey order.
"""

import io
import os
import struct
import zipfile

from ..model import Survey
from .common import decode_bytes, map_columns, point_from_fields

POINT_TYPES = {1: "Point", 11: "PointZ", 21: "PointM"}


def _read_shp(data):
    if len(data) < 100 or struct.unpack(">i", data[:4])[0] != 9994:
        raise ValueError("Not a shapefile (.shp)")
    shape_type = struct.unpack("<i", data[32:36])[0]
    pts = []
    pos = 100
    while pos + 8 <= len(data):
        _num, length = struct.unpack(">2i", data[pos:pos + 8])
        content = data[pos + 8:pos + 8 + 2 * length]
        pos += 8 + 2 * length
        if len(content) < 4:
            break
        st = struct.unpack("<i", content[:4])[0]
        if st == 0:
            pts.append(None)  # null shape keeps its place so attributes stay aligned
            continue
        if st not in POINT_TYPES:
            raise ValueError("Shapefile type %d is not a point shapefile" % st)
        x, y = struct.unpack("<2d", content[4:20])
        z = struct.unpack("<d", content[20:28])[0] if st == 11 and len(content) >= 28 else None
        pts.append((x, y, z))
    return shape_type, pts


def _read_dbf(data):
    if len(data) < 32:
        return [], []
    nrec, hlen, rlen = struct.unpack("<IHH", data[4:12])
    fields = []
    pos = 32
    while pos < hlen - 1 and data[pos] != 0x0D:
        raw = data[pos:pos + 32]
        name = raw[:11].split(b"\x00")[0].decode("latin-1").strip()
        ftype = chr(raw[11])
        flen = raw[16]
        fields.append((name, ftype, flen))
        pos += 32
    # code page byte 29: 0x57 = ANSI (cp1252); utf-8 is common from modern tools
    records = []
    pos = hlen
    for _ in range(nrec):
        rec = data[pos:pos + rlen]
        pos += rlen
        if not rec or rec[:1] == b"*":  # deleted
            records.append(None)
            continue
        off = 1
        row = []
        for _name, _t, flen in fields:
            row.append(decode_bytes(rec[off:off + flen]).strip())
            off += flen
        records.append(row)
    return [f[0] for f in fields], records


def _cs_from_prj(prj_text):
    if not prj_text:
        return ""
    t = prj_text.strip()
    if t.upper().startswith(("PROJCS[", "GEOGCS[", "PROJCRS[", "GEOGCRS[", "COMPD_CS[", "COMPOUNDCRS[")):
        start = t.find('"')
        end = t.find('"', start + 1)
        if start >= 0 and end > start:
            return t[start + 1:end].replace("_", " ")
    return ""


def read_shapefile_bytes(shp, dbf=None, prj=None, source="", columns=None):
    _type, pts = _read_shp(shp)
    headers, records = _read_dbf(dbf) if dbf else ([], [])
    cols = map_columns(headers, columns, dbf=True) if headers else {}
    cs = _cs_from_prj(decode_bytes(prj)) if prj else ""
    survey = Survey(source=os.path.basename(source), reader="shapefile")
    used = set(cols.values())
    for i, xyz in enumerate(pts):
        if xyz is None:
            continue
        row = records[i] if i < len(records) and records[i] is not None else []
        values = {k: (row[j] if j < len(row) else "") for k, j in cols.items()}
        values["x"], values["y"] = repr(xyz[0]), repr(xyz[1])
        if xyz[2] is not None and not values.get("z"):
            values["z"] = repr(xyz[2])
        if cs and not values.get("cs_name"):
            values["cs_name"] = cs
        extra = {headers[j]: row[j] for j in range(min(len(headers), len(row)))
                 if j not in used and row[j]}
        p = point_from_fields(len(survey.points), values, extra=extra)
        if p is not None:
            survey.points.append(p)
    if survey.points and all(p.z is None for p in survey.points):
        survey.warnings.append("The shapefile has no elevations (no Z and no Elevation field).")
    return survey


def read_shapefile(path, columns=None):
    """Read a point shapefile (.shp with .dbf/.prj beside it) or a .zip of shapefiles."""
    if path.lower().endswith(".zip"):
        return _read_zip(path, columns)
    base = os.path.splitext(path)[0]

    def sidecar(ext):
        for e in (ext, ext.upper()):
            if os.path.exists(base + e):
                with open(base + e, "rb") as f:
                    return f.read()
        return None

    with open(path, "rb") as f:
        shp = f.read()
    return read_shapefile_bytes(shp, sidecar(".dbf"), sidecar(".prj"), path, columns)


def _read_zip(path, columns=None):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        lower = {n.lower(): n for n in names}
        merged = Survey(source=os.path.basename(path), reader="shapefile")
        for n in sorted(names):
            if not n.lower().endswith(".shp"):
                continue
            shp = z.read(n)
            if struct.unpack("<i", shp[32:36])[0] not in POINT_TYPES:
                continue
            stem = n[:-4].lower()
            dbf = z.read(lower[stem + ".dbf"]) if stem + ".dbf" in lower else None
            prj = z.read(lower[stem + ".prj"]) if stem + ".prj" in lower else None
            s = read_shapefile_bytes(shp, dbf, prj, n, columns)
            for p in s.points:
                p.seq = len(merged.points)
                merged.points.append(p)
            merged.warnings.extend(s.warnings)
    if not merged.points:
        merged.warnings.append("No point shapefile with points in %s." % os.path.basename(path))
    return merged


def write_point_shapefile(points, fields, z=True):
    """Minimal writer for tests: (shp, shx, dbf) bytes for [(x, y, z, {field: value})]."""
    st = 11 if z else 1
    recs = []
    for i, (x, y, zz, _a) in enumerate(points):
        body = struct.pack("<i2d", st, x, y) + (struct.pack("<2d", zz or 0.0, 0.0) if z else b"")
        recs.append(struct.pack(">2i", i + 1, len(body) // 2) + body)
    xs = [p[0] for p in points] or [0]
    ys = [p[1] for p in points] or [0]

    def header(total_len):
        return (struct.pack(">i5ii", 9994, 0, 0, 0, 0, 0, total_len // 2)
                + struct.pack("<2i4d4d", 1000, st, min(xs), min(ys), max(xs), max(ys), 0, 0, 0, 0))
    body = b"".join(recs)
    shp = header(100 + len(body)) + body
    shx = io.BytesIO()
    off = 100
    for r in recs:
        shx.write(struct.pack(">2i", off // 2, (len(r) - 8) // 2))
        off += len(r)
    shx = header(100 + 8 * len(recs)) + shx.getvalue()
    flen = 40
    hlen = 32 + 32 * len(fields) + 1
    dbf = io.BytesIO()
    dbf.write(struct.pack("<4BIHH20x", 3, 126, 10, 24, len(points), hlen, 1 + flen * len(fields)))
    for name in fields:
        dbf.write(struct.pack("<11sc4xBB14x", name.encode("latin-1")[:10], b"C", flen, 0))
    dbf.write(b"\r")
    for _x, _y, _z, attrs in points:
        dbf.write(b" " + b"".join(str(attrs.get(n, "")).encode("utf-8")[:flen].ljust(flen) for n in fields))
    dbf.write(b"\x1a")
    return shp, shx, dbf.getvalue()
