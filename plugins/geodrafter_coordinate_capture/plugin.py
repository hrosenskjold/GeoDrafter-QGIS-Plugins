# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2020 Stefanos Natsis (original Coordinate Capture plugin)
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Coordinate Capture – plugin wiring."""

import os

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsCoordinateReferenceSystem, QgsSettings

try:  # Qt6 / QGIS 4
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 / QGIS 3.40
    from qgis.PyQt.QtWidgets import QAction

from .geodrafter_common import PUBLISH_AVAILABLE, share_as_web_map, show_about
from .geodrafter_common.toolbar import MENU_NAME, add_to_toolbar, remove_actions

PLUGIN_NAME = "GeoDrafter Coordinate Capture"
KEY_CRS = "geodrafter/coordinate_capture/crs"
KEY_COPY = "geodrafter/coordinate_capture/copy_on_click"


def tr(text):
    return QCoreApplication.translate("GeoDrafterCoordinateCapture", text)


class GeoDrafterCoordinateCapturePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.actions = []
        self.action = None
        self.dock = None
        self.tool = None
        self.computer = None
        self.last_point = None

    def initGui(self):  # noqa: N802
        icon = QIcon(os.path.join(self.plugin_dir, "icon.svg"))
        self.action = QAction(icon, tr("Coordinate Capture"), self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setObjectName("GeoDrafterCoordinateCaptureAction")
        self.action.setToolTip(
            tr("GeoDrafter Coordinate Capture – coordinates in any CRS, DMS, UTM and MGRS"))
        self.action.triggered.connect(self.toggle_dock)
        share = QAction(tr("Share as web map…"), self.iface.mainWindow())
        share.triggered.connect(lambda: share_as_web_map(self.iface, PLUGIN_NAME))
        about = QAction(tr("About GeoDrafter Coordinate Capture"), self.iface.mainWindow())
        about.triggered.connect(lambda: show_about(self.iface.mainWindow(), self.plugin_dir))
        add_to_toolbar(self.iface, self.action)
        for action in (self.action, share, about) if PUBLISH_AVAILABLE else (self.action, about):
            self.iface.addPluginToMenu(MENU_NAME, action)
            self.actions.append(action)

    # -- setup on first use ----------------------------------------------------

    def _ensure_dock(self):
        if self.dock is not None:
            return
        from .capture import CaptureDock, CaptureMapTool, CoordinateComputer

        canvas = self.iface.mapCanvas()
        self.computer = CoordinateComputer()
        self.dock = CaptureDock(self.iface.mainWindow())
        self.tool = CaptureMapTool(canvas)
        self.tool.mouseMoved.connect(self.on_move)
        self.tool.mouseClicked.connect(self.on_click)
        self.tool.deactivated.connect(self._tool_deactivated)
        self.dock.capture_button.toggled.connect(self.set_capturing)
        self.dock.goto_button.clicked.connect(self.go_to)
        self.dock.visibilityChanged.connect(self.action.setChecked)

        settings = QgsSettings()
        crs = QgsCoordinateReferenceSystem(settings.value(KEY_CRS, "EPSG:4326", type=str))
        self.dock.crs_widget.setCrs(crs if crs.isValid() else QgsCoordinateReferenceSystem("EPSG:4326"))
        self.computer.user_crs = self.dock.crs_widget.crs()
        self.dock.crs_widget.crsChanged.connect(self.on_user_crs)
        idx = self.dock.copy_on_click.findData(settings.value(KEY_COPY, "", type=str))
        self.dock.copy_on_click.setCurrentIndex(max(idx, 0))
        self.dock.copy_on_click.currentIndexChanged.connect(
            lambda _i: QgsSettings().setValue(KEY_COPY, self.dock.copy_on_click.currentData()))

        canvas.destinationCrsChanged.connect(self.on_map_crs)
        self.on_map_crs()
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

    # -- slots ---------------------------------------------------------------------

    def toggle_dock(self, checked=True):
        self._ensure_dock()
        self.dock.setVisible(bool(checked))
        if checked:
            self.dock.raise_()
        else:
            self.set_capturing(False)

    def set_capturing(self, on):
        canvas = self.iface.mapCanvas()
        if on and canvas.mapTool() is not self.tool:
            canvas.setMapTool(self.tool)
        elif not on and canvas.mapTool() is self.tool:
            canvas.unsetMapTool(self.tool)
        if self.dock.capture_button.isChecked() != bool(on):
            self.dock.capture_button.setChecked(bool(on))

    def _tool_deactivated(self):
        # Another map tool took over: only reflect it on the button
        self.dock.capture_button.blockSignals(True)
        self.dock.capture_button.setChecked(False)
        self.dock.capture_button.blockSignals(False)

    def on_map_crs(self):
        self.computer.map_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.last_point = None

    def on_user_crs(self, crs):
        self.computer.user_crs = crs
        QgsSettings().setValue(KEY_CRS, crs.authid() or crs.toWkt())
        if self.last_point is not None:
            self.show(self.last_point)

    def show(self, point):
        self.last_point = point
        self.dock.set_values(self.computer.compute(point))

    def go_to(self):
        from .capture import resolve_typed

        text = self.dock.goto_edit.text()
        canvas = self.iface.mapCanvas()
        try:
            point, how = resolve_typed(
                text, self.computer.user_crs, canvas.mapSettings().destinationCrs())
        except ValueError as e:
            self.iface.messageBar().pushWarning(PLUGIN_NAME, tr(str(e)))
            return None
        self.dock.track_button.setChecked(False)
        canvas.setCenter(point)
        canvas.refresh()
        self.tool.mark(point)
        self.show(point)
        self.iface.messageBar().pushInfo(
            PLUGIN_NAME, tr("Went to {} – read as {}").format(text.strip(), how))
        return point

    def on_move(self, point):
        if self.dock.track_button.isChecked():
            self.show(point)

    def on_click(self, point):
        self.dock.track_button.setChecked(False)
        self.show(point)
        key = self.dock.copy_on_click.currentData()
        if key:
            text = self.dock.copy(key)
            if text:
                self.iface.messageBar().pushInfo(PLUGIN_NAME, tr("Copied: {}").format(text))

    def unload(self):
        if self.tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() is self.tool:
                canvas.unsetMapTool(self.tool)
            try:
                canvas.destinationCrsChanged.disconnect(self.on_map_crs)
            except (TypeError, RuntimeError):
                pass
            self.tool.cleanup()
            self.tool = None
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        remove_actions(self.iface, self.actions)
        self.actions = []
