# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Long profile and text exports of a survey (pure Python).

Inputs are plain data so the functions work outside QGIS:

``sections``: list of ``SectionData`` (id, station, x, y, normal, points), points
left → right as ExtPoint-like objects (offset, z, x, y, source, point_type,
point, dhm_version), e.g. from ``SurveyState.section_data()``.

Formats:

* CSV of all section points (with source and terrain model version) and of the long profile.
* HEC-RAS geometry text (``.g01``): one river/reach with the centre line and one
  cross-section per section – station/elevation, bank stations, reach lengths
  to the next section downstream, Manning's n in three zones. River stations
  count upstream from the downstream end, as HEC-RAS expects.
* MIKE 11 / MIKE HYDRO River cross-sections as raw data text (the ``.txt`` that
  the cross-section editor imports): x/z with the markers as MIKE's bit flags
  ``<#1>`` left bank (marker 1), ``<#2>`` lowest point (marker 2), ``<#4>`` right
  bank (marker 3), combined when they fall on the same point.
"""

import csv
import io
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class SectionData:
    id: str
    station: float
    x: float
    y: float
    normal: Tuple[float, float]
    points: list = field(default_factory=list)
    status: str = ""


@dataclass
class LongRow:
    id: str
    station: float
    bed: Optional[float]
    water: Optional[float]
    bank_left: Optional[float]
    bank_right: Optional[float]
    terrain_left: Optional[float]      # terrain model at the outer end of the left extension
    terrain_right: Optional[float]


def _measured(points):
    return [e for e in points if e.source == "measured" and e.z is not None]


def long_profile(sections: List[SectionData]):
    """One row per section in station order: bed, water level, bank tops and terrain on both sides."""
    rows = []
    for s in sorted(sections, key=lambda s: s.station):
        m = _measured(s.points)
        beds = [e.z for e in m if e.point_type in ("bed", "knick")]
        ws = [e.z for e in m if e.point_type == "water_level"]
        left = [e for e in m if e.point_type == "bank_top" and e.offset < 0]
        right = [e for e in m if e.point_type == "bank_top" and e.offset > 0]
        tl = [e for e in s.points if e.source != "measured" and e.offset < 0 and e.z is not None]
        tr = [e for e in s.points if e.source != "measured" and e.offset > 0 and e.z is not None]
        rows.append(LongRow(
            s.id, s.station, min(beds) if beds else None, sum(ws) / len(ws) if ws else None,
            min(left, key=lambda e: e.offset).z if left else None,
            max(right, key=lambda e: e.offset).z if right else None,
            min(tl, key=lambda e: e.offset).z if tl else None,
            max(tr, key=lambda e: e.offset).z if tr else None))
    return rows


def _f(v, n=3):
    return "" if v is None else ("%." + str(n) + "f") % v


def sections_csv(sections, separator=";"):
    """All section points: profile, station, offset, x, y, z, name, code, type, source, terrain model."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=separator, lineterminator="\n")
    w.writerow(["profile_id", "station", "offset", "x", "y", "z", "name", "code", "point_type", "source",
                "dhm_version"])
    for s in sorted(sections, key=lambda s: s.station):
        for e in s.points:
            p = e.point
            w.writerow([s.id, _f(s.station, 2), _f(e.offset, 3), _f(e.x, 3), _f(e.y, 3), _f(e.z, 3),
                        p.name if p else "", p.code if p else "", e.point_type, e.source, e.dhm_version])
    return buf.getvalue()


def long_profile_csv(sections, separator=";"):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=separator, lineterminator="\n")
    w.writerow(["profile_id", "station", "bed", "water_level", "bank_top_left", "bank_top_right",
                "terrain_left", "terrain_right"])
    for r in long_profile(sections):
        w.writerow([r.id, _f(r.station, 2), _f(r.bed), _f(r.water), _f(r.bank_left), _f(r.bank_right),
                    _f(r.terrain_left), _f(r.terrain_right)])
    return buf.getvalue()


# -- HEC-RAS --------------------------------------------------------------------------------

def _fixed(values, width=8, per_line=10, decimals=2):
    """HEC-RAS fixed-width number block: ``per_line`` fields of ``width`` characters."""
    out = []
    line = ""
    for i, v in enumerate(values):
        s = ("%." + str(decimals) + "f") % v
        if len(s) > width:
            s = ("%." + str(max(decimals - (len(s) - width), 0)) + "f") % v
        line += s.rjust(width)
        if (i + 1) % per_line == 0:
            out.append(line)
            line = ""
    if line:
        out.append(line)
    return out


def _bank_sta(s, sta0):
    m = _measured(s.points)
    left = [e.offset for e in m if e.point_type == "bank_top" and e.offset < 0]
    right = [e.offset for e in m if e.point_type == "bank_top" and e.offset > 0]
    pts = [e.offset for e in s.points if e.z is not None]
    lo = min(left) if left else min(pts)
    hi = max(right) if right else max(pts)
    return lo - sta0, hi - sta0


def hecras_geometry(sections, centerline_coords, title="GeoDrafter Stream Survey", river="Stream",
                    reach="Survey", manning=(0.06, 0.035, 0.06), version="6.00"):
    """HEC-RAS geometry file text (``.g01``) for one reach."""
    secs = sorted(sections, key=lambda s: s.station)
    if not secs:
        raise ValueError("No sections to export.")
    last = secs[-1].station
    lines = ["Geom Title=%s" % title, "Program Version=%s" % version,
             "Viewing Rectangle= 0 , 1 , 1 , 0 ", ""]
    lines.append("River Reach=%-16s,%-16s" % (river[:16], reach[:16]))
    lines.append("Reach XY= %d " % len(centerline_coords))
    xy = []
    for x, y in centerline_coords:
        xy += [x, y]
    lines += _fixed(xy, width=16, per_line=4, decimals=3)
    lines.append("Rch Text X Y=%s,%s" % (_f(centerline_coords[0][0]), _f(centerline_coords[0][1])))
    lines.append("Reverse River Text= 0 ")
    lines.append("")
    for i, s in enumerate(secs):
        rs = last - s.station
        nxt = secs[i + 1].station - s.station if i + 1 < len(secs) else 0.0
        pts = [e for e in s.points if e.z is not None]
        sta0 = pts[0].offset
        d = _f(nxt, 2)
        lines.append("Type RM Length L Ch R = 1 ,%-8s,%s,%s,%s" % ("%.2f" % rs, d, d, d))
        lines.append("BEGIN DESCRIPTION:")
        lines.append("Section %s, station %.2f (GeoDrafter Stream Survey)" % (s.id, s.station))
        lines.append("END DESCRIPTION:")
        nx, ny = s.normal
        a, b = pts[0], pts[-1]
        lines.append("XS GIS Cut Line=2")
        lines += _fixed([s.x + a.offset * nx, s.y + a.offset * ny, s.x + b.offset * nx, s.y + b.offset * ny],
                        width=16, per_line=4, decimals=3)
        lines.append("Node Last Edited Time=")
        lines.append("#Sta/Elev= %d " % len(pts))
        se = []
        for e in pts:
            se += [e.offset - sta0, e.z]
        lines += _fixed(se, width=8, per_line=10, decimals=2)
        lb, rb = _bank_sta(s, sta0)
        lines.append("#Mann= 3 , 0 , 0 ")
        lines += _fixed([0.0, manning[0], 0.0, lb, manning[1], 0.0, rb, manning[2], 0.0], 8, 9, 3)
        lines.append("Bank Sta=%s,%s" % (_f(lb, 2), _f(rb, 2)))
        lines.append("XS Rating Curve= 0 ,0")
        lines.append("Exp/Cntr=0.3,0.1")
        lines.append("")
    return "\n".join(lines) + "\n"


# -- MIKE -----------------------------------------------------------------------------------

def mike_cross_sections(sections, river="Stream", topo_id="Survey"):
    """MIKE 11 / MIKE HYDRO River cross-section raw data (text import of the cross-section editor)."""
    out = []
    for s in sorted(sections, key=lambda s: s.station):
        pts = [e for e in s.points if e.z is not None]
        if not pts:
            continue
        m = _measured(s.points)
        left = [i for i, e in enumerate(pts) if e.point_type == "bank_top" and e.offset < 0]
        right = [i for i, e in enumerate(pts) if e.point_type == "bank_top" and e.offset > 0]
        low = min(range(len(pts)), key=lambda i: pts[i].z if pts[i] in m else float("inf"))
        mark = {}
        for i, bit in ((left[0] if left else 0, 1), (low, 2), (right[-1] if right else len(pts) - 1, 4)):
            mark[i] = mark.get(i, 0) | bit
        x0 = pts[0].offset
        out += [topo_id, river, "%14.3f" % s.station, "COORDINATES", "    0", "FLOW DIRECTION", "    0",
                "PROTECT DATA", "    0", "DATUM", "      0.00", "RADIUS TYPE", "    0",
                "DIVIDE X-Section", "0",
                "SECTION ID", "%s" % s.id, "INTERPOLATED", "    0", "ANGLE", "    0.00   0",
                "RESISTANCE NUMBERS", "   2  0     1.000     1.000     1.000    1.000    1.000",
                "PROFILE        %d" % len(pts)]
        for i, e in enumerate(pts):
            code = mark.get(i, 0)
            out.append("%10.3f %10.3f     1.000     <#%d>     0     0.000     0" % (e.offset - x0, e.z, code))
        out += ["LEVEL PARAMS", "   0  0    0.000  0    0.000  20", "*******************************"]
    return "\n".join(out) + "\n"
