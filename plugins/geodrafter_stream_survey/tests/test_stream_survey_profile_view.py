# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Block 10: profile view – edits on the survey state (pure) and the view in QGIS."""

import os

import pytest

from conftest import needs_qgis
from geodrafter_stream_survey.gui.project import SurveyState

HERE = os.path.dirname(os.path.abspath(__file__))
EMLID = os.path.join(HERE, "data", "emlid_flow_SYNTHETIC.csv")


def state(terrain=True):
    st = SurveyState()
    st.run_import(EMLID)
    st.run_centerline()
    st.run_profiles()
    if terrain:
        st.run_terrain(lambda pr, length: (lambda x, y: 13.45))   # 5–13 cm from the bank tops
    return st


def test_section_points_before_and_after_terrain():
    st = state(terrain=False)
    pts = st.section_points("P01")
    assert [e.source for e in pts] == ["measured"] * 9 and pts[0].offset < pts[-1].offset
    st = state()
    pts = st.section_points("P01")
    assert {"measured", "dhm"} <= {e.source for e in pts}
    z, left, right = st.water_level("P01")
    assert z == pytest.approx((12.82 + 12.81) / 2) and left < 0 < right


def test_move_point_updates_survey_point():
    st = state()
    pts = st.section_points("P01")
    i = next(k for k, e in enumerate(pts) if e.point is not None and e.point.name == "P01-05")
    old = (pts[i].point.x, pts[i].point.y)
    st.move_point("P01", i, pts[i].offset + 0.5, 12.30)
    p = next(e for e in st.section_points("P01") if e.point is not None and e.point.name == "P01-05")
    assert p.z == pytest.approx(12.30) and p.point.z == pytest.approx(12.30)
    pr = st.profile("P01")
    assert (p.point.x - pr.x) * pr.normal[0] + (p.point.y - pr.y) * pr.normal[1] == pytest.approx(p.offset)
    assert p.point.extra["edited_from"].startswith("%.3f %.3f" % old)
    offs = [e.offset for e in st.section_points("P01")]
    assert offs == sorted(offs)


def test_set_code_and_remove_dhm():
    st = state()
    pts = st.section_points("P01")
    i = next(k for k, e in enumerate(pts) if e.point is not None and e.point.code == "B")
    e = st.set_point_code("P01", i, "VS")
    assert e.point.code == "VS" and e.point_type == "water_level" and e.point.code_known
    j = next(k for k, e in enumerate(pts) if e.point is None)
    with pytest.raises(ValueError):
        st.set_point_code("P01", j, "B")
    st.remove_dhm("P01", "left")
    pts = st.section_points("P01")
    assert not [e for e in pts if e.source != "measured" and e.offset < 0]
    assert [e for e in pts if e.source != "measured" and e.offset > 0]
    assert st.extended_profile("P01").sides["left"].status == "removed"


def test_edits_without_terrain_step():
    st = state(terrain=False)
    st.move_point("P02", 0, -3.0, 13.0)
    assert st.extended_profile("P02") is not None
    assert st.section_points("P02")[0].z == pytest.approx(13.0)


@needs_qgis
def test_profile_view_in_qgis(qapp, tmp_path):
    from qgis.PyQt.QtCore import QPoint, Qt
    from qgis.PyQt.QtTest import QTest
    from qgis.core import QgsPointXY, QgsProject
    from qgis.gui import QgsMapCanvas
    from qgis_fakes import fake_iface
    import geodrafter_stream_survey as pkg

    canvas = QgsMapCanvas()
    iface = fake_iface(canvas, None)
    plugin = pkg.classFactory(iface)
    plugin.initGui()
    plugin.toggle(True)
    d = plugin.dock
    d.file_edit.setText(EMLID)
    d.gpkg_edit.setText(str(tmp_path / "v.gpkg"))
    d.cl_build.setChecked(True)
    for step in ("import", "centerline", "profiles"):
        plugin.run_step(step)
    v = plugin.view
    assert v is not None and v.ids == ["P01", "P02"] and v.current() == "P01"
    assert v.table.rowCount() == 9 and v.table.item(0, 5).text() == "Measured"
    assert not v.prev_button.isEnabled() and v.next_button.isEnabled()
    v.step(1)
    assert v.current() == "P02" and v.table.rowCount() == 8
    v.step(-1)
    # drag the deepest point 20 px down in the drawing
    cv = v.canvas
    cv.resize(600, 300)
    cv.set_data(cv.points, cv.water)
    i = min(range(len(cv.points)), key=lambda k: cv.points[k].z)
    q = cv.to_px(cv.points[i].offset, cv.points[i].z)
    start = QPoint(int(q.x()), int(q.y()))
    old_z = cv.points[i].z
    QTest.mousePress(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(cv, start + QPoint(0, 20))
    QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(0, 20))
    moved = [e for e in plugin.state.section_points("P01") if e.point is not None
             and e.point.extra.get("edited_from")]
    assert len(moved) == 1 and moved[0].z < old_z
    # change a code through the signal (the menu itself needs a user)
    v.codeChanged.emit("P01", 1, "KK")
    assert plugin.state.section_points("P01")[1].point.code == "KK"
    # map click on the second section opens it
    pr = plugin.state.profile("P02")
    plugin.on_map_click(QgsPointXY(pr.x, pr.y))
    assert v.current() == "P02"
    assert plugin.nearest_profile(pr.x + 500, pr.y, 5.0) is None
    v.pick_button.setChecked(True)
    assert canvas.mapTool() is plugin.pick_tool
    v.pick_button.setChecked(False)
    img = cv.grab()                                 # paints without errors
    assert not img.isNull()
    plugin.unload()
    assert plugin.view is None
    QgsProject.instance().removeAllMapLayers()
    QgsProject.instance().layerTreeRoot().removeAllChildren()
