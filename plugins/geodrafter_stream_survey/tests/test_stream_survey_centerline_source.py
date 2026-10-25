# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Block 9c: centre line from a watercourse WFS response (mocked, no network)."""

import pytest

from geodrafter_stream_survey.core.centerline_source import (
    WatercourseFeature, assemble, bed_distance, clip_to_points, features_from_geojson, fit_to_bed,
    pick_watercourse, watercourse_centerline, watercourse_key)
from geodrafter_stream_survey.core.geometry import Centerline, orient_downstream
from geodrafter_stream_survey.core.model import SurveyPoint


def mocked_wfs():
    """Three watercourses near the survey: the right one (Hønsebæk) in three segments, one of them
    digitised the other way and one piped stretch missing 20 m; a ditch nearby; a river far off."""
    def line(cid, name, coords):
        return {"type": "Feature", "id": cid, "properties": {"localId": cid, "name": name},
                "geometry": {"type": "LineString", "coordinates": coords}}
    return {"type": "FeatureCollection", "features": [
        line("wc.2", "Hønsebæk", [[100, 0.4], [200, 0.2]]),                    # middle part
        line("wc.1", "Hønsebæk", [[100, 0.4], [50, 0.5], [0, 0.0]]),           # reversed first part
        line("wc.3", "Hønsebæk", [[220, 0.0], [400, 0.0]]),                    # after a 20 m gap
        line("d.1", "Grøft", [[0, 12], [400, 12]]),
        {"type": "Feature", "id": "r.1", "properties": {"localId": "r.1"},
         "geometry": {"type": "MultiLineString", "coordinates": [[[0, 500], [400, 500]]]}},
    ]}


def bed(xs, y=0.0, z0=10.0, fall=0.001):
    return [SurveyPoint(seq=i, name="B%d" % i, x=x, y=y, z=z0 - fall * x, point_type="bed")
            for i, x in enumerate(xs)]


def test_geojson_and_keys():
    feats = features_from_geojson(mocked_wfs())
    assert len(feats) == 5
    assert feats[0].key == "name:Hønsebæk" and feats[4].key == "id:r.1"
    assert watercourse_key({"LOCALID": "x"}) == "id:x" and watercourse_key({}) == ""


def test_pick_the_watercourse_nearest_the_bed_points():
    feats = features_from_geojson(mocked_wfs())
    key, chosen, med = pick_watercourse(feats, [(p.x, p.y) for p in bed([60, 140, 260])])
    assert key == "name:Hønsebæk" and len(chosen) == 3 and med < 0.5


def test_assemble_order_reversal_and_gap():
    feats = [f for f in features_from_geojson(mocked_wfs()) if f.key == "name:Hønsebæk"]
    coords, used, gaps = assemble([f.coords for f in feats], tolerance=1.0, max_gap=50.0, start_near=(150, 0))
    assert used == 3 and gaps == [pytest.approx(20.0, abs=0.01)]
    assert coords[0] == (0.0, 0.0) and coords[-1] == (400.0, 0.0)
    assert coords == [(0.0, 0.0), (50.0, 0.5), (100.0, 0.4), (200.0, 0.2), (220.0, 0.0), (400.0, 0.0)]
    # a gap over max_gap is not bridged
    coords, used, _g = assemble([f.coords for f in feats], max_gap=10.0, start_near=(150, 0))
    assert used == 2 and coords[-1] == (200.0, 0.2)


def test_clip_to_points():
    coords = [(0.0, 0.0), (1000.0, 0.0), (2000.0, 0.0)]
    out = clip_to_points(coords, [(900, 3), (1300, -2)], margin=200)
    assert out == [(700.0, 0.0), (1000.0, 0.0), (1500.0, 0.0)]


def test_whole_chain_and_direction():
    feats = features_from_geojson(mocked_wfs())
    pts = bed([60, 140, 260, 330])
    coords, info = watercourse_centerline(feats, [(p.x, p.y) for p in pts], margin=50)
    assert info["key"] == "name:Hønsebæk" and info["used"] == 3 and len(info["gaps"]) == 1
    assert coords[0] == pytest.approx((10.0, 0.1), abs=0.01)
    assert coords[-1] == pytest.approx((380.0, 0.0), abs=0.01)
    cl, why = orient_downstream(Centerline(coords), pts)
    assert why.startswith("kept")                         # bed falls towards x = 400
    rising = bed([60, 140, 260, 330], fall=-0.001)
    cl, why = orient_downstream(Centerline(coords), rising)
    assert why.startswith("reversed") and cl.coords[0] == pytest.approx((380.0, 0.0), abs=0.01)


def test_distance_check_and_fit_to_bed():
    cl = Centerline([(0, 0), (400, 0)])
    pts = [(100, 2.0), (200, 7.5), (300, 1.0)]
    fit = bed_distance(cl, pts)
    assert fit.median == pytest.approx(2.0) and fit.maximum == pytest.approx(7.5) and fit.n == 3
    fitted = fit_to_bed(cl, pts)
    assert fitted.coords == [(0, 0), (100, 2.0), (200, 7.5), (300, 1.0), (400, 0)]
    assert bed_distance(fitted, pts).maximum == pytest.approx(0)
    assert "fitted" in fitted.source


def test_no_features():
    coords, info = watercourse_centerline([], [(0, 0)])
    assert coords is None and info["reason"]
    assert pick_watercourse([WatercourseFeature([(0, 0), (1, 1)], "k")], [])[0] == "k"
