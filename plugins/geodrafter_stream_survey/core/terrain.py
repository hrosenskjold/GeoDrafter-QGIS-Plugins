# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Terrain extension of cross-sections with a terrain model (pure Python).

The surveyor measures from bank top to bank top (plus water level, structures
and drains). Each section is extended outwards on terrain from its outermost
measured bank top on each side, along the section line:

* **Only outside the measured points.** Inside the stream the terrain model is
  never used (the laser hits water and vegetation, not the bed).
* **Sampling** every 0.4 m (the cell size of Danmarks Højdemodel), bilinear,
  out to ``length`` (default 10 m, allowed 5–50 m) beyond the bank top.
* **Join at the bank top.** dz = measured bank top − terrain model there.
  |dz| ≤ ``tolerance`` (10 cm): the terrain samples are used directly.
  Larger: the terrain is shifted by dz at the bank top, tapering linearly to no
  shift over the ``transition`` zone (3 m), and the section is marked for
  review. |dz| > ``error_limit`` (50 cm): nothing is joined on that side and
  the section is an error (typically a wrong code, dense vegetation or a new
  ditch).
* **Thinning** to break points with a ``thin_tolerance`` of 2 cm
  (Douglas–Peucker on offset/elevation), so a section does not get 25 terrain
  points. The outer end point is always kept.
* **Source per point**: ``measured``, ``dhm`` or ``transition``, with the
  terrain model version.
* **Control points**: points coded ``terrain`` outside the bank top are not
  part of the joined section by default (``control_points="check"``); their
  difference to the terrain model is reported per section. With
  ``control_points="keep"`` they stay in the section and the extension starts
  beyond the outermost measured point on that side.
* **No bank top on a side** (the surveyor stopped part-way up the bank, or the
  code was missed): the extension starts at the outermost measured point on
  the bank (bank toe, break point, terrain or other – never bed, water level or
  structures), is joined by the same rules and the side is marked for review.
  With no such point the side is not extended.

The terrain model is passed in as a function ``terrain(x, y) -> z or None``, so
everything is testable without DHM; ``GridTerrain`` samples a raster grid
bilinearly (for local GeoTIFF blocks read by the plugin).
"""

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

SOURCE_MEASURED = "measured"
SOURCE_DHM = "dhm"
SOURCE_TRANSITION = "transition"

STATUS_OK = "ok"                # joined directly
STATUS_SHIFTED = "shifted"      # joined with a shifted transition – review
STATUS_ERROR = "error"          # difference over the error limit – not joined
STATUS_NO_BANK = "no_bank_top"  # no bank top and no bank point on that side – not extended
STATUS_FROM_OUTER = "from_outer_point"  # no bank top: extended from the outermost bank point – review
STATUS_NO_DATA = "no_data"      # terrain model has no value at the bank top
STATUS_OFF = "off"              # extension switched off
STATUS_REMOVED = "removed"      # terrain-model part removed by the user in the profile view


@dataclass
class ExtensionSettings:
    length: float = 10.0          # beyond the bank top [m]
    step: float = 0.4             # sampling distance [m]
    tolerance: float = 0.10       # direct join up to this |dz| [m]
    transition: float = 3.0       # transition zone [m]
    error_limit: float = 0.50     # no join above this |dz| [m]
    thin_tolerance: float = 0.02  # thinning tolerance [m]
    control_points: str = "check"  # "check" or "keep"
    dhm_version: str = ""         # e.g. "DHM/Terræn 0,4 m 2023"

    def validate(self):
        if not 5.0 <= self.length <= 50.0:
            raise ValueError("Extension length must be 5–50 m (got %g)" % self.length)
        if self.step <= 0 or self.step > self.length:
            raise ValueError("Sampling distance must be > 0 and ≤ the length")
        if not 0 <= self.tolerance <= self.error_limit:
            raise ValueError("Tolerance must be between 0 and the error limit")
        if self.transition < 0:
            raise ValueError("Transition zone cannot be negative")
        if self.control_points not in ("check", "keep"):
            raise ValueError("control_points must be 'check' or 'keep'")
        return self


@dataclass
class ExtPoint:
    offset: float
    z: Optional[float]
    x: float
    y: float
    source: str
    point_type: str = "terrain"
    point: object = None          # the SurveyPoint for measured points
    dhm_version: str = ""
    shift: float = 0.0            # applied terrain shift (transition points)

    @property
    def name(self):
        return getattr(self.point, "name", "")


@dataclass
class SideResult:
    side: str                     # "left" / "right"
    status: str
    dz: Optional[float] = None    # measured − terrain model at the join
    join_offset: Optional[float] = None
    samples: int = 0              # terrain samples before thinning
    kept: int = 0                 # after thinning
    message: str = ""


@dataclass
class ControlResult:
    point: object
    offset: float
    measured: float
    dhm: Optional[float]

    @property
    def deviation(self):
        return None if self.dhm is None else self.measured - self.dhm


@dataclass
class ExtendedProfile:
    profile: object
    points: List[ExtPoint] = field(default_factory=list)       # left → right
    sides: Dict[str, SideResult] = field(default_factory=dict)
    controls: List[ControlResult] = field(default_factory=list)
    dhm_version: str = ""
    raw_samples: Dict[str, List[ExtPoint]] = field(default_factory=dict)   # before thinning, per side

    @property
    def status(self):
        st = {s.status for s in self.sides.values()}
        if STATUS_ERROR in st or STATUS_NO_DATA in st:
            return "error"
        if STATUS_SHIFTED in st or STATUS_NO_BANK in st or STATUS_FROM_OUTER in st:
            return "review"
        return "ok"

    def control_deviation(self):
        """(mean, max abs) deviation measured − terrain model of the control points, or None."""
        d = [c.deviation for c in self.controls if c.deviation is not None]
        if not d:
            return None
        return sum(d) / len(d), max(abs(v) for v in d)


class GridTerrain:
    """Bilinear sampling of a north-up raster grid.

    origin_x/origin_y = the upper-left corner of the upper-left cell; values
    are rows from north to south; ``nodata`` cells give None.
    """

    def __init__(self, origin_x, origin_y, cell, values, nodata=None):
        self.ox, self.oy, self.cell = float(origin_x), float(origin_y), float(cell)
        self.values = values
        self.rows = len(values)
        self.cols = len(values[0]) if values else 0
        self.nodata = nodata

    def _v(self, r, c):
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return None
        v = self.values[r][c]
        if v is None or (self.nodata is not None and v == self.nodata):
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        return float(v)

    def __call__(self, x, y):
        # cell centres at ox + (c + .5) * cell and oy − (r + .5) * cell
        fc = (x - self.ox) / self.cell - 0.5
        fr = (self.oy - y) / self.cell - 0.5
        inside = -0.5 <= fc <= self.cols - 0.5 and -0.5 <= fr <= self.rows - 0.5
        if self.cols < 2 or self.rows < 2 or not inside:
            return None                                     # outside the grid
        c0 = min(max(int(math.floor(fc)), 0), self.cols - 2)
        r0 = min(max(int(math.floor(fr)), 0), self.rows - 2)
        tc = min(max(fc - c0, 0.0), 1.0)                    # half a cell at the edge: edge value
        tr = min(max(fr - r0, 0.0), 1.0)
        q = [self._v(r0, c0), self._v(r0, c0 + 1), self._v(r0 + 1, c0), self._v(r0 + 1, c0 + 1)]
        if any(v is None for v in q):
            return None
        top = q[0] * (1 - tc) + q[1] * tc
        bot = q[2] * (1 - tc) + q[3] * tc
        return top * (1 - tr) + bot * tr


def thin(points, tolerance):
    """Douglas–Peucker on (offset, z) with the vertical distance to the chord.

    ``points`` are (offset, z, payload) sorted by offset; returns the kept ones.
    """
    if len(points) <= 2:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        (o1, z1, _), (o2, z2, _) = points[i], points[j]
        best, bi = -1.0, None
        for k in range(i + 1, j):
            o, z, _ = points[k]
            t = 0.0 if o2 == o1 else (o - o1) / (o2 - o1)
            d = abs(z - (z1 + t * (z2 - z1)))
            if d > best:
                best, bi = d, k
        if bi is not None and best > tolerance:
            keep[bi] = True
            stack.append((i, bi))
            stack.append((bi, j))
    return [p for p, k in zip(points, keep) if k]


def _outermost(pps, side, types):
    cand = [pp for pp in pps if pp.point.point_type in types and pp.point.z is not None
            and (pp.offset < 0 if side == "left" else pp.offset > 0)]
    if not cand:
        return None
    return min(cand, key=lambda pp: pp.offset) if side == "left" else max(cand, key=lambda pp: pp.offset)


FALLBACK_TYPES = ("bank_toe", "knick", "terrain", "other")


def extend_profile(profile, terrain: Callable, settings: ExtensionSettings = None, sides=("left", "right")):
    """Extend one cross-section (``geometry.Profile``) with the terrain model."""
    st = (settings or ExtensionSettings()).validate()
    nx, ny = profile.normal
    result = ExtendedProfile(profile, dhm_version=st.dhm_version)

    # measured part and control points
    measured, controls = [], []
    banks = {s: _outermost(profile.points, s, ("bank_top",)) for s in ("left", "right")}
    for pp in profile.points:
        p = pp.point
        if p.point_type == "terrain" and st.control_points == "check":
            bank = banks["left" if pp.offset < 0 else "right"]
            if bank is not None and abs(pp.offset) > abs(bank.offset):
                dhm = terrain(p.x, p.y)
                if p.z is not None:
                    controls.append(ControlResult(p, pp.offset, p.z, dhm))
                continue
        measured.append(ExtPoint(pp.offset, p.z, p.x, p.y, SOURCE_MEASURED, p.point_type, p))
    result.controls = controls

    left_ext, right_ext = [], []
    for side in ("left", "right"):
        bank = banks[side]
        if side not in sides:
            result.sides[side] = SideResult(side, STATUS_OFF)
            continue
        from_outer = False
        if bank is None:
            bank = _outermost(profile.points, side, FALLBACK_TYPES)
            if bank is None:
                result.sides[side] = SideResult(side, STATUS_NO_BANK,
                                                message="No bank top on the %s side – not extended." % side)
                continue
            from_outer = True
        sign = -1.0 if side == "left" else 1.0
        start = bank
        if st.control_points == "keep":
            outer = [m for m in measured if (m.offset < 0) == (side == "left") and m.z is not None]
            if outer:
                far = (min if side == "left" else max)(outer, key=lambda m: m.offset)
                if abs(far.offset) > abs(bank.offset):
                    start = _PP(far)
        sx, sy, sz, soff = start.point.x, start.point.y, start.point.z, start.offset
        dhm0 = terrain(sx, sy)
        if dhm0 is None:
            msg = "The terrain model has no value at the %s bank top." % side
            result.sides[side] = SideResult(side, STATUS_NO_DATA, join_offset=soff, message=msg)
            continue
        dz = sz - dhm0
        if abs(dz) > st.error_limit:
            result.sides[side] = SideResult(
                side, STATUS_ERROR, dz, soff,
                message="%s bank top is %.2f m %s the terrain model (limit %.2f m) – not joined; "
                        "check the code, vegetation or a new ditch." % (
                            side.capitalize(), abs(dz), "above" if dz > 0 else "below", st.error_limit))
            continue
        shifted = abs(dz) > st.tolerance
        n = int(math.floor(st.length / st.step + 1e-9))
        dists = [k * st.step for k in range(1, n + 1)]
        if dists[-1] < st.length - 1e-9:
            dists.append(st.length)
        if shifted and 0 < st.transition < st.length and all(abs(d - st.transition) > 1e-9 for d in dists):
            dists = sorted(dists + [st.transition])        # a sample exactly at the end of the transition
        samples = []
        stopped = False
        for d in dists:
            x, y = sx + sign * d * nx, sy + sign * d * ny
            z = terrain(x, y)
            if z is None:
                stopped = True
                break
            shift = dz * max(0.0, 1.0 - d / st.transition) if shifted and st.transition > 0 else 0.0
            src = SOURCE_TRANSITION if shifted and d < st.transition - 1e-9 else SOURCE_DHM
            samples.append(ExtPoint(soff + sign * d, z + shift, x, y, src, "terrain",
                                    dhm_version=st.dhm_version, shift=shift))
        # thinning: the join point (measured) is the anchor; keep the transition end and the outer end
        chain = [(0.0, sz, None)] + [(abs(e.offset - soff), e.z, e) for e in samples]
        result.raw_samples[side] = samples
        kept = [c[2] for c in thin(chain, st.thin_tolerance) if c[2] is not None]
        if shifted:
            end_tr = [e for e in samples if abs(abs(e.offset - soff) - st.transition) < 1e-6]
            for e in end_tr[:1]:
                if e not in kept:
                    kept.append(e)
        kept.sort(key=lambda e: e.offset)
        msg = ""
        if from_outer:
            msg = "No bank top on the %s side – extended from the outermost point %s (%.2f m), review." % (
                side, bank.point.name or "?", abs(bank.offset))
        if shifted:
            shift_msg = "%s side: terrain model differs %.2f m at the join – shifted over %.1f m, review." % (
                side.capitalize(), dz, st.transition)
            msg = (msg + " " if msg else "") + shift_msg
        if stopped:
            msg = (msg + " " if msg else "") + "Terrain model ends after %.1f m on the %s side." % (
                (samples[-1].offset - soff) * sign if samples else 0.0, side)
        status = STATUS_FROM_OUTER if from_outer else (STATUS_SHIFTED if shifted else STATUS_OK)
        result.sides[side] = SideResult(side, status, dz, soff,
                                        len(samples), len(kept), msg)
        (left_ext if side == "left" else right_ext).extend(kept)
    result.points = sorted(left_ext + measured + right_ext, key=lambda e: e.offset)
    return result


class _PP:
    """Adapter so a measured ExtPoint can act as the start of the extension."""

    def __init__(self, e):
        self.point = e.point
        self.offset = e.offset


def extend_profiles(profiles, terrain, settings=None):
    st = (settings or ExtensionSettings()).validate()
    return [extend_profile(p, terrain, st) for p in profiles]


__all__ = ["ExtensionSettings", "ExtPoint", "SideResult", "ControlResult", "ExtendedProfile", "GridTerrain",
           "thin", "extend_profile", "extend_profiles", "SOURCE_MEASURED", "SOURCE_DHM", "SOURCE_TRANSITION"]
