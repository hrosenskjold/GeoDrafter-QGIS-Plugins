# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Stream geometry: centre line, stationing and cross-sections (pure Python).

Conventions (as in the municipal specifications):

* The centre line runs **downstream**; station grows downstream, in metres,
  with station 0 (or any value) bound to a chosen fixed point.
* Offsets are signed across the stream: **right is positive, left negative,
  looking downstream**.
* A cross-section line is perpendicular to the centre line at the section's
  station. The centre line direction there is the chord from ``station − w`` to
  ``station + w`` (``w`` = ``tangent_window``, default 5 m), so a section in a
  bend gets the bisector direction instead of jumping between two segments.

Each surveyed point of a section gets the section's station, its signed offset
along the section line and its distance from the section line (positive
downstream), which the data check uses for "point far from the section line".
"""

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from .model import SurveyPoint

DEFAULT_TANGENT_WINDOW = 5.0
DEFAULT_NAME_PATTERN = r"^(?P<profile>.*?\d+)[-_./ ](?P<point>\d+)$"   # P12-03, 12.3, P7_10
DEFAULT_DESCRIPTION_PATTERN = r"(?i)\b(?:p|profil|profile|tv)\s*\.?\s*(?P<profile>\d+)\b"
DEFAULT_PROFILE_ATTRIBUTES = ("Profil", "Profile")
SECTION_TYPES = ("bed", "bank_top", "bank_toe", "water_level", "terrain", "knick")


def _attr_profile(p, names):
    for n in names:
        v = p.attribute(n) if n else ""
        if v:
            try:
                f = float(v.replace(",", "."))
                return str(int(f)) if f == int(f) else v
            except ValueError:
                return v
    return ""


CENTER_TOL = 0.005


class GeometryError(ValueError):
    pass


def _dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


@dataclass
class Location:
    station: float        # including the station binding
    offset: float         # signed, right of downstream positive
    x: float              # foot point on the centre line
    y: float
    segment: int
    distance: float       # absolute distance to the centre line


class Centerline:
    """A polyline in survey coordinates, oriented downstream."""

    def __init__(self, coords: Sequence[Tuple[float, float]], station_shift=0.0, source=""):
        pts = []
        for c in coords:
            c = (float(c[0]), float(c[1]))
            if not pts or _dist(pts[-1], c) > 1e-9:
                pts.append(c)
        if len(pts) < 2:
            raise GeometryError("A centre line needs at least two distinct vertices")
        self.coords = pts
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + _dist(a, b))
        self.station_shift = float(station_shift)
        self.source = source

    # -- basic --------------------------------------------------------------------
    @property
    def length(self):
        return self.cum[-1]

    def reversed(self):
        return Centerline(list(reversed(self.coords)), self.station_shift, self.source)

    def bind_station(self, x, y, station=0.0):
        """Set the stationing so the point on the line nearest (x, y) has ``station``."""
        loc = self.locate(x, y, raw=True)
        self.station_shift = float(station) - loc.station
        return self

    def raw(self, station):
        return station - self.station_shift

    def point_at(self, station):
        """(x, y) at a station (clamped to the line)."""
        s = min(max(self.raw(station), 0.0), self.length)
        i = self._segment_at(s)
        a, b = self.coords[i], self.coords[i + 1]
        seg = self.cum[i + 1] - self.cum[i]
        t = 0.0 if seg == 0 else (s - self.cum[i]) / seg
        return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

    def _segment_at(self, s):
        for i in range(len(self.coords) - 1):
            if s <= self.cum[i + 1]:
                return i
        return len(self.coords) - 2

    def tangent_at(self, station, window=DEFAULT_TANGENT_WINDOW):
        """Unit downstream direction at a station (chord over ±window)."""
        s = self.raw(station)
        if window and window > 0:
            lo, hi = max(s - window, 0.0), min(s + window, self.length)
            a, b = self.point_at(lo + self.station_shift), self.point_at(hi + self.station_shift)
            d = _dist(a, b)
            if d > 1e-9:
                return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)
        i = self._segment_at(min(max(s, 0.0), self.length))
        a, b = self.coords[i], self.coords[i + 1]
        d = _dist(a, b)
        return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)

    @staticmethod
    def right_normal(tangent):
        """Unit vector to the right of a downstream direction."""
        return (tangent[1], -tangent[0])

    def locate(self, x, y, raw=False):
        """Nearest point on the line: station, signed offset (right +), foot point."""
        best = None
        for i, (a, b) in enumerate(zip(self.coords, self.coords[1:])):
            dx, dy = b[0] - a[0], b[1] - a[1]
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / seg2))
            fx, fy = a[0] + t * dx, a[1] + t * dy
            d = math.hypot(x - fx, y - fy)
            if best is None or d < best[0] - 1e-12:
                seg = math.sqrt(seg2)
                # side from the segment's own direction (right = negative cross product)
                cross = dx * (y - a[1]) - dy * (x - a[0])
                best = (d, i, fx, fy, self.cum[i] + t * seg, -math.copysign(d, cross) if d > 0 else 0.0)
        d, i, fx, fy, s, off = best
        return Location(s + (0.0 if raw else self.station_shift), off, fx, fy, i, d)

    def intersect(self, p, direction):
        """Raw stations where the infinite line through p with ``direction`` crosses the centre line."""
        out = []
        ux, uy = direction
        for i, (a, b) in enumerate(zip(self.coords, self.coords[1:])):
            vx, vy = b[0] - a[0], b[1] - a[1]
            den = ux * vy - uy * vx
            if abs(den) < 1e-12:
                continue
            wx, wy = a[0] - p[0], a[1] - p[1]
            t_seg = (wx * uy - wy * ux) / den      # along segment, 0..1
            if -1e-9 <= t_seg <= 1 + 1e-9:
                s = self.cum[i] + max(0.0, min(1.0, t_seg)) * math.hypot(vx, vy)
                if not out or abs(out[-1] - s) > 1e-6:
                    out.append(s)
        return out


# -- orientation and building -------------------------------------------------------

def _bed_like(p):
    return p.point_type in ("bed", "knick") and p.z is not None


def bed_trend(centerline, points):
    """Least-squares fall of bed elevations per metre of station (positive = falls downstream)."""
    data = [(centerline.locate(p.x, p.y, raw=True).station, p.z) for p in points if _bed_like(p)]
    if len(data) < 2:
        return None
    n = len(data)
    ms = sum(d[0] for d in data) / n
    mz = sum(d[1] for d in data) / n
    sxx = sum((d[0] - ms) ** 2 for d in data)
    if sxx < 1e-9:
        return None
    return -sum((d[0] - ms) * (d[1] - mz) for d in data) / sxx


def orient_downstream(centerline, points=None, upstream_point=None):
    """The centre line pointing downstream.

    ``upstream_point`` (x, y) wins when given: the line's end nearest it is the
    start. Otherwise the bed (and knick) elevations decide: the bed must fall
    along the line. Returns (centerline, reason).
    """
    if upstream_point is not None:
        a, b = centerline.coords[0], centerline.coords[-1]
        if _dist(upstream_point, b) < _dist(upstream_point, a):
            return centerline.reversed(), "reversed: upstream point is nearer the end"
        return centerline, "kept: upstream point is nearer the start"
    fall = bed_trend(centerline, points or [])
    if fall is None:
        return centerline, "kept: too few bed points to tell the flow direction"
    if fall < 0:
        return centerline.reversed(), "reversed: bed rises along the line (%.2f ‰)" % (-fall * 1000)
    return centerline, "kept: bed falls along the line (%.2f ‰)" % (fall * 1000)


def centerline_from_points(groups, ungrouped=()):
    """Build a centre line from the surveyed sections.

    One vertex per section in survey order: the lowest bed point, else the lowest
    knick point, else the middle between the outermost bank tops. With no
    sections, the bed/knick points in survey order are used.
    """
    verts = []
    for pts in groups.values():
        v = _section_vertex(pts)
        if v is not None:
            verts.append((min(p.seq for p in pts), v))
    verts.sort()
    coords = [v for _s, v in verts]
    if len(coords) < 2:
        coords = [(p.x, p.y) for p in sorted(list(ungrouped) + [q for g in groups.values() for q in g],
                                             key=lambda p: p.seq) if _bed_like(p)]
    return Centerline(coords, source="surveyed sections")


def _section_vertex(pts):
    for kind in ("bed", "knick"):
        cand = [p for p in pts if p.point_type == kind and p.z is not None]
        if cand:
            p = min(cand, key=lambda q: (q.z, q.seq))
            return (p.x, p.y)
    banks = [p for p in pts if p.point_type == "bank_top"]
    if len(banks) >= 2:
        a, b = max(((p, q) for p in banks for q in banks), key=lambda pq: _dist((pq[0].x, pq[0].y),
                                                                                (pq[1].x, pq[1].y)))
        return ((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)
    return None


# -- grouping into cross-sections -------------------------------------------------------

def group_profiles(points: List[SurveyPoint], method="auto", pattern=None, max_gap=15.0, min_points=3,
                   attributes=DEFAULT_PROFILE_ATTRIBUTES):
    """Group points into cross-sections.

    method:
      "attribute"   – section number from a code attribute of the export (``attributes``,
                      default "Profil"/"Profile", as in the Emlid code library)
      "name"        – section id from the point name (default pattern: "P12-03" → "P12")
      "description" – section id from the description ("P12", "Profil 12" → "12")
      "markers"     – by start/end codes (VASP: a section runs from its start point to its
                      end point; points outside belong to no section)
      "auto"        – "attribute" when most section points carry it, else "markers" when the
                      survey has start and end codes, else "name" when
                      most names match, else by survey order: a new
                      section starts where the jump to the next point exceeds
                      ``max_gap`` metres.
    Points of types that are never part of a section on their own (structures,
    drains) stay in a section when they belong to it by name. Groups with fewer
    than ``min_points`` points are returned as ungrouped.
    Returns (groups {id: [points in survey order]}, ungrouped [points]).
    """
    pts = sorted(points, key=lambda p: p.seq)
    attributes = [a for a in (attributes or ()) if a]
    if method == "auto":
        section_pts = [p for p in pts if p.point_type in SECTION_TYPES] or pts
        with_attr = sum(1 for p in section_pts if _attr_profile(p, attributes))
        rx = re.compile(pattern or DEFAULT_NAME_PATTERN)
        matched = sum(1 for p in pts if rx.match(p.name or ""))
        starts = sum(1 for p in pts if getattr(p, "section_role", "") == "section_start")
        ends = sum(1 for p in pts if getattr(p, "section_role", "") == "section_end")
        if attributes and section_pts and with_attr >= 0.6 * len(section_pts):
            method = "attribute"
        elif starts >= 1 and ends >= 1:
            method = "markers"
        else:
            method = "name" if pts and matched >= 0.6 * len(pts) else "order"
    groups: Dict[str, List[SurveyPoint]] = {}
    ungrouped: List[SurveyPoint] = []
    if method == "attribute":
        for p in pts:
            v = _attr_profile(p, attributes)
            if v:
                groups.setdefault(v, []).append(p)
            else:
                ungrouped.append(p)
    elif method in ("name", "description"):
        default = DEFAULT_NAME_PATTERN if method == "name" else DEFAULT_DESCRIPTION_PATTERN
        rx = re.compile(pattern or default)
        for p in pts:
            m = rx.match(p.name or "") if method == "name" else rx.search(p.description or "")
            if m:
                groups.setdefault(m.group("profile"), []).append(p)
            else:
                ungrouped.append(p)
    elif method == "markers":
        current = None
        n = 0
        for p in pts:
            role = getattr(p, "section_role", "")
            if role == "section_start":
                if current:
                    groups["%d" % n] = current
                n += 1
                current = [p]
            elif current is not None:
                current.append(p)
                if role == "section_end":
                    groups["%d" % n] = current
                    current = None
            else:
                ungrouped.append(p)
        if current:
            groups["%d" % n] = current
    elif method == "order":
        current: List[SurveyPoint] = []
        n = 0
        for p in pts:
            if current and _dist((current[-1].x, current[-1].y), (p.x, p.y)) > max_gap:
                n += 1
                groups["%d" % n] = current
                current = []
            current.append(p)
        if current:
            groups["%d" % (n + 1)] = current
    else:
        raise ValueError("Unknown grouping method '%s'" % method)
    for k in [k for k, v in groups.items() if len(v) < min_points]:
        ungrouped.extend(groups.pop(k))
    ungrouped.sort(key=lambda p: p.seq)
    if method in ("order", "markers"):   # renumber 1..n after dropping small groups
        groups = {"%d" % (i + 1): v for i, v in enumerate(groups.values())}
    return groups, ungrouped


# -- cross-sections ---------------------------------------------------------------------

@dataclass
class ProfilePoint:
    point: SurveyPoint
    station: float         # the section's station
    offset: float          # along the section line, right of downstream positive
    along: float           # distance from the section line, positive downstream
    side: str              # "left", "right" or "center"

    @property
    def z(self):
        return self.point.z


@dataclass
class Profile:
    id: str
    station: float
    x: float                       # where the section line crosses the centre line
    y: float
    tangent: Tuple[float, float]   # downstream direction there
    points: List[ProfilePoint] = field(default_factory=list)   # sorted left → right
    note: str = ""

    @property
    def normal(self):
        return Centerline.right_normal(self.tangent)

    def line(self, extra=0.0):
        """Section line end points (left, right) covering the points plus ``extra`` metres."""
        if self.points:
            lo, hi = self.points[0].offset - extra, self.points[-1].offset + extra
        else:
            lo, hi = -extra, extra
        nx, ny = self.normal
        return ((self.x + lo * nx, self.y + lo * ny), (self.x + hi * nx, self.y + hi * ny))

    def max_along(self):
        return max((abs(pp.along) for pp in self.points), default=0.0)


def _principal_axis(pts):
    n = len(pts)
    mx = sum(p.x for p in pts) / n
    my = sum(p.y for p in pts) / n
    sxx = sum((p.x - mx) ** 2 for p in pts)
    syy = sum((p.y - my) ** 2 for p in pts)
    sxy = sum((p.x - mx) * (p.y - my) for p in pts)
    if sxx + syy < 1e-12:
        return (mx, my), None
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    return (mx, my), (math.cos(ang), math.sin(ang))


def section_station(centerline, pts):
    """Raw station where a section crosses the centre line.

    The points' best-fit line is intersected with the centre line (the crossing
    nearest the points' centre); with no crossing, the centre is projected.
    """
    c, axis = _principal_axis(pts)
    if axis is not None and len(pts) >= 2:
        hits = centerline.intersect(c, axis)
        if hits:
            ref = centerline.locate(c[0], c[1], raw=True).station
            return min(hits, key=lambda s: abs(s - ref)), "crossing"
    return centerline.locate(c[0], c[1], raw=True).station, "projected"


def build_profile(centerline, pid, pts, tangent_window=DEFAULT_TANGENT_WINDOW, station=None):
    """One cross-section from its points. ``station`` (with binding) overrides the computed one."""
    if station is None:
        raw, how = section_station(centerline, pts)
        station = raw + centerline.station_shift
    else:
        how = "given"
    cx, cy = centerline.point_at(station)
    t = centerline.tangent_at(station, tangent_window)
    nx, ny = Centerline.right_normal(t)
    out = []
    for p in pts:
        dx, dy = p.x - cx, p.y - cy
        off = dx * nx + dy * ny
        along = dx * t[0] + dy * t[1]
        side = "center" if abs(off) <= CENTER_TOL else ("right" if off > 0 else "left")
        out.append(ProfilePoint(p, station, off, along, side))
    out.sort(key=lambda pp: (pp.offset, pp.point.seq))
    return Profile(str(pid), station, cx, cy, t, out, note=how)


def build_profiles(centerline, groups, tangent_window=DEFAULT_TANGENT_WINDOW):
    """All sections, sorted by station (downstream)."""
    profs = [build_profile(centerline, pid, pts, tangent_window) for pid, pts in groups.items() if pts]
    profs.sort(key=lambda pr: pr.station)
    return profs


@dataclass
class LocatedPoint:
    point: SurveyPoint
    station: float
    offset: float
    distance: float


def locate_points(centerline, points):
    """Station and signed offset of single points (structures, drains …)."""
    out = []
    for p in points:
        loc = centerline.locate(p.x, p.y)
        out.append(LocatedPoint(p, loc.station, loc.offset, loc.distance))
    return out


def profile_spacing(profiles):
    """[(from id, to id, distance in station)] between consecutive sections."""
    return [(a.id, b.id, b.station - a.station) for a, b in zip(profiles, profiles[1:])]


def survey_geometry(points, centerline_coords=None, grouping="auto", pattern=None, max_gap=15.0,
                    min_points=3, upstream_point=None, station_point=None, station_value=0.0,
                    tangent_window=DEFAULT_TANGENT_WINDOW, attributes=DEFAULT_PROFILE_ATTRIBUTES):
    """Whole step 2–3 in one call; returns a dict with centerline, profiles, located points, notes.

    centerline_coords: an existing centre line (GeoDanmark, regulation line) or None to build it.
    station_point: (x, y) the station binding refers to; default the start of the line.
    """
    groups, ungrouped = group_profiles(points, grouping, pattern, max_gap, min_points, attributes)
    notes = []
    if centerline_coords is not None:
        cl = Centerline(centerline_coords, source="given line")
    else:
        cl = centerline_from_points(groups, ungrouped)
    cl, why = orient_downstream(cl, points, upstream_point)
    notes.append("Flow direction " + why)
    if station_point is not None:
        cl.bind_station(station_point[0], station_point[1], station_value)
    else:
        cl.station_shift = float(station_value)
    profiles = build_profiles(cl, groups, tangent_window)
    return {"centerline": cl, "profiles": profiles, "groups": groups,
            "located": locate_points(cl, ungrouped), "notes": notes}


__all__ = ["Centerline", "Location", "Profile", "ProfilePoint", "LocatedPoint", "GeometryError",
           "group_profiles", "build_profile", "build_profiles", "centerline_from_points",
           "orient_downstream", "bed_trend", "locate_points", "profile_spacing", "survey_geometry",
           "section_station"]
