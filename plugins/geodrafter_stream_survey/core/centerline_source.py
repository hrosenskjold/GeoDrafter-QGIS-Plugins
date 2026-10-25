# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Where the centre line comes from: a national watercourse line, the user's own line, or the points.

Pure Python. The plugin fetches watercourse features (INSPIRE Hydrography from
Dataforsyningen, see ``gui/inspire.py``) and hands them over as
``WatercourseFeature`` objects; here we

* pick the watercourse that fits the surveyed bed points best (smallest
  median distance), grouping segments by watercourse name/id,
* join its segments into one continuous line in order (also piped stretches,
  which are separate segments), bridging small gaps,
* cut it to the surveyed reach plus a margin,
* measure how far the bed points are from the line (median, max) and
* optionally fit the line through the surveyed bed points ("Fit line to the
  surveyed bed points"), keeping the rest of the line.

The direction downstream is set afterwards by ``geometry.orient_downstream``.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from .geometry import Centerline

Coord = Tuple[float, float]


@dataclass
class WatercourseFeature:
    coords: List[Coord]                     # one part (multi-part features are split)
    key: str = ""                           # watercourse identity (name or id)
    attrs: Dict[str, str] = field(default_factory=dict)


NAME_KEYS = ("name", "navn", "geographicalname", "text", "spelling", "watercourse", "vandloebsnavn")
ID_KEYS = ("localid", "inspireid", "id", "gml_id", "fid", "objectid")


def watercourse_key(attrs):
    """Identity of a watercourse from its attributes: a name when there is one, else an id."""
    low = {str(k).lower(): v for k, v in (attrs or {}).items()}
    for k in NAME_KEYS:
        v = low.get(k)
        if v not in (None, "", "NULL"):
            return "name:%s" % str(v).strip()
    for k in ID_KEYS:
        v = low.get(k)
        if v not in (None, "", "NULL"):
            return "id:%s" % str(v).strip()
    return ""


def features_from_geojson(fc, key_fn=watercourse_key):
    """WatercourseFeatures from a GeoJSON FeatureCollection (LineString/MultiLineString)."""
    out = []
    for i, f in enumerate(fc.get("features", [])):
        g = f.get("geometry") or {}
        attrs = dict(f.get("properties") or {})
        if "id" in f and "id" not in attrs:
            attrs["id"] = f["id"]
        parts = []
        if g.get("type") == "LineString":
            parts = [g.get("coordinates") or []]
        elif g.get("type") == "MultiLineString":
            parts = g.get("coordinates") or []
        key = key_fn(attrs) or "feature:%d" % i
        for part in parts:
            coords = [(float(c[0]), float(c[1])) for c in part]
            if len(coords) >= 2:
                out.append(WatercourseFeature(coords, key, attrs))
    return out


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def distance_to_lines(p, lines):
    best = float("inf")
    for coords in lines:
        for a, b in zip(coords, coords[1:]):
            d = _seg_dist(p, a, b)
            if d < best:
                best = d
    return best


def _median(v):
    v = sorted(v)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def pick_watercourse(features: Sequence[WatercourseFeature], bed_xy: Sequence[Coord]):
    """(key, [features], median distance) of the watercourse nearest the bed points."""
    groups: Dict[str, List[WatercourseFeature]] = {}
    for f in features:
        groups.setdefault(f.key, []).append(f)
    if not groups:
        return None, [], None
    best = None
    for key, feats in groups.items():
        lines = [f.coords for f in feats]
        med = _median([distance_to_lines(p, lines) for p in bed_xy]) if bed_xy else 0.0
        if best is None or med < best[2]:
            best = (key, feats, med)
    return best


def assemble(parts: Sequence[Sequence[Coord]], tolerance=1.0, max_gap=50.0, start_near=None):
    """Join line parts into one continuous line.

    Starts with the part nearest ``start_near`` (or the first) and repeatedly
    attaches the unused part whose end point is nearest either end of the chain,
    reversing it when needed. Ends closer than ``tolerance`` are merged; gaps up
    to ``max_gap`` are bridged with a straight segment (e.g. a missing piped
    stretch); parts further away are left out. Returns (coords, used, gaps).
    """
    parts = [list(p) for p in parts if len(p) >= 2]
    if not parts:
        return [], 0, []
    if start_near is not None:
        first = min(range(len(parts)), key=lambda i: distance_to_lines(start_near, [parts[i]]))
    else:
        first = 0
    chain = parts.pop(first)
    used, gaps = 1, []
    while parts:
        head, tail = chain[0], chain[-1]
        best = None
        for i, p in enumerate(parts):
            for at_tail, end_first in ((True, True), (True, False), (False, True), (False, False)):
                anchor = tail if at_tail else head
                end = p[0] if end_first else p[-1]
                d = math.hypot(anchor[0] - end[0], anchor[1] - end[1])
                if best is None or d < best[0]:
                    best = (d, i, at_tail, end_first)
        d, i, at_tail, end_first = best
        if d > max_gap:
            break
        p = parts.pop(i)
        if at_tail:
            seg = p if end_first else list(reversed(p))
            if d <= tolerance:
                seg = seg[1:]
            else:
                gaps.append(d)
            chain = chain + seg
        else:
            seg = list(reversed(p)) if end_first else p
            if d <= tolerance:
                seg = seg[:-1]
            else:
                gaps.append(d)
            chain = seg + chain
        used += 1
    return chain, used, gaps


def clip_to_points(coords, points_xy, margin=200.0):
    """The part of a line between the stations of the points, extended by ``margin``."""
    cl = Centerline(coords)
    st = [cl.locate(x, y, raw=True).station for x, y in points_xy]
    if not st:
        return list(coords)
    lo, hi = max(min(st) - margin, 0.0), min(max(st) + margin, cl.length)
    out = [cl.point_at(lo)]
    for c, s in zip(cl.coords, cl.cum):
        if lo < s < hi:
            out.append(c)
    out.append(cl.point_at(hi))
    return out


@dataclass
class LineFit:
    median: float
    maximum: float
    n: int


def bed_distance(centerline, bed_xy):
    """Median and largest distance from the bed points to the line."""
    d = [centerline.locate(x, y).distance for x, y in bed_xy]
    if not d:
        return None
    return LineFit(_median(d), max(d), len(d))


def fit_to_bed(centerline, section_bed_xy, margin=0.0):
    """The line moved through the sections' lowest bed points between the first and the last
    section, the rest kept. ``section_bed_xy``: one (x, y) per section."""
    if len(section_bed_xy) < 2:
        return centerline
    raw = sorted(((centerline.locate(x, y, raw=True).station, (x, y)) for x, y in section_bed_xy))
    s0, s1 = raw[0][0] - margin, raw[-1][0] + margin
    before = [c for c, s in zip(centerline.coords, centerline.cum) if s < s0]
    after = [c for c, s in zip(centerline.coords, centerline.cum) if s > s1]
    coords = before + [xy for _s, xy in raw] + after
    return Centerline(coords, centerline.station_shift, centerline.source + " (fitted to bed points)")


def watercourse_centerline(features, bed_xy, points_xy=None, margin=200.0, tolerance=1.0, max_gap=50.0):
    """Pick, join and clip a watercourse line for the survey. Returns (coords, info dict)."""
    key, feats, med = pick_watercourse(features, bed_xy)
    if not feats:
        return None, {"reason": "no watercourse features"}
    cx = sum(p[0] for p in bed_xy) / len(bed_xy) if bed_xy else feats[0].coords[0][0]
    cy = sum(p[1] for p in bed_xy) / len(bed_xy) if bed_xy else feats[0].coords[0][1]
    coords, used, gaps = assemble([f.coords for f in feats], tolerance, max_gap, start_near=(cx, cy))
    coords = clip_to_points(coords, points_xy or bed_xy, margin) if (points_xy or bed_xy) else coords
    return coords, {"key": key, "median": med, "parts": len(feats), "used": used, "gaps": gaps}
