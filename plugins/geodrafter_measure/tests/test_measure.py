"""Tests for GeoDrafter Measure."""

import os

import pytest

from conftest import ROOT, needs_qgis

from geodrafter_measure import units

PLUGIN_DIR = os.path.join(ROOT, "plugins", "geodrafter_measure")
CPH = (12.5683, 55.6761)      # lon, lat
AARHUS = (10.2039, 56.1629)
CPH_AARHUS_M = 157441.026     # pyproj Geod(WGS84).inv
BOX_M2 = 6857247564.419       # 10–11°E x 56–57°N, pyproj Geod polygon_area


def test_units():
    assert units.fmt_length(1234.5, "m") == "1 234.5 m"
    assert units.fmt_length(1234.5, "km") == "1.234 km" or units.fmt_length(1234.5, "km") == "1.235 km"
    assert units.fmt_area(25000, "ha") == "2.500 ha"
    assert units.auto_length_unit(999) == "m" and units.auto_length_unit(1000) == "km"
    assert units.auto_length_unit(2000, imperial=True) == "mi"
    assert units.auto_area_unit(5e6) == "km2" and units.auto_area_unit(5e4) == "ha"
    assert units.parse_length("5 km") == 5000
    assert units.parse_length("2,5km") == 2500
    assert units.parse_length("300") == 300
    assert units.parse_length("1 mi") == pytest.approx(1609.344)
    assert units.parse_length("2 NM") == 3704
    assert units.parse_length("") is None and units.parse_length("-3") is None
    assert units.parse_length("abc") is None


def test_metadata():
    from geodrafter_common.metadata import check_metadata, read_metadata
    assert check_metadata(read_metadata(PLUGIN_DIR)) == []


def _crs(code):
    from qgis.core import QgsCoordinateReferenceSystem
    return QgsCoordinateReferenceSystem(code)


def _to(crs_code, lon, lat):
    from qgis.core import QgsCoordinateTransform, QgsPointXY, QgsProject
    t = QgsCoordinateTransform(_crs("EPSG:4326"), _crs(crs_code), QgsProject.instance())
    return QgsPointXY(t.transform(QgsPointXY(lon, lat)))


@needs_qgis
@pytest.mark.parametrize("crs", ["EPSG:4326", "EPSG:25832", "EPSG:3857"])
def test_geodesic_independent_of_projection(qapp, crs):
    from qgis.core import QgsProject
    from geodrafter_measure.measure import MeasureEngine
    QgsProject.instance().setEllipsoid("NONE")
    eng = MeasureEngine(_crs(crs))
    a, b = _to(crs, *CPH), _to(crs, *AARHUS)
    assert eng.line_length([a, b]) == pytest.approx(CPH_AARHUS_M, abs=0.5)
    box = [_to(crs, 10, 56), _to(crs, 11, 56), _to(crs, 11, 57), _to(crs, 10, 57)]
    # QGIS measures polygon edges as straight lines in the source CRS: allow 0.5 %
    assert eng.polygon_area(box) == pytest.approx(BOX_M2, rel=5e-3)
    ring = eng.circle(a, 5000, segments=36)
    for p in ring[::6]:
        assert eng.radius_between(a, p) == pytest.approx(5000, abs=0.01)
    assert eng.bearing(_to(crs, 10, 56), _to(crs, 10, 57)) == pytest.approx(0, abs=1e-6)


@needs_qgis
def test_tool_flow_and_layers(qapp):
    from qgis.core import QgsProject
    from qgis.gui import QgsMapCanvas
    from geodrafter_measure.measure import (AREA, DISTANCE, RADIUS, MeasureTool, add_to_layer,
                                            describe, measurements_layer)
    project = QgsProject.instance()
    project.clear()
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(_crs("EPSG:25832"))
    tool = MeasureTool(canvas)
    done = []
    tool.finished.connect(done.append)

    tool.add_point(_to("EPSG:25832", *CPH))
    tool.move(_to("EPSG:25832", *AARHUS))
    assert tool.preview().values(tool.engine)["length_m"] == pytest.approx(CPH_AARHUS_M, abs=0.5)
    tool.add_point(_to("EPSG:25832", *AARHUS))
    tool.finish()
    assert len(done) == 1 and done[0].mode == DISTANCE
    lines = describe(DISTANCE, done[0].values(tool.engine))
    assert lines == ["Distance: 157.44 km"]

    tool.set_mode(AREA)
    for lon, lat in [(10, 56), (11, 56), (11, 57)]:
        tool.add_point(_to("EPSG:25832", lon, lat))
    tool.finish()
    assert done[-1].mode == AREA and len(done[-1].points) == 3

    tool.set_mode(RADIUS, fixed_radius_m=2500)
    tool.add_point(_to("EPSG:25832", *CPH))       # one click places the circle
    circle = done[-1]
    assert circle.mode == RADIUS and circle.radius_m == 2500
    vals = circle.values(tool.engine)
    assert vals["area_m2"] == pytest.approx(3.14159 * 2500 ** 2, rel=2e-3)
    assert describe(RADIUS, vals)[0] == "Radius: 2.500 km"

    tool.set_mode(RADIUS)                          # drag mode: centre + edge
    tool.add_point(_to("EPSG:25832", 10, 56))
    tool.add_point(_to("EPSG:25832", 10, 56.01))
    assert done[-1].radius_m == pytest.approx(1112, abs=2)

    lines_layer = measurements_layer(project, tool.engine.crs, DISTANCE)
    areas_layer = measurements_layer(project, tool.engine.crs, RADIUS)
    assert lines_layer is measurements_layer(project, tool.engine.crs, DISTANCE)
    add_to_layer(lines_layer, done[0], tool.engine, "x")
    f = add_to_layer(areas_layer, circle, tool.engine, "circle")
    assert f["radius_m"] == 2500 and f["kind"] == "radius"
    assert lines_layer.featureCount() == 1 and areas_layer.featureCount() == 1
    assert next(lines_layer.getFeatures())["length_m"] == pytest.approx(CPH_AARHUS_M, abs=0.5)
    tool.cleanup()
    project.clear()


@needs_qgis
def test_plugin_and_export(qapp, tmp_path):
    from qgis.core import QgsProject, QgsVectorLayer
    from qgis.gui import QgsMapCanvas
    from qgis_fakes import fake_iface
    import geodrafter_measure as pkg
    from geodrafter_measure.plugin import export_layers

    project = QgsProject.instance()
    project.clear()
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(_crs("EPSG:25832"))
    iface = fake_iface(canvas, None)
    plugin = pkg.classFactory(iface)
    plugin.initGui()
    plugin.action.trigger()
    assert canvas.mapTool() is plugin.tool and plugin.dock is not None
    plugin.dock.mode_buttons["radius"].setChecked(True)
    plugin.dock.radius_edit.setText("1 km")
    plugin.dock.radius_edit.editingFinished.emit()
    assert plugin.tool.mode == "radius" and plugin.tool.fixed_radius_m == 1000
    plugin.tool.add_point(_to("EPSG:25832", *CPH))
    assert "Radius: 1.000 km" in plugin.dock.result.toPlainText()
    layers = plugin._measurement_layers()
    assert [lyr.name() for lyr in layers] == ["GeoDrafter areas"]
    assert layers[0].featureCount() == 1

    out = str(tmp_path / "m.gpkg")
    assert export_layers(layers, out, project.transformContext()) == []
    check = QgsVectorLayer(out + "|layername=geodrafter_areas", "c", "ogr")
    assert check.isValid() and check.featureCount() == 1
    plugin.unload()
    assert iface.menu == [] and plugin.dock is None
    project.clear()
