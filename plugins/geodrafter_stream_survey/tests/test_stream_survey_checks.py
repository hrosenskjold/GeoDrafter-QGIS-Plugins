# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Block 11: structures and drains on station, data check rules and per-municipality limits."""

import os

import pytest

from conftest import needs_qgis
from geodrafter_stream_survey.core.checks import (
    CheckSettings, interpolate, load_settings, run_checks, save_settings, settings_from_dict)
from geodrafter_stream_survey.core.geometry import Centerline, build_profile
from geodrafter_stream_survey.core.model import SurveyPoint
from geodrafter_stream_survey.gui.project import SurveyState

HERE = os.path.dirname(os.path.abspath(__file__))
EMLID = os.path.join(HERE, "data", "emlid_flow_SYNTHETIC.csv")


def state(terrain=None):
    st = SurveyState()
    st.run_import(EMLID)
    st.run_centerline()
    st.run_profiles()
    if terrain is not None:
        st.run_terrain(lambda pr, length: terrain)
    return st


def test_interpolate():
    assert interpolate(50, [(0, 10.0), (100, 9.0)]) == pytest.approx(9.5)
    two = [(0, 10.0), (100, 9.0)]
    assert interpolate(-5, two) == 10.0 and interpolate(150, two) == 9.0
    assert interpolate(5, []) is None and interpolate(5, [(0, None)]) is None


def test_structures_and_drain_depths():
    st = state()
    res = {s.point.name: s for s in st.run_structures()}
    rb, dr = res["RB1"], res["DR1"]
    # synthetic bed 12.40 at station 0 falling 1.5 ‰; RB1 0.05 m above bed at 55 m, DR1 0.55 m at 72 m
    assert rb.bed_z == pytest.approx(12.40 - 0.0015 * 55, abs=0.005)
    assert rb.above_bed == pytest.approx(0.05, abs=0.005)
    assert dr.above_bed == pytest.approx(0.55, abs=0.005)
    # water level ≈ bed + 0.415 → the drain invert lies 0.13 m above the water
    assert dr.below_water == pytest.approx(0.415 - 0.55, abs=0.01)
    assert rb.located.station < dr.located.station


def test_clean_synthetic_survey_has_only_expected_findings():
    st = state(terrain=lambda x, y: 13.5)
    found = st.run_check()
    kinds = sorted({c.kind for c in found})
    assert "not_fix" in kinds and "rms" in kinds               # DR1 is FLOAT with 0.187 m RMS
    assert "no_water_level" not in kinds and "bed_above_water" not in kinds and "spacing" not in kinds
    assert all(c.x > 500000 for c in found)
    assert [c.severity for c in found] == sorted([c.severity for c in found],
                                                 key=lambda s: {"error": 0, "warning": 1, "info": 2}[s])


def test_rules_trigger_on_bad_sections():
    cl = Centerline([(0, 0), (400, 0)])

    def P(i, n, x, y, z, t, status="FIX", rms=0.01):
        return SurveyPoint(seq=i, name=n, x=x, y=y, z=z, point_type=t, solution_status=status, rms_z=rms,
                           cs_name="ETRS89 / UTM zone 32N + DVR90")
    a = [P(0, "a1", 10, 3, 11, "bank_top"), P(1, "a2", 10, 0, 10.6, "bed"),
         P(2, "a3", 10, 1, 10.5, "water_level"),
         P(3, "a4", 11.5, -3, 11, "bank_top")]                 # 1.5 m off the line; bed above water
    b = [P(4, "b1", 200, 3, 11, "bank_top"), P(5, "b2", 200, 0, 10, "bed", "FLOAT", 0.08)]
    profs = [build_profile(cl, "A", a), build_profile(cl, "B", b)]
    pts = a + b

    def sp(pid):
        from geodrafter_stream_survey.core.terrain import ExtPoint
        pr = next(p for p in profs if p.id == pid)
        return [ExtPoint(pp.offset, pp.point.z, pp.point.x, pp.point.y, "measured", pp.point.point_type,
                         pp.point)
                for pp in pr.points]
    found = run_checks(pts, profs, sp, [], [], CheckSettings())
    kinds = [c.kind for c in found]
    assert "bed_above_water" in kinds and "far_from_line" in kinds and "spacing" in kinds
    assert kinds.count("no_bank_top") == 1                     # B has no right bank top
    assert "no_water_level" in kinds and "not_fix" in kinds and "rms" in kinds
    assert found[0].severity == "error"
    relaxed = CheckSettings(max_spacing=250, max_along=2.0, require_fix=False, max_rms_z=0.1,
                            require_water_level=False, require_bank_tops=False, bed_above_water_tol=0.2)
    assert run_checks(pts, profs, sp, [], [], relaxed) == []


def test_wrong_cs_is_an_error(tmp_path):
    p = tmp_path / "w.csv"
    txt = open(EMLID, encoding="utf-8").read()
    p.write_text(txt.replace("ETRS89 / UTM zone 32N + DVR90 height", "WGS 84"),
                 encoding="utf-8")
    st = SurveyState()
    st.run_import(str(p))
    st.run_centerline()
    st.run_profiles()
    found = st.run_check()
    assert found[0].kind == "cs_name" and found[0].severity == "error"


def test_dhm_jump_rule_and_settings_roundtrip(tmp_path):
    st = state(terrain=lambda x, y: 13.75)                     # 0.17–0.40 m above the bank tops
    found = st.run_check(CheckSettings(max_dhm_jump=0.10))
    assert any(c.kind == "dhm_jump" for c in found)
    assert not any(c.kind in ("terrain_shifted", "terrain_error") for c in st.checks)   # replaced by the rule
    s = CheckSettings(name="Aabenraa Kommune", max_spacing=100, require_fix=False)
    path = str(tmp_path / "aabenraa.yaml")
    save_settings(s, path)
    again = load_settings(path)
    assert again == s
    assert settings_from_dict({"max_spacing": "80", "require_fix": 0, "nonsense": 1}).max_spacing == 80.0


@needs_qgis
def test_steps_5_and_6_in_the_dock(qapp, tmp_path, monkeypatch):
    from qgis.core import QgsProject, QgsVectorLayer
    from qgis.gui import QgsMapCanvas
    from qgis_fakes import fake_iface
    import geodrafter_stream_survey as pkg
    from geodrafter_stream_survey.gui import codemap_dialog as cd

    monkeypatch.setattr(cd, "user_table_dir", lambda: str(tmp_path / "ct"))
    os.makedirs(str(tmp_path / "ct"), exist_ok=True)
    iface = fake_iface(QgsMapCanvas(), None)
    plugin = pkg.classFactory(iface)
    plugin.initGui()
    plugin.toggle(True)
    d = plugin.dock
    d.file_edit.setText(EMLID)
    gpkg = str(tmp_path / "c.gpkg")
    d.gpkg_edit.setText(gpkg)
    d.cl_build.setChecked(True)
    for step in ("import", "centerline", "profiles", "structures"):
        plugin.run_step(step)
        assert step in plugin.state.done, d.message.text()
    assert d.st_table.rowCount() == 2 and d.st_table.item(0, 0).text() == "RB1"
    lay = QgsVectorLayer("%s|layername=structures" % gpkg, "s", "ogr")
    f = next(f for f in lay.getFeatures() if f["name"] == "DR1")
    assert f["above_bed"] == pytest.approx(0.55, abs=0.01)
    d.chk_spacing.setValue(50.0)
    plugin.save_check_settings("Testkommune")
    assert os.path.exists(str(tmp_path / "checksettings" / "testkommune.yaml"))
    assert d.chk_combo.currentText() == "Testkommune"
    plugin.run_step("check")
    assert "check" in plugin.state.done
    assert any(c.kind == "spacing" for c in plugin.state.checks)          # 100 m > 50 m
    assert "errors" in d.chk_summary.text()
    plugin.unload()
    QgsProject.instance().removeAllMapLayers()
    QgsProject.instance().layerTreeRoot().removeAllChildren()
