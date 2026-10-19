# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Map tool that reports where the mouse is and where the user clicks."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsApplication, QgsPointXY
from qgis.gui import QgsMapTool, QgsVertexMarker


class PositionMarker:
    """A ring on the canvas at the last picked or visited position."""

    def __init__(self, canvas):
        self._canvas = canvas
        self._item = QgsVertexMarker(canvas)
        self._item.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
        self._item.setIconSize(16)
        self._item.setPenWidth(3)
        self._item.setColor(QColor(220, 38, 38))
        self._item.hide()

    def show_at(self, point):
        self._item.setCenter(point)
        self._item.show()

    def hide(self):
        self._item.hide()

    def is_shown(self):
        return self._item.isVisible()

    def remove(self):
        self._item.hide()
        scene = self._canvas.scene()
        if scene is not None:
            scene.removeItem(self._item)


class PickTool(QgsMapTool):
    """Left click = pick a position, mouse move = hover, right click or Esc = done."""

    hovered = pyqtSignal(QgsPointXY)
    picked = pyqtSignal(QgsPointXY)
    finished = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.setCursor(QgsApplication.getThemeCursor(QgsApplication.Cursor.CrossHair))

    def _map_point(self, event):
        return QgsPointXY(self.toMapCoordinates(event.pos()))

    def canvasMoveEvent(self, event):  # noqa: N802
        self.hovered.emit(self._map_point(event))

    def canvasReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self._map_point(event))
        elif event.button() == Qt.MouseButton.RightButton:
            self.canvas().unsetMapTool(self)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.canvas().unsetMapTool(self)
            event.accept()
        else:
            event.ignore()

    def deactivate(self):
        super().deactivate()
        self.finished.emit()
