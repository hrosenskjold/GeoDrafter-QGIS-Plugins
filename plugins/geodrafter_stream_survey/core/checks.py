# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Structures and drains on station, and the data check rules (pure Python).

Every rule is a small function returning ``Check`` findings with a place
(x, y in EPSG:25832) so the list can zoom there. The limits live in
``CheckSettings`` and can be saved per municipality (YAML).
"""

import os
from dataclasses import asdict, dataclass, fields
from typing import Optional

SECTION_TYPES = ("bed", "bank_top", "bank_toe", "water_level", "terrain", "knick")


@dataclass
class Check:
    severity: str           # "error", "warning", "info"
    kind: str               # short key, e.g. "terrain_error", "no_water_level", "rms"
    message: str
    x: float = 0.0
    y: float = 0.0
    profile_id: str = ""
    value: Optional[float] = None


@dataclass
class CheckSettings:
    name: str = "GeoDrafter standard"
    max_spacing: float = 120.0        # largest distance between sections [m]
    max_along: float = 1.0            # point further from its section line [m]
    max_rms_z: float = 0.03           # Elevation RMS [m]
    require_fix: bool = True          # GNSS points must be FIX
    bed_above_water_tol: float = 0.0  # bed may lie this much above the water level [m]
    max_dhm_jump: float = 0.10        # terrain model vs bank top [m] (same as the join tolerance)
    require_water_level: bool = True
    require_bank_tops: bool = True    # a bank top on both sides
    expected_cs: str = "ETRS89 / UTM zone 32N + DVR90"

    def to_dict(self):
        return asdict(self)


def settings_from_dict(d):
    known = {f.name: f for f in fields(CheckSettings)}
    kw = {}
    for k, v in (d or {}).items():
        if k in known:
            t = known[k].type
            kw[k] = (bool(v) if t in (bool, "bool") else float(v) if t in (float, "float") else str(v))
    return CheckSettings(**kw)


def save_settings(settings, path):
    import yaml
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(settings.to_dict(), f, allow_unicode=True, sort_keys=False)


def load_settings(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        s = settings_from_dict(yaml.safe_load(f) or {})
    if not s.name:
        s.name = os.path.splitext(os.path.basename(path))[0]
    return s


# -- structures and drains --------------------------------------------------------------------

@dataclass
class StructureResult:
    located: object               # geometry.LocatedPoint
    bed_z: Optional[float] = None
    water_z: Optional[float] = None

    @property
    def point(self):
        return self.located.point

    @property
    def above_bed(self):
        """Height of the point above the stream bed at its station (drain invert − bed)."""
        z = self.point.z
        return None if z is None or self.bed_z is None else z - self.bed_z

    @property
    def below_water(self):
        """Depth of the point below the water level at its station (water − drain invert)."""
        z = self.point.z
        return None if z is None or self.water_z is None else self.water_z - z


def section_bed(points):
    zs = [e.z for e in points if e.z is not None and e.point_type in ("bed", "knick")
          and getattr(e, "source", "measured") == "measured"]
    return min(zs) if zs else None


def section_water(points):
    zs = [e.z for e in points if e.z is not None and e.point_type == "water_level"]
    return sum(zs) / len(zs) if zs else None


def interpolate(station, samples):
    """Linear interpolation of (station, value) samples; nearest value outside; None without samples."""
    s = sorted((a, b) for a, b in samples if b is not None)
    if not s:
        return None
    if station <= s[0][0]:
        return s[0][1]
    if station >= s[-1][0]:
        return s[-1][1]
    for (a0, v0), (a1, v1) in zip(s, s[1:]):
        if a0 <= station <= a1:
            return v0 if a1 == a0 else v0 + (v1 - v0) * (station - a0) / (a1 - a0)
    return s[-1][1]


def locate_structures(located, profiles, section_points):
    """StructureResults for the single points, with bed and water level interpolated from the sections.

    section_points(pid) -> the points of a section (ExtPoint-like: z, point_type, source)."""
    beds = [(pr.station, section_bed(section_points(pr.id))) for pr in profiles]
    water = [(pr.station, section_water(section_points(pr.id))) for pr in profiles]
    out = []
    for lp in sorted(located, key=lambda lp: lp.station):
        out.append(StructureResult(lp, interpolate(lp.station, beds), interpolate(lp.station, water)))
    return out


# -- rules ------------------------------------------------------------------------------------

def check_sections(profiles, section_points, settings):
    out = []
    for pr in profiles:
        pts = section_points(pr.id)
        measured = [e for e in pts if getattr(e, "source", "measured") == "measured"]
        types = [e.point_type for e in measured]
        nx, ny = pr.normal
        if settings.require_bank_tops:
            for side, sign in (("left", -1), ("right", 1)):
                if not any(e.point_type == "bank_top" and e.offset * sign > 0 for e in measured):
                    out.append(Check("warning", "no_bank_top", "Section %s: no bank top on the %s side."
                                     % (pr.id, side), pr.x + sign * 3 * nx, pr.y + sign * 3 * ny, pr.id))
        if settings.require_water_level and "water_level" not in types:
            out.append(Check("warning", "no_water_level", "Section %s: no water level." % pr.id, pr.x, pr.y,
                             pr.id))
        ws = section_water(measured)
        if ws is not None:
            for e in measured:
                if e.point_type == "bed" and e.z is not None and e.z > ws + settings.bed_above_water_tol:
                    msg = "Section %s: bed point %s is %.2f m above the water level." % (
                        pr.id, e.name or "?", e.z - ws)
                    out.append(Check("error", "bed_above_water", msg, e.x, e.y, pr.id, e.z - ws))
        for pp in pr.points:
            if abs(pp.along) > settings.max_along:
                p = pp.point
                msg = "Section %s: point %s is %.2f m from the section line (limit %.2f m)." % (
                    pr.id, p.name, abs(pp.along), settings.max_along)
                out.append(Check("warning", "far_from_line", msg, p.x, p.y, pr.id, abs(pp.along)))
    for a, b in zip(profiles, profiles[1:]):
        d = b.station - a.station
        if d > settings.max_spacing:
            out.append(Check("warning", "spacing", "Sections %s – %s are %.0f m apart (limit %.0f m)."
                             % (a.id, b.id, d, settings.max_spacing), (a.x + b.x) / 2, (a.y + b.y) / 2,
                             b.id, d))
    return out


def check_dhm(extended, settings):
    out = []
    for ext in extended or []:
        pr = ext.profile
        nx, ny = pr.normal
        for side, res in ext.sides.items():
            if res.dz is not None and abs(res.dz) > settings.max_dhm_jump and res.status != "removed":
                off = res.join_offset or 0.0
                msg = "Section %s: the terrain model differs %.2f m from the %s bank top (limit %.2f m)." % (
                    pr.id, res.dz, side, settings.max_dhm_jump)
                out.append(Check("error" if res.status == "error" else "warning", "dhm_jump", msg,
                                 pr.x + off * nx, pr.y + off * ny, pr.id, res.dz))
    return out


def check_gnss(points, settings):
    out = []
    for p in points:
        if settings.require_fix and p.solution_status and p.solution_status != "FIX":
            msg = "Point %s: solution %s, not FIX." % (p.name, p.solution_status)
            out.append(Check("warning", "not_fix", msg, p.x, p.y))
        if p.rms_z is not None and p.rms_z > settings.max_rms_z:
            out.append(Check("warning", "rms", "Point %s: elevation RMS %.3f m (limit %.3f m)."
                             % (p.name, p.rms_z, settings.max_rms_z), p.x, p.y, value=p.rms_z))
    return out


def check_cs(points, settings):
    from .readers.common import check_crs

    class _S:
        def __init__(self, pts):
            self.points = pts
            self.warnings = []
    s = _S(points)
    msgs = check_crs(s)
    p0 = points[0] if points else None
    return [Check("error", "cs_name", m, p0.x if p0 else 0.0, p0.y if p0 else 0.0) for m in msgs]


def check_structures(structures):
    out = []
    for s in structures:
        p = s.point
        if p.point_type == "drain_outlet" and s.above_bed is not None and s.above_bed < 0:
            out.append(Check("warning", "drain_below_bed", "Drain %s lies %.2f m below the stream bed."
                             % (p.name, -s.above_bed), p.x, p.y, value=s.above_bed))
        if p.point_type == "drain_outlet" and s.below_water is not None and s.below_water > 0:
            out.append(Check("info", "drain_submerged", "Drain %s is %.2f m below the water level."
                             % (p.name, s.below_water), p.x, p.y, value=s.below_water))
    return out


def run_checks(points, profiles, section_points, extended, structures, settings=None):
    """All rules; errors first, then warnings, then notes, each in survey/station order."""
    st = settings or CheckSettings()
    found = (check_cs(points, st) + check_sections(profiles, section_points, st) + check_dhm(extended, st)
             + check_structures(structures or []) + check_gnss(points, st))
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(found, key=lambda c: order.get(c.severity, 3))


__all__ = ["Check", "CheckSettings", "StructureResult", "locate_structures", "run_checks", "interpolate",
           "save_settings", "load_settings", "settings_from_dict"]
