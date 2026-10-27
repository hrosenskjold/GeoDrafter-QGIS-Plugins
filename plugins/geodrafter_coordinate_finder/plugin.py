# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Coordinate Finder and Converter – connects the panel, the pick tool and the readout."""

import os

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsCoordinateReferenceSystem, QgsSettings

try:  # Qt6 / QGIS 4
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 / QGIS 3.40
    from qgis.PyQt.QtWidgets import QAction

from .geodrafter_common import PUBLISH_AVAILABLE, share_as_web_map, show_about
from .geodrafter_common.toolbar import add_to_menu, add_to_toolbar, remove_actions

PLUGIN_NAME = "GeoDrafter Coordinate Finder and Converter"
SETTING_CRS = "geodrafter/coordinate_finder/chosen_crs"
SETTING_COPY = "geodrafter/coordinate_finder/copy_on_pick"


def tr(text):
    return QCoreApplication.translate("GeoDrafterCoordinateFinder", text)


class GeoDrafterCoordinateFinderPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.actions = []
        self.panel_action = None
        self.panel = None
        self.tool = None
        self.marker = None
        self.readout = None
        self.position = None   # last shown position, map CRS

    # -- QGIS plugin API -------------------------------------------------------------

    def initGui(self):  # noqa: N802
        window = self.iface.mainWindow()
        icon = QIcon(os.path.join(self.plugin_dir, "icon.svg"))
        self.panel_action = QAction(icon, tr("Coordinate Finder"), window)
        self.panel_action.setObjectName("GeoDrafterCoordinateFinderAction")
        self.panel_action.setCheckable(True)
        self.panel_action.setToolTip(tr(
            "GeoDrafter Coordinate Finder and Converter – read positions in any CRS, DMS, UTM and MGRS, "
            "or go to a typed one"))
        self.panel_action.toggled.connect(self.show_panel)
        about = QAction(tr("About GeoDrafter Coordinate Finder and Converter"), window)
        about.triggered.connect(lambda: show_about(window, self.plugin_dir))
        batch_action = QAction(tr("Coordinates for points and vertices…"), window)
        batch_action.triggered.connect(self.open_batch)
        entries = [self.panel_action, batch_action]
        if PUBLISH_AVAILABLE:
            share = QAction(tr("Share as web map…"), window)
            share.triggered.connect(lambda: share_as_web_map(self.iface, PLUGIN_NAME))
            entries.append(share)
        entries.append(about)
        add_to_toolbar(self.iface, self.panel_action)
        for action in entries:
            add_to_menu(self.iface, action)
            self.actions.append(action)

    def unload(self):
        canvas = self.iface.mapCanvas()
        if self.tool is not None:
            if canvas.mapTool() is self.tool:
                canvas.unsetMapTool(self.tool)
            self.tool = None
        if self.marker is not None:
            self.marker.remove()
            self.marker = None
        if self.panel is not None:
            try:
                canvas.destinationCrsChanged.disconnect(self._map_crs_changed)
            except (TypeError, RuntimeError):
                pass
            self.iface.removeDockWidget(self.panel)
            self.panel.deleteLater()
            self.panel = None
        remove_actions(self.iface, self.actions)
        self.actions = []

    # -- building on first use --------------------------------------------------------------

    def _build(self):
        from .panel import CoordinatesPanel
        from .picktool import PickTool, PositionMarker
        from .readout import Readout

        canvas = self.iface.mapCanvas()
        settings = QgsSettings()
        chosen = QgsCoordinateReferenceSystem(settings.value(SETTING_CRS, "EPSG:4326", type=str))
        if not chosen.isValid():
            chosen = QgsCoordinateReferenceSystem("EPSG:4326")
        self.readout = Readout(canvas.mapSettings().destinationCrs(), chosen)

        self.panel = CoordinatesPanel(self.readout.keys_and_labels(), self.iface.mainWindow())
        self.panel.crs_picker.setCrs(chosen)
        self.panel.crs_picker.crsChanged.connect(self._chosen_crs_changed)
        index = self.panel.copy_on_pick.findData(settings.value(SETTING_COPY, "", type=str))
        self.panel.copy_on_pick.setCurrentIndex(max(index, 0))
        self.panel.copy_on_pick.currentIndexChanged.connect(
            lambda _i: QgsSettings().setValue(SETTING_COPY, self.panel.copy_on_pick.currentData()))
        self.panel.pick_button.toggled.connect(self.set_picking)
        self.panel.follow_button.toggled.connect(self._follow_toggled)
        self.panel.go_requested.connect(self.go_to)
        self.panel.batch_requested.connect(self.open_batch)
        self.panel.visibilityChanged.connect(self._panel_visibility)

        self.tool = PickTool(canvas)
        self.tool.hovered.connect(self._hovered)
        self.tool.picked.connect(self._picked)
        self.tool.finished.connect(self._tool_finished)
        self.marker = PositionMarker(canvas)
        canvas.destinationCrsChanged.connect(self._map_crs_changed)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.panel)

    # -- panel and tool state --------------------------------------------------------------

    def show_panel(self, visible=True):
        if self.panel is None:
            if not visible:
                return
            self._build()
        self.panel.setUserVisible(bool(visible))
        if not visible:
            self.set_picking(False)

    def _panel_visibility(self, visible):
        if self.panel_action.isChecked() != visible:
            self.panel_action.blockSignals(True)
            self.panel_action.setChecked(visible)
            self.panel_action.blockSignals(False)
        if not visible:
            self.set_picking(False)

    def set_picking(self, on):
        canvas = self.iface.mapCanvas()
        if on and canvas.mapTool() is not self.tool:
            canvas.setMapTool(self.tool)
        elif not on and self.tool is not None and canvas.mapTool() is self.tool:
            canvas.unsetMapTool(self.tool)
        self._set_button(self.panel.pick_button, on)

    def _tool_finished(self):
        if self.panel is not None:
            self._set_button(self.panel.pick_button, False)
            self._set_button(self.panel.follow_button, False)

    def _follow_toggled(self, on):
        if on:
            self.set_picking(True)   # following needs the tool to receive mouse moves

    @staticmethod
    def _set_button(button, on):
        if button.isChecked() != bool(on):
            button.blockSignals(True)
            button.setChecked(bool(on))
            button.blockSignals(False)

    # -- positions ---------------------------------------------------------------------

    def show_position(self, point):
        self.position = point
        self.panel.show_rows(self.readout.rows(point))

    def _hovered(self, point):
        if self.panel.follow_button.isChecked():
            self.show_position(point)

    def _picked(self, point):
        self._set_button(self.panel.follow_button, False)
        self.marker.show_at(point)
        self.show_position(point)
        key = self.panel.copy_on_pick.currentData()
        if key:
            copied = self.panel.copy_key(key)
            if copied:
                self.iface.messageBar().pushInfo(PLUGIN_NAME, tr("Copied {}").format(copied))

    def open_batch(self):
        """Dialog for many points/vertices; uses the CRS chosen in the panel (remembered setting)."""
        from .batch_dialog import open_dialog

        if self.readout is not None:
            chosen = self.readout.chosen_crs
        else:
            chosen = QgsCoordinateReferenceSystem(QgsSettings().value(SETTING_CRS, "EPSG:4326", type=str))
            if not chosen.isValid():
                chosen = QgsCoordinateReferenceSystem("EPSG:4326")
        return open_dialog(self.iface, chosen, PLUGIN_NAME)

    def go_to(self, text):
        from .readout import locate

        canvas = self.iface.mapCanvas()
        try:
            point, how = locate(text, self.readout.chosen_crs, canvas.mapSettings().destinationCrs())
        except ValueError as e:
            self.iface.messageBar().pushWarning(PLUGIN_NAME, tr(str(e)))
            return None
        self._set_button(self.panel.follow_button, False)
        canvas.setCenter(point)
        canvas.refresh()
        self.marker.show_at(point)
        self.show_position(point)
        self.iface.messageBar().pushInfo(PLUGIN_NAME, tr("{} – read as {}").format(text.strip(), how))
        return point

    def _chosen_crs_changed(self, crs):
        self.readout.chosen_crs = crs
        QgsSettings().setValue(SETTING_CRS, crs.authid() or crs.toWkt())
        if self.position is not None:
            self.show_position(self.position)

    def _map_crs_changed(self):
        self.readout.map_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.position = None
        self.marker.hide()
