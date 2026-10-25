# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Block 7: centre line, stationing and cross-sections, against hand-calculated values."""

import math
import os

import pytest

from geodrafter_stream_survey.core import codes
from geodrafter_stream_survey.core.geometry import (
    Centerline, GeometryError, build_profile, centerline_from_points, group_profiles, orient_downstream,
    profile_spacing, survey_geometry)
from geodrafter_stream_survey.core.model import SurveyPoint
from geodrafter_stream_survey.core.readers import read_survey

HERE = os.path.dirname(os.path.abspath(__file__))
EMLID = os.path.join(HERE, "data", "emlid_flow_SYNTHETIC.csv")
S2 = math.sqrt(2.0)


def P(seq, name, x, y, z=None, t="other", desc=""):
    return SurveyPoint(seq=seq, name=name, x=x, y=y, z=z, point_type=t, description=desc)


# --- centre line ----------------------------------------------------------------

def test_straight_line_locate_and_sides():
    cl = Centerline([(0, 0), (100, 0)])          # flows east; right = south
    loc = cl.locate(30, 4)
    assert (loc.station, loc.offset, loc.x, loc.y) == pytest.approx((30, -4, 30, 0))
    assert cl.locate(30, -2.5).offset == pytest.approx(2.5)
    assert cl.locate(-10, 0).station == pytest.approx(0)          # clamped before the start
    assert cl.length == 100 and cl.point_at(25) == pytest.approx((25, 0))
    assert Centerline.right_normal(cl.tangent_at(50)) == pytest.approx((0, -1))
    with pytest.raises(GeometryError):
        Centerline([(1, 1), (1, 1)])


def test_station_binding():
    cl = Centerline([(0, 0), (100, 0)])
    cl.bind_station(20, 7, 0.0)                  # station 0 at the fixed point x = 20
    assert cl.locate(50, 1).station == pytest.approx(30)
    assert cl.locate(10, 0).station == pytest.approx(-10)
    assert cl.point_at(30) == pytest.approx((50, 0))
    cl.bind_station(0, 0, 1000.0)                # or e.g. station 1000 at the start
    assert cl.locate(50, 0).station == pytest.approx(1050)


def test_knee_tangent_is_bisector_at_vertex():
    # east 100 m, then south 100 m: a right-hand bend at (100, 0)
    cl = Centerline([(0, 0), (100, 0), (100, -100)])
    assert cl.tangent_at(100) == pytest.approx((1 / S2, -1 / S2))
    # 2 m before the vertex: chord from s=93 (93, 0) to s=103 (100, -3) → (7, -3)/√58
    assert cl.tangent_at(98) == pytest.approx((7 / math.sqrt(58), -3 / math.sqrt(58)))
    # far from the bend: segment direction
    assert cl.tangent_at(50) == pytest.approx((1, 0)) and cl.tangent_at(150) == pytest.approx((0, -1))
    # without window: plain segment direction
    assert cl.tangent_at(98, window=0) == pytest.approx((1, 0))


def test_profile_in_knee_hand_calculated():
    cl = Centerline([(0, 0), (100, 0), (100, -100)])
    # section through the vertex along the bisector normal (−1, −1)/√2 (right = inside of the bend)
    pts = [P(0, "L", 103, 3, 11.0, "bank_top"), P(1, "B", 100, 0, 10.0, "bed"),
           P(2, "R", 98, -2, 11.2, "bank_top"), P(3, "OFF", 101, 1.2, 10.8, "bank_toe")]
    # the three points on the bisector alone put the section exactly at the vertex …
    assert build_profile(cl, "K", pts[:3]).station == pytest.approx(100)
    # … the point off the line tilts the best-fit line slightly, so give the station here
    pr = build_profile(cl, "K", pts, station=100.0)
    assert (pr.x, pr.y) == pytest.approx((100, 0))
    by = {pp.point.name: pp for pp in pr.points}
    assert by["L"].offset == pytest.approx(-3 * S2) and by["L"].side == "left"
    assert by["R"].offset == pytest.approx(2 * S2) and by["R"].side == "right"
    assert by["B"].offset == pytest.approx(0) and by["B"].side == "center"
    # OFF is 0.2 m off the section line: along = (1, 1.2)·(1, −1)/√2 = −0.2/√2 (upstream)
    assert by["OFF"].along == pytest.approx(-0.2 / S2)
    assert by["OFF"].offset == pytest.approx(-2.2 / S2)
    assert [pp.point.name for pp in pr.points] == ["L", "OFF", "B", "R"]      # left → right
    assert all(pp.station == pr.station for pp in pr.points)
    a, b = pr.line()
    assert a == pytest.approx((103, 3)) and b == pytest.approx((98, -2))


def test_profile_station_from_crossing_not_projection():
    cl = Centerline([(0, 0), (100, 0)])
    # a slightly skewed section: (40, 5) … (42, −5) crosses the line at x = 41
    pts = [P(0, "a", 40, 5, 11), P(1, "b", 41, 0, 10, "bed"), P(2, "c", 42, -5, 11)]
    pr = build_profile(cl, "1", pts)
    assert pr.station == pytest.approx(41) and pr.note == "crossing"
    by = {pp.point.name: pp for pp in pr.points}
    assert by["a"].offset == pytest.approx(-5) and by["a"].along == pytest.approx(-1)
    assert by["c"].offset == pytest.approx(5) and by["c"].along == pytest.approx(1)
    assert pr.max_along() == pytest.approx(1)


# --- orientation -------------------------------------------------------------------

def test_orient_downstream_by_bed_and_by_point():
    cl = Centerline([(0, 0), (100, 0)])
    rising = [P(0, "1", 0, 0, 10.0, "bed"), P(1, "2", 50, 0, 10.1, "bed"), P(2, "3", 100, 0, 10.2, "bed")]
    out, why = orient_downstream(cl, rising)
    assert out.coords[0] == (100, 0) and why.startswith("reversed")
    falling = [P(0, "1", 0, 0, 10.2, "bed"), P(1, "2", 100, 0, 10.0, "bed")]
    out, why = orient_downstream(cl, falling)
    assert out.coords[0] == (0, 0) and why.startswith("kept")
    out, _ = orient_downstream(cl, rising, upstream_point=(-5, 3))
    assert out.coords[0] == (0, 0)                # the user's upstream point wins
    out, why = orient_downstream(cl, [])
    assert out is cl and "too few" in why


# --- grouping ------------------------------------------------------------------------

def test_group_by_name():
    names = ["P1-1", "P1-2", "P1-3", "RB1", "P2-1", "P2-2", "P2-3", "P12.4", "P12.5", "P12.6"]
    pts = [P(i, n, i, 0) for i, n in enumerate(names)]
    g, u = group_profiles(pts, "name")
    assert list(g) == ["P1", "P2", "P12"] and [p.name for p in u] == ["RB1"]
    assert [p.name for p in g["P2"]] == ["P2-1", "P2-2", "P2-3"]
    g2, _ = group_profiles(pts, "auto")
    assert list(g2) == list(g)


def test_group_by_description():
    pts = [P(i, str(i), i, 0, desc=d) for i, d in enumerate(
        ["Profil 4 kk", "profil 4", "P4 bund", "bro", "P5", "P 5", "p5 vs"])]
    g, u = group_profiles(pts, "description")
    assert {k: [p.seq for p in v] for k, v in g.items()} == {"4": [0, 1, 2], "5": [4, 5, 6]}
    assert [p.seq for p in u] == [3]


def test_group_by_order_and_gap():
    xs = [0, 1, 2, 3, 4, 60, 61, 62, 63, 90, 150, 151, 152]
    pts = [P(i, str(i + 1), 0, x) for i, x in enumerate(xs)]
    g, u = group_profiles(pts, "auto", max_gap=15)          # numeric names → order
    assert {k: [p.name for p in v] for k, v in g.items()} == {
        "1": ["1", "2", "3", "4", "5"], "2": ["6", "7", "8", "9"], "3": ["11", "12", "13"]}
    assert [p.name for p in u] == ["10"]                    # a lone point (e.g. a drain)


# --- synthetic Emlid survey end to end -------------------------------------------------

def test_synthetic_emlid_survey_geometry():
    s = read_survey(EMLID, code_table=codes.standard_table())
    first = s.points[0]
    geo = survey_geometry(s.points)
    profs = geo["profiles"]
    assert [p.id for p in profs] == ["P01", "P02"]
    # built from the lowest bed points; the file runs downstream (azimuth 120°), so kept
    assert geo["notes"][0].startswith("Flow direction kept")
    assert profs[1].station - profs[0].station == pytest.approx(100, abs=0.05)
    assert profile_spacing(profs)[0][2] == pytest.approx(100, abs=0.05)
    p1 = {pp.point.name: pp for pp in profs[0].points}
    # the synthetic sections are perpendicular to the stream with known offsets (bed at −0.4 lowest)
    assert p1["P01-01"].offset - p1["P01-05"].offset == pytest.approx(-5.6, abs=1e-3)
    assert p1["P01-09"].offset - p1["P01-05"].offset == pytest.approx(2.9, abs=1e-3)
    assert p1["P01-01"].side == "left" and p1["P01-09"].side == "right"
    assert max(abs(pp.along) for pp in profs[0].points) < 2e-3      # mm rounding in the file
    # structures located on station
    loc = {lp.point.name: lp for lp in geo["located"]}
    assert loc["RB1"].station - profs[0].station == pytest.approx(55, abs=0.05)
    assert loc["DR1"].offset == pytest.approx(2.3 + 0.4, abs=0.01)     # right bank, from bed line
    # station 0 bound to the first (terrain) point projected on the line
    geo2 = survey_geometry(s.points, station_point=(first.x, first.y), station_value=0.0)
    assert geo2["profiles"][0].station == pytest.approx(0, abs=0.01)


def test_given_centerline_reversed_by_bed():
    s = read_survey(EMLID, code_table=codes.standard_table())
    built = centerline_from_points(group_profiles(s.points)[0])
    upstream_first = list(reversed(built.coords))           # digitised the wrong way
    geo = survey_geometry(s.points, centerline_coords=upstream_first)
    assert geo["notes"][0].startswith("Flow direction reversed")
    assert geo["centerline"].coords[0] == pytest.approx(built.coords[0])
