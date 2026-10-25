# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Block 12: long profile and exports (CSV, HEC-RAS, MIKE, PDF)."""

import csv
import io
import os
import re

import pytest

from conftest import needs_qgis
from geodrafter_stream_survey.core import export
from geodrafter_stream_survey.gui.project import SurveyState

HERE = os.path.dirname(os.path.abspath(__file__))
EMLID = os.path.join(HERE, "data", "emlid_flow_SYNTHETIC.csv")


def state(terrain=True):
    st = SurveyState()
    st.run_import(EMLID)
    st.run_centerline()
    st.run_profiles()
    if terrain:
        st.run_terrain(lambda pr, length: (lambda x, y: 13.45))
    return st


def test_long_profile_rows():
    rows = export.long_profile(state().section_data())
    assert [r.id for r in rows] == ["P01", "P02"]
    r1 = rows[0]
    assert r1.bed == pytest.approx(12.40) and r1.water == pytest.approx((12.82 + 12.81) / 2)
    assert r1.bank_left == pytest.approx(13.50) and r1.bank_right == pytest.approx(13.58)
    assert r1.terrain_left == pytest.approx(13.45) and r1.terrain_right == pytest.approx(13.45)
    assert rows[1].bed == pytest.approx(12.40 - 0.15)
    no_dhm = export.long_profile(state(terrain=False).section_data())
    assert no_dhm[0].terrain_left is None


def test_sections_csv_has_sources():
    rows = list(csv.DictReader(io.StringIO(export.sections_csv(state().section_data())), delimiter=";"))
    assert {r["source"] for r in rows} >= {"measured", "dhm"}
    m = next(r for r in rows if r["name"] == "P01-05")
    assert m["profile_id"] == "P01" and m["code"] == "B" and m["dhm_version"] == ""
    lp = list(csv.DictReader(io.StringIO(export.long_profile_csv(state().section_data())), delimiter=";"))
    assert lp[0]["bed"] == "12.400" and lp[1]["station"] == "100.00"


def test_hecras_geometry_structure():
    st = state()
    g = export.hecras_geometry(st.section_data(), st.centerline.coords, title="Test", river="Testå")
    lines = g.splitlines()
    assert lines[0] == "Geom Title=Test" and lines[3] == ""
    xs = [ln for ln in lines if ln.startswith("Type RM Length L Ch R = 1 ,")]
    assert len(xs) == 2
    rs = [float(ln.split(",")[1]) for ln in xs]
    assert rs == pytest.approx([100.0, 0.0], abs=0.05)                   # counted from downstream
    assert [float(v) for v in xs[0].split(",")[2:]] == pytest.approx([100.0] * 3, abs=0.05)
    i = lines.index(next(ln for ln in lines if ln.startswith("#Sta/Elev=")))
    n = int(lines[i].split("=")[1])
    vals = []
    j = i + 1
    while len(vals) < 2 * n:
        row = lines[j]
        assert len(row) <= 80 and len(row) % 8 == 0                     # 8-character fields
        vals += [float(row[k:k + 8]) for k in range(0, len(row), 8)]
        j += 1
    sta = vals[0::2]
    assert sta[0] == 0.0 and sta == sorted(sta)                         # left to right from 0
    bank = next(ln for ln in lines if ln.startswith("Bank Sta="))
    lb, rb = (float(v) for v in bank.split("=")[1].split(","))
    assert 0 < lb < rb < sta[-1]
    assert "Reach XY= %d " % len(st.centerline.coords) in g and "#Mann= 3 , 0 , 0 " in g


def test_mike_cross_sections_markers():
    t = export.mike_cross_sections(state(terrain=False).section_data(), river="Testå")
    blocks = [b for b in t.split("*******************************") if b.strip()]
    assert len(blocks) == 2
    b1 = blocks[0].strip().splitlines()
    assert b1[1] == "Testå" and float(b1[2]) == pytest.approx(0.0, abs=0.01)
    n = int(re.search(r"PROFILE\s+(\d+)", blocks[0]).group(1))
    rows = [ln for ln in b1 if "<#" in ln]
    assert len(rows) == n == 9
    marks = [int(re.search(r"<#(\d+)>", ln).group(1)) for ln in rows]
    assert marks.count(1) == 1 and marks.count(2) == 1 and marks.count(4) == 1
    z = [float(ln.split()[1]) for ln in rows]
    assert z[marks.index(2)] == min(z)
    # the left bank top (KK at offset −2.4) carries marker 1; the terrain point outside has none
    assert marks[0] == 0 and marks[1] == 1


@needs_qgis
def test_exports_from_the_plugin(qapp, tmp_path):
    from qgis.core import QgsProject
    from qgis.gui import QgsMapCanvas
    from qgis_fakes import fake_iface
    import geodrafter_stream_survey as pkg

    plugin = pkg.classFactory(fake_iface(QgsMapCanvas(), None))
    plugin.initGui()
    plugin.toggle(True)
    d = plugin.dock
    d.file_edit.setText(EMLID)
    d.gpkg_edit.setText(str(tmp_path / "e.gpkg"))
    d.cl_build.setChecked(True)
    for step in ("import", "centerline", "profiles"):
        plugin.run_step(step)
    plugin.state.run_terrain(lambda pr, length: (lambda x, y: 13.45))
    d.river_edit.setText("Testå")
    for kind, name in (("csv", "a.csv"), ("long_csv", "b.csv"), ("hecras", "c.g01"), ("mike", "d.txt")):
        p = plugin.export_to(kind, str(tmp_path / name))
        assert os.path.getsize(p) > 100
    assert "Geom Title=Testå" in open(str(tmp_path / "c.g01"), encoding="utf-8").read()
    pdf = str(tmp_path / "p.pdf")
    plugin.export_to("pdf", pdf)
    data = open(pdf, "rb").read()
    assert data.startswith(b"%PDF") and len(re.findall(rb"/Type\s*/Page[^s]", data)) == 3   # long + 2
    assert "3 pages" in d.export_summary.text()
    assert "export" in plugin.state.done
    v = plugin.view
    v.tabs.setCurrentIndex(2)
    assert len(v.long.rows) == 2 and not v.long.grab().isNull()
    v.long._station_clicked = None
    v._station_clicked(95.0)
    assert v.current() == "P02"
    plugin.unload()
    QgsProject.instance().removeAllMapLayers()
    QgsProject.instance().layerTreeRoot().removeAllChildren()
