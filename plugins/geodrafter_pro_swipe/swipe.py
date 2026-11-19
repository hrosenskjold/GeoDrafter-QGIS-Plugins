# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Pro Swipe – peel a layer back to see what is underneath.

ArcGIS Pro-style swipe: select one or more layers in the Layers panel, then
drag in the map. Start near the top or bottom of the map to swipe vertically,
near the left or right side to swipe horizontally; the cursor arrow shows the
direction. The selected layers are pulled back from that edge to the cursor.

How it works: the canvas keeps showing the whole map. The tool renders the
same view once more *without* the selected layers and paints that image over
the swiped-away part of the canvas. Transparency, blend modes and labels are
therefore exactly what QGIS itself would draw with the layers switched off.

Scoped Qt and QGIS enums only, so the same code runs on QGIS 3.34 and newer,
including 4.x (Qt6).
"""

from qgis.PyQt.QtCore import QCoreApplication, QPoint, QPointF, QRectF, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QCursor, QPainter, QPen, QPixmap, QPolygonF

from qgis.core import Qgis, QgsMapRendererParallelJob, QgsMapSettings
from qgis.gui import QgsMapCanvasItem, QgsMapTool

PLUGIN_NAME = "GeoDrafter Pro Swipe"

TOP, BOTTOM, LEFT, RIGHT = "top", "bottom", "left", "right"

#: Cursor rotation per side; the arrow is drawn pointing down (swipe from the top).
_CURSOR_ANGLE = {TOP: 0, BOTTOM: 180, LEFT: -90, RIGHT: 90}


def tr(text):
    return QCoreApplication.translate("GeoDrafterProSwipe", text)


def zone(x, y, width, height):
    """The map edge a swipe starting at (x, y) pulls the layer back from.

    The view is divided by its two diagonals: the triangle towards the top
    edge gives TOP, and so on – like the swipe pointer in ArcGIS Pro.
    """
    if width <= 0 or height <= 0:
        return TOP
    fx = min(max(x / width, 0.0), 1.0)
    fy = min(max(y / height, 0.0), 1.0)
    if fy <= fx and fy <= 1.0 - fx:
        return TOP
    if fy >= fx and fy >= 1.0 - fx:
        return BOTTOM
    return LEFT if fx < 0.5 else RIGHT


def swiped_rect(side, x, y, width, height):
    """The part of a width × height view that is swiped away (QRectF)."""
    if side == TOP:
        return QRectF(0, 0, width, y)
    if side == BOTTOM:
        return QRectF(0, y, width, height - y)
    if side == LEFT:
        return QRectF(0, 0, x, height)
    return QRectF(x, 0, width - x, height)


def view_key(settings):
    """What must be unchanged for a rendered image to still fit the canvas."""
    size = settings.outputSize()
    return (settings.extent().toString(), size.width(), size.height(), settings.rotation(),
            settings.destinationCrs().authid(), settings.devicePixelRatio())


def swipe_cursor(side, ratio=1.0):
    """Arrow cursor for ``side``: a bar (the layer edge) and the way it is pulled."""
    size = 32
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(size / 2, size / 2)
    painter.rotate(_CURSOR_ANGLE[side])
    pen = QPen(QColor(255, 255, 255), 1.5)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QColor(31, 58, 95))
    painter.drawRect(QRectF(-11, -2, 22, 4))
    painter.drawPolygon(QPolygonF([QPointF(-7, 5), QPointF(7, 5), QPointF(0, 14)]))
    painter.end()
    return QCursor(pixmap, size // 2, size // 2)


class SwipeOverlay(QgsMapCanvasItem):
    """Paints the map without the swiped layers over the swiped-away part."""

    def __init__(self, canvas):
        super().__init__(canvas)
        self.image = None      # the view rendered without the swiped layers
        self.view_size = None  # its size in canvas (logical) pixels
        self.side = None       # TOP/BOTTOM/LEFT/RIGHT while a swipe is shown
        self.at = QPoint()     # where the swipe edge is, canvas pixels
        self.setZValue(-9.0)   # just above the map, below rubber bands and markers

    def set_image(self, image, view_size=None):
        self.prepareGeometryChange()
        self.image = image
        self.view_size = view_size if image is not None else None
        self.update()

    def set_swipe(self, side, at=None):
        self.side = side
        if at is not None:
            self.at = QPoint(at)
        self.update()

    def boundingRect(self):  # noqa: N802
        if self.view_size is None:
            return QRectF()
        return QRectF(0, 0, self.view_size.width(), self.view_size.height())

    def updatePosition(self):  # noqa: N802
        # Screen-fixed: the image is dropped and rendered again when the view changes.
        pass

    def paint(self, painter, option=None, widget=None):
        if self.image is None or self.side is None:
            return
        width, height = self.view_size.width(), self.view_size.height()
        x = min(max(self.at.x(), 0), width)
        y = min(max(self.at.y(), 0), height)
        rect = swiped_rect(self.side, x, y, width, height)
        if rect.width() <= 0 or rect.height() <= 0:
            return
        painter.save()
        painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        painter.drawImage(QRectF(0, 0, width, height), self.image)
        painter.restore()
        # The swipe edge: thin dark line with a light halo, readable on any map.
        if self.side in (TOP, BOTTOM):
            a, b = QPointF(0, y), QPointF(width, y)
        else:
            a, b = QPointF(x, 0), QPointF(x, height)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor(255, 255, 255, 170), 3))
        painter.drawLine(a, b)
        painter.setPen(QPen(QColor(31, 58, 95), 1))
        painter.drawLine(a, b)
        painter.restore()


class SwipeTool(QgsMapTool):
    """Map tool that swipes the layers selected in the Layers panel.

    Usage:

      * Select the layer (or several layers, or a group) to swipe.
      * Press the left mouse button and drag. Starting near the top or bottom
        of the map swipes vertically, near the sides horizontally.
      * Releasing the button brings the layer back – unless ``keep`` is on,
        then the swipe stays until Esc, and its edge can be grabbed again.
      * Mouse wheel, middle button and space bar navigate as usual.
    """

    #: How close (pixels) a press must be to a kept swipe edge to grab it.
    GRAB_PX = 8

    def __init__(self, iface, keep=False):
        canvas = iface.mapCanvas()
        super().__init__(canvas)
        self.iface = iface
        self.map_canvas = canvas
        self.keep = bool(keep)

        self.overlay = SwipeOverlay(canvas)
        self.overlay.hide()

        self._job = None          # running render of the view without the swiped layers
        self._job_key = None
        self._job_size = None
        self._restart = False     # render again as soon as the cancelled job has stopped
        self._image_key = None    # view_key the overlay image was rendered for
        self._dragging = False
        self._told = False        # the "select a layer" hint was shown
        self._cursors = {}
        self._side_cursor = None
        self._connections = []

        # Selection changes arrive in bursts; render once when they settle.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._selection_settled)

    # ------------------------------------------------------------------ layers

    def swipe_layers(self):
        """Layers selected in the Layers panel (groups count as their layers)."""
        view = self.iface.layerTreeView()
        layers = []
        if view is not None:
            try:
                layers = list(view.selectedLayersRecursive())
            except AttributeError:
                layers = list(view.selectedLayers())
        if not layers:
            layer = self.iface.activeLayer()
            layers = [layer] if layer is not None else []
        return [layer for layer in layers if layer is not None]

    def _split_layers(self, settings):
        """(layers drawn in the view that are swiped, the layers that stay)."""
        ids = {layer.id() for layer in self.swipe_layers()}
        swiped, rest = [], []
        for layer in settings.layers():
            (swiped if layer.id() in ids else rest).append(layer)
        return swiped, rest

    # --------------------------------------------------------------- rendering

    def _render(self):
        """Render the current view without the swiped layers, in the background."""
        if self._job is not None:
            self._restart = True
            self._job.cancelWithoutBlocking()
            return
        settings = QgsMapSettings(self.map_canvas.mapSettings())
        swiped, rest = self._split_layers(settings)
        if not swiped or settings.outputSize().isEmpty():
            self._set_image(None)
            return
        settings.setLayers(rest)
        job = QgsMapRendererParallelJob(settings)
        job.finished.connect(self._job_finished)
        self._job = job
        self._job_key = view_key(settings)
        self._job_size = settings.outputSize()
        job.start()

    def _job_finished(self):
        job, key, size = self._job, self._job_key, self._job_size
        self._job = None
        if job is None:
            return
        restart, self._restart = self._restart, False
        if restart:
            job.deleteLater()
            self._render()
            return
        image = job.renderedImage()
        job.deleteLater()
        # The view may have moved on while rendering; renderStarting then renders anew.
        if not image.isNull() and key == view_key(self.map_canvas.mapSettings()):
            self._set_image(image, key, size)

    def _stop_job(self):
        job, self._job = self._job, None
        self._restart = False
        if job is None:
            return
        try:
            job.finished.disconnect(self._job_finished)
        except (TypeError, RuntimeError):
            pass
        job.cancel()
        job.deleteLater()

    def _set_image(self, image, key=None, size=None):
        self._image_key = key if image is not None else None
        self.overlay.set_image(image, size)

    def _drop_stale_image(self):
        """Hide the image at once when it no longer fits the view (pan, zoom, resize)."""
        if self.overlay.image is not None and \
                self._image_key != view_key(self.map_canvas.mapSettings()):
            self._set_image(None)

    def _on_render_starting(self):
        # The canvas redraws (new extent, style, visibility...): redraw our image too.
        # An image for the same view stays up until the new one is ready – no flicker.
        self._drop_stale_image()
        self._render()

    def _on_selection_changed(self, *args):
        self._set_image(None)  # it shows the previous selection
        self._timer.start()

    def _selection_settled(self):
        self._told = False
        self._render()
        self._announce()

    # ----------------------------------------------------------------- signals

    def _connect(self):
        if self._connections:
            return
        canvas = self.map_canvas
        pairs = [
            (canvas.renderStarting, self._on_render_starting),
            (canvas.extentsChanged, self._drop_stale_image),
            (self.iface.currentLayerChanged, self._on_selection_changed),
        ]
        view = self.iface.layerTreeView()
        model = view.selectionModel() if view is not None else None
        if model is not None:
            pairs.append((model.selectionChanged, self._on_selection_changed))
        for signal, slot in pairs:
            signal.connect(slot)
        self._connections = pairs

    def _disconnect(self):
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._connections = []

    # --------------------------------------------------------------- map tool

    def activate(self):
        super().activate()
        self._connect()
        self._dragging = False
        self._told = False
        self._side_cursor = None
        self.overlay.set_swipe(None)
        self.overlay.show()
        self._render()
        self._announce()

    def deactivate(self):
        self._shutdown()
        super().deactivate()

    def cleanup(self):
        """Called when the plugin is unloaded."""
        self._shutdown()
        scene = self.map_canvas.scene()
        if scene is not None and self.overlay.scene() is scene:
            scene.removeItem(self.overlay)

    def _shutdown(self):
        self._disconnect()
        self._timer.stop()
        self._stop_job()
        self._dragging = False
        self.overlay.set_swipe(None)
        self._set_image(None)
        self.overlay.hide()

    def set_keep(self, keep):
        """Keep the swipe on the map after the mouse button is released."""
        self.keep = bool(keep)
        if not self.keep and not self._dragging:
            self.overlay.set_swipe(None)

    def _announce(self):
        """Tell in the status bar which layers a drag will swipe."""
        swiped, _rest = self._split_layers(self.map_canvas.mapSettings())
        if not swiped:
            return
        names = ", ".join(layer.name() for layer in swiped[:4])
        if len(swiped) > 4:
            names += tr(" and {} more").format(len(swiped) - 4)
        try:
            self.iface.statusBarIface().showMessage(
                tr("Pro Swipe: {} – drag from an edge of the map to peel it back.").format(names),
                6000)
        except (AttributeError, RuntimeError):
            pass

    def _tell(self, message):
        self.iface.messageBar().pushMessage(
            PLUGIN_NAME, message, level=Qgis.MessageLevel.Info, duration=6)

    def _side_at(self, pos):
        """The side a press at ``pos`` swipes from; a kept swipe edge can be grabbed."""
        overlay = self.overlay
        if overlay.side is not None:
            if overlay.side in (TOP, BOTTOM):
                distance = abs(pos.y() - overlay.at.y())
            else:
                distance = abs(pos.x() - overlay.at.x())
            if distance <= self.GRAB_PX:
                return overlay.side
        size = self.map_canvas.mapSettings().outputSize()
        return zone(pos.x(), pos.y(), size.width(), size.height())

    def _show_cursor(self, side):
        if side == self._side_cursor:
            return
        if side not in self._cursors:
            self._cursors[side] = swipe_cursor(side, self.map_canvas.devicePixelRatioF())
        self._side_cursor = side
        self.setCursor(self._cursors[side])

    def canvasPressEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        swiped, _rest = self._split_layers(self.map_canvas.mapSettings())
        if not swiped:
            if not self._told:
                self._told = True
                self._tell(tr("Select the layer to swipe in the Layers panel – "
                              "it must be switched on and inside the map view."))
            return
        side = self._side_at(e.pos())
        self._dragging = True
        self._show_cursor(side)
        self.overlay.set_swipe(side, e.pos())

    def canvasMoveEvent(self, e):  # noqa: N802
        if self._dragging:
            self.overlay.set_swipe(self.overlay.side, e.pos())
        else:
            self._show_cursor(self._side_at(e.pos()))

    def canvasReleaseEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton or not self._dragging:
            return
        self._dragging = False
        if not self.keep:
            self.overlay.set_swipe(None)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape and self.overlay.side is not None:
            self._dragging = False
            self.overlay.set_swipe(None)
            return
        e.ignore()  # let the canvas handle space bar panning, arrow keys...
