"""Tests for GeoDrafter Pro Swipe. The map-tool tests need python3-qgis."""

import os
import time

import pytest

from conftest import ROOT, needs_qgis
from qgis_fakes import fake_iface as _fake_iface

PLUGIN_DIR = os.path.join(ROOT, "plugins", "geodrafter_pro_swipe")
KEEP_KEY = "geodrafter/pro_swipe/keep"

RED, GREEN, BLUE = (255, 0, 0, 255), (0, 200, 0, 255), (0, 0, 255, 255)
NOTHING = (0, 0, 0, 0)


def test_metadata_ok():
    from geodrafter_common.metadata import check_metadata, read_metadata
    meta = read_metadata(PLUGIN_DIR)
    assert check_metadata(meta) == []
    assert meta["name"] == "GeoDrafter Pro Swipe"
    assert "ArcGIS" not in meta["name"]
    assert meta["homepage"] == "https://geodrafter.com/qgis/pro-swipe/"
    assert os.path.isfile(os.path.join(PLUGIN_DIR, meta["icon"]))


def _wait(qapp, condition, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def _layer(name, rgba):
    from qgis.core import (QgsFeature, QgsFillSymbol, QgsGeometry, QgsRectangle,
                           QgsSingleSymbolRenderer, QgsVectorLayer)
    layer = QgsVectorLayer("Polygon?crs=EPSG:25832", name, "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromRect(QgsRectangle(-1000, -1000, 1000, 1000)))
    layer.dataProvider().addFeatures([f])
    layer.updateExtents()
    layer.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": "%d,%d,%d,%d" % rgba, "outline_style": "no"})))
    return layer


@pytest.fixture
def scene(qapp):
    """Three stacked, single-colour layers (red on green on blue) and a Layers panel with red selected."""
    from qgis.core import (QgsCoordinateReferenceSystem, QgsLayerTreeModel, QgsProject,
                           QgsRectangle, QgsSettings)
    from qgis.gui import QgsLayerTreeView, QgsMapCanvas
    from qgis.PyQt.QtCore import QObject, pyqtSignal

    class Signals(QObject):
        currentLayerChanged = pyqtSignal(object)  # noqa: N815

    class Pan:
        triggered = 0

        def trigger(self):
            Pan.triggered += 1

    QgsSettings().remove(KEEP_KEY)
    project = QgsProject.instance()
    project.clear()
    top, middle, bottom = _layer("top", RED), _layer("middle", GREEN), _layer("bottom", BLUE)
    project.addMapLayers([bottom, middle, top])

    canvas = QgsMapCanvas()
    canvas.resize(400, 300)
    canvas.show()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    canvas.setLayers([top, middle, bottom])
    canvas.setExtent(QgsRectangle(-400, -300, 400, 300))
    canvas.refresh()
    qapp.processEvents()

    view = QgsLayerTreeView()
    model = QgsLayerTreeModel(project.layerTreeRoot())
    view.setModel(model)
    view.setCurrentLayer(top)

    iface = _fake_iface(canvas, None)
    iface.signals = Signals()
    iface.currentLayerChanged = iface.signals.currentLayerChanged
    iface.layerTreeView = lambda: view
    iface.activeLayer = view.currentLayer
    iface.pan = Pan
    iface.actionPan = Pan
    Pan.triggered = 0
    iface.keep_alive = (view, model)
    yield canvas, iface, (top, middle, bottom)
    canvas.hide()
    QgsSettings().remove(KEEP_KEY)
    project.clear()


def _tool(qapp, canvas, iface, keep=False):
    from geodrafter_pro_swipe.swipe import SwipeTool
    tool = SwipeTool(iface, keep=keep)
    canvas.setMapTool(tool)
    assert _wait(qapp, lambda: tool.overlay.image is not None), "the view without the layer was not rendered"
    return tool


def _mouse(canvas, kind, x, y, down=True):
    from qgis.gui import QgsMapMouseEvent
    from qgis.PyQt.QtCore import QEvent, QPoint, Qt
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    kinds = {"press": (QEvent.Type.MouseButtonPress, left, left),
             "move": (QEvent.Type.MouseMove, none, left if down else none),
             "release": (QEvent.Type.MouseButtonRelease, left, none)}
    etype, button, buttons = kinds[kind]
    return QgsMapMouseEvent(canvas, etype, QPoint(x, y), button, buttons, Qt.KeyboardModifier.NoModifier)


def _drag(tool, canvas, start, end, release=True):
    tool.canvasPressEvent(_mouse(canvas, "press", *start))
    tool.canvasMoveEvent(_mouse(canvas, "move", *end))
    if release:
        tool.canvasReleaseEvent(_mouse(canvas, "release", *end))


def _painted(overlay, size):
    """What the overlay draws on top of the map, as an image (transparent where it draws nothing)."""
    from qgis.PyQt.QtGui import QImage, QPainter
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    overlay.paint(painter)
    painter.end()
    return image


def _rgba(image, x, y):
    c = image.pixelColor(x, y)
    return (c.red(), c.green(), c.blue(), c.alpha())


@needs_qgis
def test_zone_follows_the_nearest_edge(qapp):
    from geodrafter_pro_swipe.swipe import BOTTOM, LEFT, RIGHT, TOP, swiped_rect, zone
    assert zone(200, 10, 400, 300) == TOP
    assert zone(200, 290, 400, 300) == BOTTOM
    assert zone(10, 150, 400, 300) == LEFT
    assert zone(390, 150, 400, 300) == RIGHT
    assert zone(-50, 150, 400, 300) == LEFT       # outside the view: clamped, no error
    assert zone(5, 5, 0, 0) == TOP                # empty view
    rect = swiped_rect(TOP, 120, 90, 400, 300)
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == (0, 0, 400, 90)
    rect = swiped_rect(RIGHT, 120, 90, 400, 300)
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == (120, 0, 280, 300)
    rect = swiped_rect(BOTTOM, 120, 90, 400, 300)
    assert (rect.y(), rect.height()) == (90, 210)
    rect = swiped_rect(LEFT, 120, 90, 400, 300)
    assert (rect.x(), rect.width()) == (0, 120)


@needs_qgis
def test_swipe_shows_the_layer_underneath_and_release_restores(qapp, scene):
    from geodrafter_pro_swipe.swipe import RIGHT, TOP
    canvas, iface, (top, _middle, _bottom) = scene
    tool = _tool(qapp, canvas, iface)
    size = canvas.mapSettings().outputSize()
    w, h = size.width(), size.height()
    assert tool.swipe_layers() == [top]
    assert tool.overlay.side is None            # nothing swiped before a drag

    tool.canvasMoveEvent(_mouse(canvas, "move", w // 2, 10, down=False))
    assert tool._side_cursor == TOP             # the pointer shows the direction
    _drag(tool, canvas, (w // 2, 10), (w // 2, h // 2), release=False)
    assert tool.overlay.side == TOP
    image = _painted(tool.overlay, size)
    assert _rgba(image, w // 2, h // 4) == GREEN        # swiped part: the layer underneath
    assert _rgba(image, w // 2, 3 * h // 4) == NOTHING  # rest: the canvas with the red layer
    tool.canvasReleaseEvent(_mouse(canvas, "release", w // 2, h // 2))
    assert tool.overlay.side is None            # release brings the layer back

    _drag(tool, canvas, (w - 10, h // 2), (w // 2, h // 2), release=False)
    assert tool.overlay.side == RIGHT
    image = _painted(tool.overlay, size)
    assert _rgba(image, 3 * w // 4, h // 2) == GREEN
    assert _rgba(image, w // 4, h // 2) == NOTHING
    tool.canvasReleaseEvent(_mouse(canvas, "release", w // 2, h // 2))
    canvas.unsetMapTool(tool)
    tool.cleanup()


@needs_qgis
def test_selected_layers_decide_what_is_swiped(qapp, scene):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QItemSelectionModel
    from geodrafter_pro_swipe.swipe import LEFT
    canvas, iface, (top, middle, _bottom) = scene
    tool = _tool(qapp, canvas, iface)
    size = canvas.mapSettings().outputSize()
    w, h = size.width(), size.height()

    view = iface.layerTreeView()
    node = QgsProject.instance().layerTreeRoot().findLayer(middle.id())
    index = view.node2index(node) if hasattr(view, "node2index") else view.layerTreeModel().node2index(node)
    view.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select)
    assert sorted(layer.name() for layer in tool.swipe_layers()) == ["middle", "top"]
    assert tool.overlay.image is None           # the old image showed the previous selection
    assert _wait(qapp, lambda: tool.overlay.image is not None)

    _drag(tool, canvas, (10, h // 2), (w // 2, h // 2), release=False)
    assert tool.overlay.side == LEFT
    assert _rgba(_painted(tool.overlay, size), w // 4, h // 2) == BLUE   # both swiped: the bottom layer
    tool.canvasReleaseEvent(_mouse(canvas, "release", w // 2, h // 2))

    # A selected layer that is not drawn cannot be swiped: a hint, once, and no swipe
    view.setCurrentLayer(top)
    canvas.setLayers([middle, _bottom])
    assert _wait(qapp, lambda: tool.overlay.image is None)
    shown = len(iface.messageBar().items())
    _drag(tool, canvas, (w // 2, 10), (w // 2, h // 2))
    _drag(tool, canvas, (w // 2, 10), (w // 2, h // 2))
    assert tool.overlay.side is None
    assert len(iface.messageBar().items()) == shown + 1
    canvas.unsetMapTool(tool)
    tool.cleanup()


@needs_qgis
def test_keep_leaves_the_swipe_and_its_edge_can_be_dragged(qapp, scene):
    from qgis.PyQt.QtCore import QEvent, Qt
    from qgis.PyQt.QtGui import QKeyEvent
    from geodrafter_pro_swipe.swipe import BOTTOM
    canvas, iface, _layers = scene
    tool = _tool(qapp, canvas, iface, keep=True)
    size = canvas.mapSettings().outputSize()
    w, h = size.width(), size.height()

    _drag(tool, canvas, (w // 2, h - 10), (w // 2, h // 2))
    assert tool.overlay.side == BOTTOM          # still there after release
    image = _painted(tool.overlay, size)
    assert _rgba(image, w // 2, 3 * h // 4) == GREEN
    assert _rgba(image, w // 2, h // 4) == NOTHING

    # Near the kept edge the press grabs it, although the left side of the view is closer
    tool.canvasMoveEvent(_mouse(canvas, "move", 20, h // 2 + 3, down=False))
    assert tool._side_cursor == BOTTOM
    _drag(tool, canvas, (20, h // 2 + 3), (20, h // 4))
    assert tool.overlay.side == BOTTOM and tool.overlay.at.y() == h // 4
    assert _rgba(_painted(tool.overlay, size), w // 2, 3 * h // 8) == GREEN

    # Zooming renders the view again; the kept swipe stays
    old_key = tool._image_key
    canvas.zoomByFactor(0.5)
    assert _wait(qapp, lambda: tool._image_key not in (None, old_key))
    assert _rgba(_painted(tool.overlay, size), w // 2, 3 * h // 8) == GREEN

    other = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    tool.keyPressEvent(other)
    assert not other.isAccepted()               # left to the canvas (space bar panning)
    tool.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert tool.overlay.side is None            # Esc clears

    _drag(tool, canvas, (w // 2, 10), (w // 2, h // 2))
    assert tool.overlay.side is not None
    tool.set_keep(False)                        # switching keep off clears a kept swipe
    assert tool.overlay.side is None
    canvas.unsetMapTool(tool)
    tool.cleanup()


@needs_qgis
def test_plugin_toggle_keep_setting_and_unload(qapp, scene):
    from qgis.core import QgsSettings
    import geodrafter_pro_swipe
    canvas, iface, _layers = scene
    plugin = geodrafter_pro_swipe.classFactory(iface)
    plugin.initGui()
    assert [a.text() for a in iface.menu] == [
        "Pro Swipe", "Pro Swipe: keep the swipe on release", "About GeoDrafter Pro Swipe"]
    assert iface.pluginToolBar().actions() == [plugin.swipe_action]
    assert not plugin.keep_action.isChecked()

    plugin.swipe_action.trigger()
    tool = plugin.tool
    assert canvas.mapTool() is tool and plugin.swipe_action.isChecked()
    assert tool.overlay.isVisible() and tool.overlay.scene() is canvas.scene()

    plugin.keep_action.trigger()
    assert tool.keep is True and QgsSettings().value(KEEP_KEY, False, type=bool) is True
    plugin.keep_action.trigger()
    assert tool.keep is False and QgsSettings().value(KEEP_KEY, True, type=bool) is False

    plugin.swipe_action.trigger()               # off again: back to Pan, nothing left on the map
    assert canvas.mapTool() is not tool and iface.pan.triggered == 1
    assert not plugin.swipe_action.isChecked()
    assert not tool.overlay.isVisible() and tool.overlay.image is None and tool._job is None

    plugin.swipe_action.trigger()               # unload while active and rendering
    plugin.unload()
    assert iface.menu == [] and iface.pluginToolBar().actions() == []
    assert tool.overlay.scene() is None and tool._job is None
    canvas.refresh()                            # no slot of the unloaded tool fires
    qapp.processEvents()
