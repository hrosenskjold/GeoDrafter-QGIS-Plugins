# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Block 9: survey state (pure), GeoPackage layers, raster terrain and the plugin in QGIS."""

import os

import pytest

from conftest import needs_qgis
from geodrafter_stream_survey.gui.project import SurveyState

HERE = os.path.dirname(os.path.abspath(__file__))
EMLID = os.path.join(HERE, "data", "emlid_flow_SYNTHETIC.csv")


def plane(x, y):
    """A terrain plane 13.6 m – the synthetic bank tops are 13.50/13.58 and 13.35/13.43."""
    return 13.6


def run_all(state, terrain=plane):
    state.run_import(EMLID)
    state.run_centerline()
    state.run_profiles()
    state.run_terrain(lambda pr, length: terrain)
    return state


def test_state_steps_in_order_and_reset():
    st = SurveyState()
    with pytest.raises(RuntimeError):
        st.run_profiles()
    run_all(st)
    assert st.done == {"import", "centerline", "profiles", "terrain"}
    assert [p.id for p in st.profiles] == ["P01", "P02"]
    assert {lp.point.name for lp in st.located} == {"RB1", "DR1"}
    assert len(st.extended) == 2
    kinds = {c.kind for c in st.checks}
    assert "control" in kinds                         # P01-01 is a terrain control point
    # P02 right bank 13.43 − 13.6 = −0.17 → shifted, a warning with the place
    shifted = [c for c in st.checks if c.kind == "terrain_shifted"]
    assert shifted and all(c.severity == "warning" and c.x > 500000 for c in shifted)
    st.run_centerline(station_value=1000.0)           # an earlier step again resets the later ones
    assert st.done == {"import", "centerline"} and not st.profiles and not st.extended
    st.run_profiles()
    assert st.profiles[0].station == pytest.approx(1000.0, abs=0.5)


def test_state_terrain_error():
    st = run_all(SurveyState(), terrain=lambda x, y: 14.5)    # 1 m above the bank tops
    assert {e.status for e in st.extended} == {"error"}
    assert any(c.severity == "error" and c.kind == "terrain_error" for c in st.checks)


def test_import_failure_is_clear(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("Name,Easting,Northing\n", encoding="utf-8")
    with pytest.raises(ValueError):
        SurveyState().run_import(str(p))


# --- QGIS ---------------------------------------------------------------------------

@needs_qgis
def test_geopackage_layers(qapp, tmp_path):
    from qgis.core import QgsProject, QgsVectorLayer
    from geodrafter_stream_survey.gui.layers import SCHEMAS, build_layers, load_geopackage, write_geopackage

    st = run_all(SurveyState())
    layers = build_layers(st)
    path = str(tmp_path / "survey.gpkg")
    assert write_geopackage(layers, path) == []
    counts = {}
    for name in SCHEMAS:
        lay = QgsVectorLayer("%s|layername=%s" % (path, name), name, "ogr")
        assert lay.isValid(), name
        assert lay.crs().authid() == "EPSG:25832"
        counts[name] = lay.featureCount()
    assert counts["points"] == 19 and counts["centerline"] == 1 and counts["profiles"] == 2
    assert counts["structures"] == 2 and counts["extensions"] >= 2 and counts["checks"] >= 1
    pp = QgsVectorLayer("%s|layername=profile_points" % path, "pp", "ogr")
    sources = {f["source"] for f in pp.getFeatures()}
    assert {"measured", "dhm"} <= sources
    f = next(f for f in pp.getFeatures() if f["name"] == "P01-05")
    assert f["side"] in ("center", "left", "right") and f["station"] == pytest.approx(st.profiles[0].station)
    assert all(f["dhm_version"] == "" for f in pp.getFeatures() if f["source"] == "measured")
    # loading twice refreshes the same group
    proj = QgsProject.instance()
    load_geopackage(path, proj)
    shown = load_geopackage(path, proj)
    group = proj.layerTreeRoot().findGroup("GeoDrafter Stream Survey – survey")
    assert group is not None and len(group.findLayers()) == len(shown) == 7
    proj.removeAllMapLayers()
    proj.layerTreeRoot().removeAllChildren()


def _write_geotiff(path, ox, oy, cell, rows, cols, func):
    from osgeo import gdal, osr
    gdal.UseExceptions()
    ds = gdal.GetDriverByName("GTiff").Create(path, cols, rows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((ox, cell, 0, oy, 0, -cell))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(25832)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-9999)
    import array
    for r in range(rows):
        vals = array.array("f", [func(ox + (c + 0.5) * cell, oy - (r + 0.5) * cell) for c in range(cols)])
        band.WriteRaster(0, r, cols, 1, vals.tobytes())
    ds.FlushCache()
    ds = None


@needs_qgis
def test_raster_terrain_bilinear(qapp, tmp_path):
    pytest.importorskip("osgeo.gdal")
    from geodrafter_stream_survey.gui.terrain_source import RasterTerrain, file_layer, wcs_uri

    def f(x, y):   # a tilted plane: bilinear sampling reproduces it exactly
        return 10.0 + 0.01 * (x - 541150) + 0.02 * (y - 6103350)
    path = str(tmp_path / "dem.tif")
    _write_geotiff(path, 541150.0, 6103450.0, 0.4, 500, 500, f)
    rt = RasterTerrain(file_layer(path))
    g = rt.for_extent(541190, 6103390, 541210, 6103410)
    for x, y in ((541200.0, 6103400.0), (541201.13, 6103397.77), (541195.5, 6103405.05)):
        assert g(x, y) == pytest.approx(f(x, y), abs=1e-4)
    assert rt.for_extent(541190, 6103390, 541210, 6103410)(541100, 6103400) is None   # outside the block
    st = SurveyState()
    st.run_import(EMLID)
    st.run_centerline()
    st.run_profiles()
    exts = st.run_terrain(rt.for_profile)
    assert all(e.sides["left"].dz is not None for e in exts)
    # the token never goes into the layer source
    assert "token" not in wcs_uri("abc1234").lower().replace("authcfg", "")


@needs_qgis
def test_plugin_dock_runs_steps(qapp, tmp_path):
    pytest.importorskip("osgeo.gdal")
    from qgis.core import QgsProject, QgsRasterLayer
    from qgis.gui import QgsMapCanvas
    from qgis_fakes import fake_iface
    import geodrafter_stream_survey as pkg

    path = str(tmp_path / "dem.tif")
    _write_geotiff(path, 541150.0, 6103450.0, 0.4, 500, 500, lambda x, y: 13.58)
    dem = QgsRasterLayer(path, "dem", "gdal")
    QgsProject.instance().addMapLayer(dem)
    canvas = QgsMapCanvas()
    iface = fake_iface(canvas, None)
    plugin = pkg.classFactory(iface)
    plugin.initGui()
    assert len(iface.menu) == 2 and len(iface.pluginToolBar().actions()) == 1
    plugin.toggle(True)
    d = plugin.dock
    assert d.steps.count() == 7 and d.pages.count() == 7
    d.file_edit.setText(EMLID)
    d.gpkg_edit.setText(str(tmp_path / "out.gpkg"))
    assert d.cl_inspire.isChecked()                  # INSPIRE is the default (Henrik 24/10) …
    d.cl_build.setChecked(True)                       # … but the tests use no network
    for step in ("import", "centerline", "profiles"):
        plugin.run_step(step)
        assert step in plugin.state.done, d.message.text()
    d.src_layer.setChecked(True)
    d.raster_combo.setLayer(dem)
    plugin.run_step("terrain")
    assert "terrain" in plugin.state.done, d.message.text()
    assert os.path.exists(str(tmp_path / "out.gpkg"))
    assert set(plugin.layers) >= {"points", "profiles", "profile_points", "extensions", "checks"}
    assert d.check_list.count() >= 1
    # an error is shown, not raised
    d.file_edit.setText(str(tmp_path / "missing.csv"))
    plugin.run_step("import")
    assert d.message.text().startswith("Step failed")
    assert d.steps.item(0).foreground().color().name() == "#c0392b"    # the failed step turns red
    plugin.unload()
    assert iface.menu == [] and iface.pluginToolBar().actions() == []
    QgsProject.instance().removeAllMapLayers()
    QgsProject.instance().layerTreeRoot().removeAllChildren()


@needs_qgis
def test_danish_translation_loads(qapp):
    from geodrafter_stream_survey.gui import i18n
    plugin_dir = os.path.dirname(HERE)
    if not os.path.exists(os.path.join(plugin_dir, "i18n", "geodrafter_stream_survey_da.qm")):
        pytest.skip("translation not compiled")
    assert i18n.install(plugin_dir, "da_DK") == "da"
    try:
        assert i18n.tr("Cross-sections") == "Tværprofiler"
        assert i18n.tr("Terrain extension") == "Terrænforlængelse"
    finally:
        i18n.remove()
    assert i18n.tr("Cross-sections") == "Cross-sections"


def test_danish_translation_complete():
    from tools import update_ts
    assert update_ts.missing("geodrafter_stream_survey", "da") == []
    qm = update_ts.ts_path("geodrafter_stream_survey", "da")[:-3] + ".qm"
    assert os.path.exists(qm)


# --- block 9c: centre line sources -----------------------------------------------------

def _synthetic_line(shift=0.0, extend=150.0):
    """The synthetic stream's axis (through the lowest bed points), shifted sideways, as WFS parts."""
    import math
    from geodrafter_stream_survey.core.centerline_source import WatercourseFeature
    az = math.radians(120.0)
    dx, dy = math.sin(az), math.cos(az)
    rx, ry = math.cos(az), -math.sin(az)
    x0, y0 = 541200.0 + rx * (-0.4 + shift), 6103400.0 + ry * (-0.4 + shift)
    pts = [(x0 + dx * s, y0 + dy * s) for s in (-extend, 40.0, 45.0, 100.0 + extend)]
    return [WatercourseFeature(pts[:2], "name:Synthetic Å"), WatercourseFeature(pts[2:], "name:Synthetic Å"),
            WatercourseFeature([(x + 30 * rx, y + 30 * ry) for x, y in pts], "name:Grøft")]


def test_state_centerline_from_watercourse_features():
    st = SurveyState()
    st.run_import(EMLID)
    st.run_centerline(features=_synthetic_line(), source="INSPIRE test")
    assert "Synthetic Å" in st.notes_source and "1 gap" in st.notes_source
    assert st.centerline.source == "INSPIRE test"
    assert st.line_fit.median < 0.8 and st.line_fit.maximum < 1.5     # all bed points, ±1.4 m
    assert not st.checks_by_step["centerline"]
    st.run_profiles()
    assert st.profiles[1].station - st.profiles[0].station == pytest.approx(100, abs=0.05)


def test_state_centerline_distance_warning_and_fit():
    st = SurveyState()
    st.run_import(EMLID)
    st.run_centerline(features=_synthetic_line(shift=8.0), source="INSPIRE test", max_distance=5.0)
    w = [c for c in st.checks if c.kind == "centerline_distance"]
    assert w and 7.5 < w[0].value < 9.5
    st.run_centerline(features=_synthetic_line(shift=8.0), source="INSPIRE test", fit_to_bed=True)
    assert not [c for c in st.checks if c.kind == "centerline_distance"]
    assert "fitted" in st.centerline.source


def test_state_centerline_no_watercourse_falls_back():
    st = SurveyState()
    st.run_import(EMLID)
    cl = st.run_centerline(features=[])
    assert cl.source == "surveyed sections"
    assert [c.kind for c in st.checks] == ["centerline_source"]


@needs_qgis
def test_inspire_features_and_own_line_in_other_crs(qapp):
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsGeometry
    from qgis.core import QgsPointXY, QgsProject, QgsVectorLayer
    from geodrafter_stream_survey.gui.inspire import features_in
    from geodrafter_stream_survey.gui.plugin import line_coords

    # a stand-in for the WFS layer: same handling, in WGS84
    lay = QgsVectorLayer("LineString?crs=EPSG:4326&field=name:string&field=localId:string", "wfs", "memory")
    to4326 = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:25832"),
                                    QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
    feats = []
    for wf in _synthetic_line():
        f = QgsFeature(lay.fields())
        f.setGeometry(QgsGeometry.fromPolylineXY([to4326.transform(QgsPointXY(x, y)) for x, y in wf.coords]))
        f["name"] = wf.key.split(":", 1)[1]
        feats.append(f)
    far = QgsFeature(lay.fields())
    far.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(12.0, 56.0), QgsPointXY(12.1, 56.0)]))
    far["localId"] = "far"
    feats.append(far)
    lay.dataProvider().addFeatures(feats)
    got = features_in(lay, 541150, 6103300, 541300, 6103420, margin=200)
    assert {g.key for g in got} == {"name:Synthetic Å", "name:Grøft"}       # the far one is outside
    assert all(500000 < x < 600000 for g in got for x, _y in g.coords)       # back in EPSG:25832
    st = SurveyState()
    st.run_import(EMLID)
    st.run_centerline(features=got, source="INSPIRE")
    assert st.line_fit.maximum < 1.5
    # own line layer in another CRS: the selected feature, transformed
    lay.selectByIds([feats[0].id()])
    coords = line_coords(lay, prefer_selected=True)
    assert 541000 < coords[0][0] < 541300


def _layer_from_emlid(crs="EPSG:25832", z_in_geometry=False, drop_elevation=False):
    """A memory point layer like an opened Emlid export (fields by name, file order kept)."""
    import csv
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsField,
                           QgsGeometry, QgsPoint, QgsProject, QgsVectorLayer)

    def text_field(name):
        try:
            from qgis.PyQt.QtCore import QMetaType
            return QgsField(name, QMetaType.Type.QString)
        except TypeError:                     # QGIS < 3.38
            from qgis.PyQt.QtCore import QVariant
            return QgsField(name, QVariant.String)
    rows = list(csv.DictReader(open(EMLID, encoding="utf-8")))
    keep = ["Name", "Code", "Description", "Solution status", "Elevation RMS", "Antenna height"]
    if not drop_elevation:
        keep.append("Elevation")
    uri = ("PointZ?crs=%s" if z_in_geometry else "Point?crs=%s") % crs
    layer = QgsVectorLayer(uri, "emlid", "memory")
    layer.dataProvider().addAttributes([text_field(k) for k in keep])
    layer.updateFields()
    t = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:25832"), QgsCoordinateReferenceSystem(crs),
                               QgsProject.instance())
    feats = []
    for r in rows:
        f = QgsFeature(layer.fields())
        p = t.transform(float(r["Easting"]), float(r["Northing"]))
        f.setGeometry(QgsGeometry(QgsPoint(p.x(), p.y(), float(r["Elevation"]))) if z_in_geometry
                      else QgsGeometry.fromPointXY(p))
        f.setAttributes([r[k] for k in keep])
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    return layer


@needs_qgis
def test_survey_from_project_layer(qapp):
    from geodrafter_stream_survey.core import codes
    from geodrafter_stream_survey.core.readers import read_survey
    from geodrafter_stream_survey.gui.layer_source import is_point_layer, survey_from_layer
    ref = read_survey(EMLID, code_table=codes.standard_table())
    s = survey_from_layer(_layer_from_emlid(), code_table=codes.standard_table())
    assert [p.name for p in s.points] == [p.name for p in ref.points]           # file order kept
    assert [p.point_type for p in s.points] == [p.point_type for p in ref.points]
    assert s.points[1].x == pytest.approx(ref.points[1].x) and s.points[1].z == pytest.approx(ref.points[1].z)
    assert s.points[-1].solution_status == ref.points[-1].solution_status and s.reader == "layer"
    # another CRS is transformed to UTM 32N; Z from the geometry when there is no Elevation field
    s = survey_from_layer(_layer_from_emlid("EPSG:4326", z_in_geometry=True, drop_elevation=True))
    assert s.points[1].x == pytest.approx(ref.points[1].x, abs=0.01)
    assert s.points[1].z == pytest.approx(ref.points[1].z)
    assert any("transformed from EPSG:4326" in w or "DVR90" in w for w in s.warnings)
    assert is_point_layer(_layer_from_emlid())


@needs_qgis
def test_dock_imports_a_project_layer_and_takes_drops(qapp, tmp_path):
    from qgis.core import QgsProject
    from qgis.gui import QgsMapCanvas
    from qgis.PyQt.QtCore import QMimeData, QUrl
    from qgis_fakes import fake_iface
    import geodrafter_stream_survey as pkg

    layer = _layer_from_emlid()
    QgsProject.instance().addMapLayer(layer)
    iface = fake_iface(QgsMapCanvas(), None)
    plugin = pkg.classFactory(iface)
    plugin.initGui()
    plugin.toggle(True)
    d = plugin.dock
    d.gpkg_edit.setText(str(tmp_path / "out.gpkg"))
    # a layer dragged from the Layers panel
    d.file_edit.layerDropped.emit(layer.id())
    assert d.survey_layer() is layer and d.file_edit.text() == ""
    plugin.run_step("import")
    assert "import" in plugin.state.done, d.message.text()
    assert len(plugin.state.survey.points) == 19 and plugin.state.survey.reader == "layer"
    # a dropped file replaces the layer
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(EMLID)])
    assert d.file_edit._decode(mime) == ("file", EMLID)
    d.file_edit.setText(EMLID)
    assert d.survey_layer() is None
    plugin.run_step("import")
    assert plugin.state.survey.reader != "layer"
    plugin.unload()
    QgsProject.instance().removeAllMapLayers()


@needs_qgis
def test_code_pairing_pops_up_and_reimports(qapp, tmp_path, monkeypatch):
    """Unknown codes open the pairing by itself; the field can be changed there; saving re-imports."""
    from qgis.core import QgsProject
    from qgis.gui import QgsMapCanvas
    from qgis_fakes import fake_iface
    import geodrafter_stream_survey as pkg
    from geodrafter_stream_survey.gui import codemap_dialog as cd
    from test_stream_survey_vasp import _numbered_survey

    monkeypatch.setattr(cd, "user_table_dir", lambda: str(tmp_path))
    seen = {}

    def fake_exec(dlg):
        seen["fields"] = [dlg.field_combo.itemData(i) for i in range(dlg.field_combo.count())]
        seen["first"] = (dlg.field, len(dlg.mapped))
        dlg.field_combo.setCurrentIndex(dlg.field_combo.findData("code_description"))   # user picks the field
        seen["after"] = (dlg.field, len(dlg.mapped), dlg.mapped[0].suggestion.reason)
        dlg.save()
        return True

    monkeypatch.setattr(cd.CodeMapDialog, "exec", fake_exec)
    plugin = pkg.classFactory(fake_iface(QgsMapCanvas(), None))
    plugin.initGui()
    plugin.toggle(True)
    d = plugin.dock
    d.file_edit.setText(_numbered_survey(tmp_path))
    d.gpkg_edit.setText(str(tmp_path / "out.gpkg"))
    d.code_field_combo.setCurrentIndex(d.code_field_combo.findData("auto"))
    plugin.run_step("import")
    assert plugin.state.code_column == "code_description"           # found by itself: no pop-up needed
    assert "Code description" in d.import_summary.text()
    d.code_field_combo.setCurrentIndex(d.code_field_combo.findData("code"))   # the user forces 'Code'
    plugin.popup_codes = False
    plugin.run_step("import")
    assert d.unknown_button.isEnabled() and "Unknown codes" in d.unknown_button.text()
    plugin.unknown_codes(popup=True)                                 # what the pop-up does
    assert seen["first"][0] == "code" and "code_description" in seen["fields"]
    assert seen["after"][0] == "code_description" and seen["after"][2].startswith("VASP tag")
    assert plugin.state.code_column == "code_description"            # re-imported with the saved table
    assert all(p.code_known for p in plugin.state.survey.points)
    assert d.table_path().startswith(str(tmp_path))
    plugin.unload()
    QgsProject.instance().removeAllMapLayers()
