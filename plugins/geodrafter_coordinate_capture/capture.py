# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2020 Stefanos Natsis (original Coordinate Capture plugin)
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Map tool and dock widget for GeoDrafter Coordinate Capture.

Based on "Coordinate Capture" by Stefanos Natsis
(https://github.com/uclaros/qgis_coordinate_capture, GPL), itself a Python port
of the former QGIS core plugin. Rewritten for QGIS 4 (Qt6) with WGS84
DD/DMS/DDM, UTM and MGRS output, copy buttons and copy-on-click.
"""

import math

from qgis.PyQt.QtCore import Qt, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QGuiApplication
from qgis.PyQt.QtWidgets import (
    QComboBox, QDockWidget, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QWidget,
)
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsCsException, QgsPointXY, QgsProject,
)
from qgis.gui import QgsMapToolEmitPoint, QgsProjectionSelectionWidget, QgsVertexMarker

from . import coordfmt, coordparse

CONVERTER_URL = "https://geodrafter.com/coordinate-converter/"
WGS84 = "EPSG:4326"


class CaptureMapTool(QgsMapToolEmitPoint):
    """Emits the map position on mouse move and on left click; right click stops."""

    mouseMoved = pyqtSignal(QgsPointXY)
    mouseClicked = pyqtSignal(QgsPointXY)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.marker = QgsVertexMarker(canvas)
        self.marker.setIconType(QgsVertexMarker.IconType.ICON_CROSS)
        self.marker.setColor(Qt.GlobalColor.red)
        self.marker.setIconSize(14)
        self.marker.setPenWidth(2)
        self.marker.hide()
        self.setCursor(QgsApplication.getThemeCursor(QgsApplication.Cursor.CrossHair))

    def canvasMoveEvent(self, e):  # noqa: N802
        self.mouseMoved.emit(QgsPointXY(self.toMapCoordinates(e.pos())))

    def canvasPressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            point = QgsPointXY(self.toMapCoordinates(e.pos()))
            self.mark(point)
            self.mouseClicked.emit(point)
        elif e.button() == Qt.MouseButton.RightButton:
            self.canvas().unsetMapTool(self)

    def mark(self, point):
        self.marker.setCenter(point)
        self.marker.show()

    def deactivate(self):
        self.marker.hide()
        super().deactivate()

    def cleanup(self):
        self.marker.hide()
        scene = self.canvas().scene()
        if scene is not None:
            scene.removeItem(self.marker)


def _copy_icon():
    return QgsApplication.getThemeIcon("/mActionEditCopy.svg")


class CaptureDock(QDockWidget):
    """The dock: one read-only field per format, each with a copy button."""

    ROWS = [("map", "Map CRS"), ("user", "Selected CRS")] + [
        (key, label) for key, label, _ in coordfmt.format_all(0, 0)]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GeoDrafterCoordinateCaptureDock")
        self.setWindowTitle(self.tr("GeoDrafter Coordinate Capture"))
        body = QWidget(self)
        grid = QGridLayout(body)
        self.setWidget(body)

        buttons = QHBoxLayout()
        self.capture_button = QPushButton(self.tr("Start capture"), body)
        self.capture_button.setCheckable(True)
        self.capture_button.setToolTip(
            self.tr("Click on the map to capture a coordinate. Right click stops."))
        self.track_button = QPushButton(self.tr("Track mouse"), body)
        self.track_button.setCheckable(True)
        self.track_button.setToolTip(
            self.tr("Update while the mouse moves. A click on the map stops tracking."))
        buttons.addWidget(self.capture_button)
        buttons.addWidget(self.track_button)
        grid.addLayout(buttons, 0, 0, 1, 2)

        goto = QHBoxLayout()
        self.goto_edit = QLineEdit(body)
        self.goto_edit.setObjectName("goto_edit")
        self.goto_edit.setClearButtonEnabled(True)
        self.goto_edit.setPlaceholderText(self.tr("e.g. 57.0488, 9.9217 or 32V NJ 52000 20000"))
        self.goto_edit.setToolTip(self.tr(
            "Type a coordinate and press Enter to go there:\n"
            "• two numbers in the Selected CRS (lat, lon if it is geographic)\n"
            "• 57.0488N 9.9217E, 57°02′53″N 9°55′06″E, N57 02.890 E9 55.102\n"
            "• UTM: 32V 552000 6320000 (zone and latitude band)\n"
            "• MGRS: 32V NJ 52000 20000"))
        self.goto_button = QPushButton(self.tr("Go"), body)
        self.goto_button.setToolTip(self.tr("Centre the map on the coordinate and mark it"))
        self.goto_edit.returnPressed.connect(self.goto_button.click)
        goto.addWidget(self.goto_edit)
        goto.addWidget(self.goto_button)
        grid.addWidget(QLabel(self.tr("Go to"), body), 1, 0)
        grid.addLayout(goto, 1, 1)

        self.crs_widget = QgsProjectionSelectionWidget(body)
        self.crs_widget.setToolTip(self.tr("CRS for the 'Selected CRS' row and for typed numbers"))
        grid.addWidget(QLabel(self.tr("Selected CRS"), body), 2, 0)
        grid.addWidget(self.crs_widget, 2, 1)

        self.fields = {}
        self.labels = {}
        for i, (key, label) in enumerate(self.ROWS, start=3):
            lab = QLabel(self.tr(label), body)
            edit = QLineEdit(body)
            edit.setReadOnly(True)
            edit.setObjectName("coord_" + key)
            act = edit.addAction(_copy_icon(), QLineEdit.ActionPosition.TrailingPosition)
            act.setToolTip(self.tr("Copy"))
            act.triggered.connect(lambda _=False, k=key: self.copy(k))
            grid.addWidget(lab, i, 0)
            grid.addWidget(edit, i, 1)
            self.fields[key] = edit
            self.labels[key] = lab

        row = len(self.ROWS) + 3
        grid.addWidget(QLabel(self.tr("Copy on click"), body), row, 0)
        self.copy_on_click = QComboBox(body)
        self.copy_on_click.addItem(self.tr("Nothing"), "")
        for key, label in self.ROWS:
            self.copy_on_click.addItem(self.tr(label), key)
        grid.addWidget(self.copy_on_click, row, 1)

        bottom = QHBoxLayout()
        self.copy_all_button = QPushButton(self.tr("Copy all"), body)
        self.copy_all_button.clicked.connect(self.copy_all)
        self.converter_button = QPushButton(self.tr("Coordinate converter…"), body)
        self.converter_button.setToolTip(CONVERTER_URL)
        self.converter_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(CONVERTER_URL)))
        bottom.addWidget(self.copy_all_button)
        bottom.addWidget(self.converter_button)
        grid.addLayout(bottom, row + 1, 0, 1, 2)
        grid.setRowStretch(row + 2, 1)

    def set_values(self, values):
        for key, text in values.items():
            if key in self.fields:
                self.fields[key].setText(text or "")

    def text_of(self, key):
        return self.fields[key].text()

    def copy(self, key):
        text = self.text_of(key)
        if text:
            QGuiApplication.clipboard().setText(text)
        return text

    def copy_all(self):
        lines = ["%s: %s" % (self.labels[k].text(), self.fields[k].text())
                 for k, _ in self.ROWS if self.fields[k].text()]
        if lines:
            QGuiApplication.clipboard().setText("\n".join(lines))
        return "\n".join(lines)


class CoordinateComputer:
    """Turns a map-canvas point into all display strings (testable without a dock)."""

    def __init__(self):
        self.map_crs = QgsCoordinateReferenceSystem(WGS84)
        self.user_crs = QgsCoordinateReferenceSystem(WGS84)
        self.wgs84 = QgsCoordinateReferenceSystem(WGS84)

    @staticmethod
    def _precision(crs):
        return 6 if crs.isGeographic() else 3

    @staticmethod
    def _xy(point, digits, crs):
        # Geographic CRS are shown as "lat, lon" like the other formats
        if crs.isGeographic():
            return "%.*f, %.*f" % (digits, point.y(), digits, point.x())
        return "%.*f, %.*f" % (digits, point.x(), digits, point.y())

    def compute(self, point):
        project = QgsProject.instance()
        out = {"map": "%s  (%s)" % (
            self._xy(point, self._precision(self.map_crs), self.map_crs), self.map_crs.authid())}
        try:
            up = QgsCoordinateTransform(self.map_crs, self.user_crs, project).transform(point)
            out["user"] = "%s  (%s)" % (
                self._xy(up, self._precision(self.user_crs), self.user_crs), self.user_crs.authid())
        except QgsCsException:
            out["user"] = ""
        try:
            ll = QgsCoordinateTransform(self.map_crs, self.wgs84, project).transform(point)
        except QgsCsException:
            ll = None
        for key, _label, text in coordfmt.format_all(ll.y(), ll.x()) if ll else []:
            out[key] = text or ""
        if ll is None:
            for key, _label, _t in coordfmt.format_all(0, 0):
                out[key] = ""
        return out


def resolve_typed(text, user_crs, map_crs):
    """Typed coordinate -> (map-CRS QgsPointXY, how it was read). Raises ValueError."""
    parsed = coordparse.parse(text)
    kind = parsed["kind"]
    if kind == "wgs84":
        src, x, y = QgsCoordinateReferenceSystem(WGS84), parsed["lon"], parsed["lat"]
        how = "WGS84"
    elif kind == "utm":
        epsg = (32600 if parsed["north"] else 32700) + parsed["zone"]
        src = QgsCoordinateReferenceSystem("EPSG:%d" % epsg)
        x, y = parsed["easting"], parsed["northing"]
        how = "UTM %d%s (EPSG:%d)" % (parsed["zone"], "N" if parsed["north"] else "S", epsg)
    else:
        a, b = parsed["a"], parsed["b"]
        if user_crs.isGeographic():
            src, x, y, how = user_crs, b, a, user_crs.authid()
        elif coordparse.looks_like_lat_lon(a, b):
            # Small numbers in a projected CRS are almost surely lat, lon
            src, x, y, how = QgsCoordinateReferenceSystem(WGS84), b, a, "WGS84 (lat, lon)"
        else:
            src, x, y, how = user_crs, a, b, user_crs.authid()
        if src.isGeographic() and not (-90 <= y <= 90 and -180 <= x <= 180):
            raise ValueError("Latitude must be between -90 and 90 (order: lat, lon)")
    if not src.isValid():
        raise ValueError("Unknown CRS")
    try:
        point = QgsCoordinateTransform(src, map_crs, QgsProject.instance()).transform(QgsPointXY(x, y))
    except QgsCsException:
        raise ValueError("The coordinate cannot be shown in the map CRS")
    if not (math.isfinite(point.x()) and math.isfinite(point.y())):
        raise ValueError("The coordinate cannot be shown in the map CRS")
    return point, how
