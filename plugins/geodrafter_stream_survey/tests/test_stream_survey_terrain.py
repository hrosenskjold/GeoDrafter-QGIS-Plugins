# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Block 8: terrain extension with synthetic terrain functions (no DHM, no network)."""

import os

import pytest

from geodrafter_stream_survey.core import codes
from geodrafter_stream_survey.core.geometry import Centerline, build_profile, survey_geometry
from geodrafter_stream_survey.core.model import SurveyPoint
from geodrafter_stream_survey.core.readers import read_survey
from geodrafter_stream_survey.core.terrain import (
    ExtensionSettings, GridTerrain, extend_profile, extend_profiles, thin)

HERE = os.path.dirname(os.path.abspath(__file__))
EMLID = os.path.join(HERE, "data", "emlid_flow_SYNTHETIC.csv")


def P(seq, name, x, y, z, t):
    return SurveyPoint(seq=seq, name=name, x=x, y=y, z=z, point_type=t)


@pytest.fixture
def profile():
    # stream flows east along y = 0: left bank north (y > 0), right bank south
    cl = Centerline([(0, 0), (200, 0)])
    pts = [P(0, "T1", 50, 6, 11.15, "terrain"), P(1, "KKV", 50, 3, 11.0, "bank_top"),
           P(2, "VS1", 50, 1, 10.4, "water_level"), P(3, "B1", 50, 0, 10.0, "bed"),
           P(4, "VS2", 50, -1, 10.41, "water_level"), P(5, "KKH", 50, -3, 11.2, "bank_top")]
    return build_profile(cl, "P1", pts)


def sloping(x, y):
    """Bank-top heights at |y| = 3, rising 5 cm per metre outwards (a plane on each side)."""
    return (11.0 if y > 0 else 11.2) + 0.05 * (abs(y) - 3)


def test_direct_join_and_thinning(profile):
    ext = extend_profile(profile, sloping, ExtensionSettings(dhm_version="DHM test"))
    left, right = ext.sides["left"], ext.sides["right"]
    assert (left.status, right.status) == ("ok", "ok") and ext.status == "ok"
    assert left.dz == pytest.approx(0) and left.samples == 25 and left.kept == 1   # a plane → only the end
    offs = [round(e.offset, 3) for e in ext.points]
    assert offs == [-13.0, -3.0, -1.0, 0.0, 1.0, 3.0, 13.0]     # T1 is a control point, not in the section
    end = ext.points[0]
    assert (end.source, end.z, end.dhm_version) == ("dhm", pytest.approx(11.5), "DHM test")
    assert (end.x, end.y) == pytest.approx((50, 13))
    assert [e.source for e in ext.points[1:-1]] == ["measured"] * 5
    # control point: measured 11.15, model 11.0 + 0.05·3 = 11.15
    assert ext.controls[0].point.name == "T1" and ext.controls[0].deviation == pytest.approx(0)
    assert ext.control_deviation() == pytest.approx((0, 0))


def test_no_dhm_inside_the_measured_points(profile):
    ext = extend_profile(profile, sloping)
    kk_l, kk_r = -3.0, 3.0
    assert all(e.source == "measured" for e in ext.points if kk_l <= e.offset <= kk_r)


def test_break_points_kept_by_thinning(profile):
    def ditch(x, y):          # a 30 cm deep ditch 6–7 m beyond the left bank top
        base = sloping(x, y)
        return base - 0.3 if y > 0 and 9 <= y <= 10 else base
    ext = extend_profile(profile, ditch, ExtensionSettings(thin_tolerance=0.02))
    left = sorted([e for e in ext.points if e.source == "dhm" and e.offset < 0], key=lambda e: -e.offset)
    ds = [round(-e.offset - 3, 1) for e in left]
    assert ds == [5.6, 6.0, 6.8, 7.2, 10.0]   # the ditch edges and the outer end
    assert ext.sides["left"].kept == 5


def test_shifted_transition(profile):
    lower = lambda x, y: sloping(x, y) - 0.25 if y > 0 else sloping(x, y)  # noqa: E731
    ext = extend_profile(profile, lower, ExtensionSettings(transition=3.0))
    left = ext.sides["left"]
    assert left.status == "shifted" and left.dz == pytest.approx(0.25) and ext.status == "review"
    assert "review" in left.message
    pts = {round(-e.offset - 3, 2): e for e in ext.raw_samples["left"]}
    # d = 0.4: model 11.02 − 0.25 = 10.77, shift 0.25·(1 − 0.4/3) = 0.21667
    assert pts[0.4].source == "transition" and pts[0.4].z == pytest.approx(10.77 + 0.25 * (1 - 0.4 / 3))
    assert pts[0.4].shift == pytest.approx(0.25 * (1 - 0.4 / 3))
    # d = 3.0 (the end of the transition is always sampled): no shift, terrain model
    assert pts[3.0].source == "dhm" and pts[3.0].z == pytest.approx(11.15 - 0.25) and pts[3.0].shift == 0
    assert pts[10.0].z == pytest.approx(11.5 - 0.25)
    # the join is continuous: the shifted model meets the measured bank top
    assert 11.0 - pts[0.4].z == pytest.approx(0.25 * 0.4 / 3 - 0.02, abs=1e-9)
    assert ext.sides["right"].status == "ok"
    # thinned: model and taper are both linear here, so only the transition end and the outer end remain
    assert [round(-e.offset - 3, 2) for e in ext.points if e.offset < -3] == [10.0, 3.0]


def test_error_limit_no_join(profile):
    high = lambda x, y: sloping(x, y) + 0.6 if y < 0 else sloping(x, y)  # noqa: E731
    ext = extend_profile(profile, high)
    right = ext.sides["right"]
    assert right.status == "error" and right.dz == pytest.approx(-0.6) and ext.status == "error"
    assert "below" in right.message and "not joined" in right.message
    assert max(e.offset for e in ext.points) == pytest.approx(3.0)     # nothing beyond the bank top


def test_no_data_and_end_of_model(profile):
    ext = extend_profile(profile, lambda x, y: None)
    assert {s.status for s in ext.sides.values()} == {"no_data"}
    clipped = lambda x, y: sloping(x, y) if abs(y) <= 8.0 else None  # noqa: E731
    ext = extend_profile(profile, clipped)
    assert ext.sides["left"].status == "ok" and "ends after 4.8 m" in ext.sides["left"].message
    assert min(e.offset for e in ext.points) == pytest.approx(-7.8)


def test_missing_bank_top():
    cl = Centerline([(0, 0), (100, 0)])
    pr = build_profile(cl, "X", [P(0, "a", 10, 2, 10.5, "water_level"), P(1, "b", 10, 0, 10, "bed"),
                                 P(2, "c", 10, -3, 11.2, "bank_top")])
    ext = extend_profile(pr, sloping)
    assert ext.sides["left"].status == "no_bank_top" and ext.sides["right"].status == "ok"
    assert ext.status == "review"


def test_no_bank_top_extends_from_outermost_bank_point():
    # surveyor stopped part-way up the left bank (bank toe at y = 2), no bank top on that side
    cl = Centerline([(0, 0), (100, 0)])
    pr = build_profile(cl, "Y", [P(0, "BK", 10, 2, 10.95, "bank_toe"), P(1, "VS", 10, 1, 10.4, "water_level"),
                                 P(2, "B", 10, 0, 10.0, "bed"), P(3, "KKH", 10, -3, 11.2, "bank_top")])
    ext = extend_profile(pr, sloping)
    left = ext.sides["left"]
    assert left.status == "from_outer_point" and left.join_offset == pytest.approx(-2.0)
    assert left.dz == pytest.approx(0) and "outermost point BK" in left.message
    assert min(e.offset for e in ext.points) == pytest.approx(-12.0)       # 10 m beyond the bank toe
    assert all(e.source == "measured" for e in ext.points if -2.0 <= e.offset <= 3.0)
    assert ext.status == "review"


def test_control_points_keep_mode(profile):
    ext = extend_profile(profile, lambda x, y: sloping(x, y) + 0.02, ExtensionSettings(control_points="keep"))
    assert not ext.controls
    t1 = [e for e in ext.points if e.name == "T1"][0]
    assert t1.source == "measured"
    assert min(e.offset for e in ext.points) == pytest.approx(-16.0)    # 10 m beyond T1 at −6
    assert ext.sides["left"].join_offset == pytest.approx(-6)
    assert ext.sides["left"].dz == pytest.approx(-0.02)


def test_control_deviation_reported(profile):
    ext = extend_profile(profile, lambda x, y: sloping(x, y) - 0.04)
    mean, mx = ext.control_deviation()
    assert mean == pytest.approx(0.04) and mx == pytest.approx(0.04)


def test_settings_validation():
    for bad in (dict(length=4), dict(length=51), dict(step=0), dict(tolerance=0.6),
                dict(transition=-1), dict(control_points="x")):
        with pytest.raises(ValueError):
            ExtensionSettings(**bad).validate()
    ExtensionSettings(length=50).validate()


def test_length_not_multiple_of_step(profile):
    ext = extend_profile(profile, sloping, ExtensionSettings(length=5.1))
    assert ext.sides["left"].samples == 13                       # 12 × 0.4 + the end at 5.1
    assert min(e.offset for e in ext.points) == pytest.approx(-8.1)


def test_grid_terrain_bilinear():
    # 3 × 3 cells of 0.4 m, upper-left corner (100, 200); cell centres at 100.2, 100.6, 101.0
    g = GridTerrain(100.0, 200.0, 0.4, [[1, 2, 3], [4, 5, 6], [7, 8, 9]], nodata=-9999)
    assert g(100.2, 199.8) == pytest.approx(1)                  # centre of the upper-left cell
    assert g(100.4, 199.8) == pytest.approx(1.5)                # halfway east
    assert g(100.4, 199.6) == pytest.approx(3.0)                # middle of four cells: (1+2+4+5)/4
    assert g(100.05, 199.95) == pytest.approx(1)                # edge half cell: edge value
    assert g(99.0, 199.0) is None and g(101.3, 199.0) is None
    g.values[1][1] = -9999
    assert g(100.4, 199.6) is None


def test_thin_function():
    pts = [(0, 0, "a"), (1, 0.01, "b"), (2, 0.0, "c"), (3, 0.5, "d"), (4, 0.5, "e")]
    assert [p[2] for p in thin(pts, 0.02)] == ["a", "c", "d", "e"]
    assert [p[2] for p in thin(pts, 1.0)] == ["a", "e"]


def test_synthetic_emlid_extended():
    s = read_survey(EMLID, code_table=codes.standard_table())
    geo = survey_geometry(s.points)

    def model(x, y):     # DHM 3 cm under the bank tops near the stream, flat 13.6
        return 13.6
    exts = extend_profiles(geo["profiles"], model, ExtensionSettings(dhm_version="syn"))
    assert len(exts) == 2
    p1 = exts[0]
    # left bank top 13.50 vs 13.60: dz = −0.10 → still direct (≤ 10 cm)
    assert p1.sides["left"].dz == pytest.approx(-0.10, abs=1e-6)
    assert p1.controls and p1.controls[0].point.name == "P01-01"
    assert p1.controls[0].deviation == pytest.approx(13.75 - 13.6)
    assert all(e.source in ("measured", "dhm", "transition") for e in p1.points)
