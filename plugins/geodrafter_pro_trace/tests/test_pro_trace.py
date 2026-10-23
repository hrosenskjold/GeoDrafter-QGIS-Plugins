"""Tests for GeoDrafter Pro Trace. The map-tool tests need python3-qgis."""

import os

import pytest

from conftest import ROOT, needs_qgis
from qgis_fakes import fake_iface as _fake_iface

PLUGIN_DIR = os.path.join(ROOT, "plugins", "geodrafter_pro_trace")


def test_metadata_ok():
    from geodrafter_common.metadata import check_metadata, read_metadata
    meta = read_metadata(PLUGIN_DIR)
    assert check_metadata(meta) == []
    assert meta["name"] == "GeoDrafter Pro Trace"
    assert "ArcGIS" not in meta["name"]
    assert meta["homepage"] == "https://geodrafter.com/qgis/pro-trace/"
    assert os.path.isfile(os.path.join(PLUGIN_DIR, meta["icon"]))
    text = open(os.path.join(PLUGIN_DIR, "metadata.txt"), encoding="utf-8").read().lower()
    assert "limfjord" not in text  # credit only the author


@pytest.fixture
def scene(qapp):
    """L-shaped stream (0,0)-(100,0)-(100,100) plus a diagonal shortcut, UTM32."""
    from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry,
                           QgsPointXY, QgsProject, QgsRectangle, QgsVectorLayer)
    from qgis.gui import QgsMapCanvas

    project = QgsProject.instance()
    project.clear()
    net = QgsVectorLayer("LineString?crs=EPSG:25832", "streams", "memory")
    feats = []
    for pts in ([(0, 0), (100, 0), (100, 100)], [(0, 0), (100, 100)]):
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts]))
        feats.append(f)
    net.dataProvider().addFeatures(feats)
    target = QgsVectorLayer("MultiLineString?crs=EPSG:25832", "new", "memory")
    area = QgsVectorLayer("Polygon?crs=EPSG:25832", "areas", "memory")
    project.addMapLayers([net, target, area])

    canvas = QgsMapCanvas()
    canvas.resize(480, 480)
    canvas.show()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    canvas.setLayers([net, target, area])
    canvas.setExtent(QgsRectangle(-20, -20, 120, 120))
    canvas.refresh()
    qapp.processEvents()
    yield canvas, net, target, area
    canvas.hide()
    project.clear()


def _pt(x, y):
    from qgis.core import QgsPointXY
    return QgsPointXY(x, y)


@needs_qgis
def test_trace_follows_l_not_shortcut(scene):
    from geodrafter_pro_trace.trace import TraceTool
    canvas, net, target, _area = scene
    assert 0 < canvas.mapUnitsPerPixel() < 1
    iface = _fake_iface(canvas, target)
    tool = TraceTool(iface)
    canvas.setMapTool(tool)
    assert tool.layer is target and target.isEditable()

    tool.handle_click(tool.resolve_map_point(_pt(0.3, 0.2)))   # snaps to (0,0)
    assert tool.points == [_pt(0, 0)]
    for x, y in [(20, 0), (50, 0.4), (80, 0), (100, 0), (100, 30), (100.3, 60), (100, 100)]:
        tool.handle_move(tool.resolve_map_point(_pt(x, y)))
    assert tool.trace[-1] == _pt(100, 100)
    tool.handle_click(tool.resolve_map_point(_pt(100, 100)), finish=True)

    feats = list(target.getFeatures())
    assert len(feats) == 1
    geom = feats[0].geometry()
    assert geom.isMultipart()
    assert abs(geom.length() - 200) < 1e-6        # along the L, not the 141 m diagonal
    tool.cleanup()


@needs_qgis
def test_trace_pulls_back_and_mixes_freehand(scene):
    from geodrafter_pro_trace.trace import TraceTool
    canvas, net, target, _area = scene
    tool = TraceTool(_fake_iface(canvas, target))
    canvas.setMapTool(tool)
    tool.handle_click(tool.resolve_map_point(_pt(0, 0)))
    for x in (30, 60, 90):
        tool.handle_move(tool.resolve_map_point(_pt(x, 0)))
    assert abs(tool.trace[-1].x() - 90) < 0.5
    tool.handle_move(tool.resolve_map_point(_pt(40, 0)))       # move back
    assert abs(tool.trace[-1].x() - 40) < 0.5
    tool.handle_click(tool.resolve_map_point(_pt(40, 0)))      # lock
    tool.handle_move(tool.resolve_map_point(_pt(40, 60)))      # off the network
    assert tool._free_tail
    tool.handle_click(tool.resolve_map_point(_pt(40, 60)))     # free vertex
    assert tool.points[-1] == _pt(40, 60)
    tool.undo_step()                                           # Backspace
    assert tool.points[-1] != _pt(40, 60)
    tool.cleanup()


@needs_qgis
def test_polygon_and_wrong_layer(scene):
    from geodrafter_pro_trace.trace import TraceTool
    canvas, net, _target, area = scene
    iface = _fake_iface(canvas, area)
    tool = TraceTool(iface)
    canvas.setMapTool(tool)
    tool.handle_click(tool.resolve_map_point(_pt(0, 0)))
    tool.handle_move(tool.resolve_map_point(_pt(100, 0)))
    tool.handle_click(tool.resolve_map_point(_pt(100, 0)))
    tool.handle_move(tool.resolve_map_point(_pt(100, 100)))
    tool.handle_click(tool.resolve_map_point(_pt(100, 100)), finish=True)
    feats = list(area.getFeatures())
    assert len(feats) == 1 and abs(feats[0].geometry().area() - 5000) < 1e-6
    tool.cleanup()

    from qgis.core import QgsVectorLayer
    points = QgsVectorLayer("Point?crs=EPSG:25832", "pts", "memory")
    assert TraceTool.layer_kind(points) == (False, None)
    assert TraceTool.layer_kind(None) == (False, None)


@needs_qgis
def test_truncate_polyline(qapp):
    from geodrafter_pro_trace.trace import truncate_polyline
    out = truncate_polyline([_pt(0, 0), _pt(10, 0), _pt(10, 10)], 15)
    assert out == [_pt(0, 0), _pt(10, 0), _pt(10, 5)]


@needs_qgis
def test_plugin_load_unload(scene):
    import geodrafter_pro_trace
    canvas, _net, target, _area = scene
    iface = _fake_iface(canvas, target)
    plugin = geodrafter_pro_trace.classFactory(iface)
    plugin.initGui()
    assert iface.menu == []                # Vector menu, not Plugins
    assert len(iface.vector_menu) == 3  # Pro Trace + Split + About (no Share while Publish is offline)
    assert plugin.trace_action in iface.pluginToolBar().actions()
    assert plugin.split_action in iface.pluginToolBar().actions()
    plugin.trace_action.trigger()
    assert canvas.mapTool() is plugin.tool and plugin.trace_action.isChecked()
    plugin.split_action.trigger()
    assert canvas.mapTool() is plugin.split_tool and plugin.split_tool.mode == "split"
    assert plugin.split_action.isChecked() and not plugin.trace_action.isChecked()
    plugin.split_action.trigger()                       # second click switches it off
    assert canvas.mapTool() is None
    plugin.unload()
    assert iface.vector_menu == [] and plugin.tool is None
    assert iface.pluginToolBar().actions() == []


@needs_qgis
def test_only_layers_switched_on_in_the_layers_panel_are_traced(scene):
    # Henrik 17/10: a layer that is switched off in the Layers panel (not on the canvas), or not shown at
    # the current scale, must not be traced or snapped to.
    from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer

    from geodrafter_pro_trace.trace import TraceTool
    canvas, net, target, area = scene
    hidden = QgsVectorLayer("LineString?crs=EPSG:25832", "hidden", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromPolylineXY([_pt(0, 50), _pt(100, 50)]))
    hidden.dataProvider().addFeatures([f])
    QgsProject.instance().addMapLayer(hidden)        # in the project, but switched off (not on the canvas)
    tool = TraceTool(_fake_iface(canvas, target))
    canvas.setMapTool(tool)
    assert hidden not in tool.traceable_layers() and net in tool.traceable_layers()
    # A click on the hidden line is a plain freehand point, not snapped onto it.
    assert tool.resolve_map_point(_pt(40, 50.4)) == _pt(40, 50.4)

    canvas.setLayers([net, target, area, hidden])     # switched on
    assert hidden in tool.traceable_layers()
    assert tool.resolve_map_point(_pt(40, 50.4)).distance(_pt(40, 50)) < 1e-6

    hidden.setScaleBasedVisibility(True)              # shown only when zoomed in beyond 1:10
    hidden.setMinimumScale(10)
    hidden.setMaximumScale(1)
    assert canvas.scale() > 10 and hidden not in tool.traceable_layers()
    tool.cleanup()


def _square(x0, y0, x1, y1):
    from qgis.core import QgsFeature, QgsGeometry
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt(
        "POLYGON((%s %s,%s %s,%s %s,%s %s,%s %s))" % (x0, y0, x1, y0, x1, y1, x0, y1, x0, y0)))
    return f


def _trace(tool, start, moves, finish=True):
    tool.handle_click(tool.resolve_map_point(start))
    for p in moves:
        tool.handle_move(tool.resolve_map_point(p))
    tool.handle_click(tool.resolve_map_point(moves[-1]), finish=finish)


@needs_qgis
def test_split_polygons_along_a_trace(scene):
    """Split mode: the diagonal stream cuts the squares it crosses; selection limits it; one undo step."""
    from geodrafter_pro_trace.trace import TraceTool
    canvas, _net, _target, area = scene
    area.dataProvider().addFeatures([_square(10, 0, 40, 30), _square(60, 50, 90, 80)])
    iface = _fake_iface(canvas, area)
    tool = TraceTool(iface, mode="split")
    canvas.setMapTool(tool)
    assert tool.layer is area and area.isEditable()

    diagonal = [_pt(x, x) for x in (10, 25, 40, 55, 70, 85, 100)]
    _trace(tool, _pt(0, 0), diagonal)
    areas = sorted(round(f.geometry().area()) for f in area.getFeatures())
    # y=x cuts 10..40 x 0..30 into 200 + 700 and 60..90 x 50..80 into 200 + 700
    assert areas == [200, 200, 700, 700]
    assert not tool.points and tool.band_locked.numberOfVertices() == 0      # sketch cleared
    area.undoStack().undo()                                                  # one undo step
    assert area.featureCount() == 2

    # With a selection only the selected square is split
    first = min(area.getFeatures(), key=lambda f: f.geometry().centroid().asPoint().x())
    area.selectByIds([first.id()])
    _trace(tool, _pt(0, 0), diagonal)
    assert area.featureCount() == 3
    area.removeSelection()
    area.undoStack().undo()

    # A line that does not cross anything: nothing happens, the user is told why
    count = len(iface.bar.items())
    _trace(tool, _pt(0, 0), [_pt(50, 0), _pt(100, 0)])                    # along the L's bottom
    assert area.featureCount() == 2
    assert len(iface.bar.items()) == count + 1
    tool.cleanup()


@needs_qgis
def test_split_lines_and_freehand_start(scene):
    """Split mode on a line layer, starting freehand off the network."""
    from qgis.core import QgsFeature, QgsGeometry
    from geodrafter_pro_trace.trace import TraceTool
    canvas, _net, target, _area = scene
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt("MultiLineString((50 -10, 50 60))"))
    target.dataProvider().addFeatures([f])
    tool = TraceTool(_fake_iface(canvas, target), mode="split")
    canvas.setMapTool(tool)
    tool.handle_click(tool.resolve_map_point(_pt(20, -15)))       # freehand start, off the network
    tool.handle_move(tool.resolve_map_point(_pt(30, -15)))
    tool.handle_click(tool.resolve_map_point(_pt(30, 0)))         # onto the bottom of the L
    for x in (45, 60, 75):
        tool.handle_move(tool.resolve_map_point(_pt(x, 0)))       # traced along it, across x=50
    tool.handle_click(tool.resolve_map_point(_pt(75, 0)), finish=True)
    lengths = sorted(round(g.geometry().length()) for g in target.getFeatures())
    assert lengths == [10, 60]
    tool.cleanup()


@needs_qgis
def test_split_mode_validation(qapp):
    from geodrafter_pro_trace.trace import TraceTool
    with pytest.raises(ValueError):
        TraceTool(None, mode="cut")
