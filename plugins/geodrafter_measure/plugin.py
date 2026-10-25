# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Measure – plugin wiring."""

import os

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import QgsProject, QgsVectorFileWriter

try:  # Qt6 / QGIS 4
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 / QGIS 3.40
    from qgis.PyQt.QtWidgets import QAction

from .geodrafter_common import PUBLISH_AVAILABLE, share_as_web_map, show_about
from .geodrafter_common.toolbar import MENU_NAME, add_to_toolbar, remove_actions

PLUGIN_NAME = "GeoDrafter Measure"


def tr(text):
    return QCoreApplication.translate("GeoDrafterMeasure", text)


def export_layers(layers, path, transform_context):
    """Write layers as tables of one GeoPackage. Returns list of error strings."""
    errors = []
    first = True
    for layer in layers:
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = layer.name().replace(" ", "_").lower()
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile if first
            else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer)
        res = QgsVectorFileWriter.writeAsVectorFormatV3(layer, path, transform_context, opts)
        code = res[0] if isinstance(res, tuple) else res
        code = getattr(code, "value", code)
        if int(code) != 0:
            errors.append("%s: %s" % (layer.name(), res[1] if isinstance(res, tuple) else code))
        first = False
    return errors


class GeoDrafterMeasurePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.actions = []
        self.action = None
        self.dock = None
        self.tool = None
        self.last = None

    def initGui(self):  # noqa: N802
        icon = QIcon(os.path.join(self.plugin_dir, "icon.svg"))
        self.action = QAction(icon, tr("Measure"), self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setObjectName("GeoDrafterMeasureAction")
        self.action.setToolTip(tr(
            "GeoDrafter Measure – geodesic distance, area and radius.\n"
            "Click to add points; right click, double click or Enter finishes; Esc clears.\n"
            "Feature mode: click a line or polygon to get its length or area."))
        self.action.triggered.connect(self.run)
        share = QAction(tr("Share as web map…"), self.iface.mainWindow())
        share.triggered.connect(self.share)
        about = QAction(tr("About GeoDrafter Measure"), self.iface.mainWindow())
        about.triggered.connect(lambda: show_about(self.iface.mainWindow(), self.plugin_dir))
        add_to_toolbar(self.iface, self.action)
        for action in (self.action, share, about) if PUBLISH_AVAILABLE else (self.action, about):
            self.iface.addPluginToMenu(MENU_NAME, action)
            self.actions.append(action)

    def _ensure(self):
        if self.tool is not None:
            return
        from .measure import MeasureDock, MeasureTool

        canvas = self.iface.mapCanvas()
        self.tool = MeasureTool(canvas)
        self.tool.setAction(self.action)
        self.tool.changed.connect(self.update_result)
        self.tool.finished.connect(self.on_finished)
        self.dock = MeasureDock(self.iface.mainWindow())
        self.dock.modeChanged.connect(self.tool.set_mode)
        self.dock.unit_combo.currentIndexChanged.connect(lambda _i: self.update_result())
        self.dock.clear_button.clicked.connect(self.tool.clear)
        self.dock.export_button.clicked.connect(self.export)
        self.dock.share_button.clicked.connect(self.share)
        self.dock.share_button.setVisible(PUBLISH_AVAILABLE)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.last = None

    def run(self, checked=True):
        self._ensure()
        canvas = self.iface.mapCanvas()
        if canvas.mapTool() is self.tool:
            canvas.unsetMapTool(self.tool)
            return
        canvas.setMapTool(self.tool)
        self.dock.show()
        self.dock.raise_()
        self.update_result()

    def _describe(self, measurement):
        from .measure import describe
        lu, au, imperial = self.dock.units_choice()
        return describe(measurement.mode, measurement.values(self.tool.engine), lu, au, imperial)

    def update_result(self):
        if self.tool is None or self.dock is None:
            return
        from .measure import FEATURE, describe
        if self.tool.mode == FEATURE:
            lu, au, imperial = self.dock.units_choice()
            if self.tool.picked:
                lines = describe(FEATURE, self.tool.picked_summary(), lu, au, imperial)
            else:
                lines = [tr("Click a line or polygon to measure it."),
                         tr("Shift+click adds more features to a total.")]
            self.dock.show_lines(lines)
            self.dock.ellipsoid_label.setText(
                tr("Geodesic, on ellipsoid {}").format(self.tool.engine.ellipsoid))
            return
        m = self.tool.preview()
        if m.points:
            lines = self._describe(m)
        elif self.last is not None:
            lines = [tr("Last measurement:")] + self._describe(self.last)
        else:
            lines = [tr("Click on the map to start measuring.")]
        self.dock.show_lines(lines)
        self.dock.ellipsoid_label.setText(
            tr("Geodesic, on ellipsoid {}").format(self.tool.engine.ellipsoid))

    def on_finished(self, measurement):
        from .measure import add_to_layer, measurements_layer
        self.last = measurement
        if self.dock.keep_button.isChecked():
            layer = measurements_layer(QgsProject.instance(), self.tool.engine.crs, measurement.mode)
            add_to_layer(layer, measurement, self.tool.engine, " · ".join(
                line.strip() for line in self._describe(measurement) if not line.startswith("  ")))
        self.tool.clear()
        self.update_result()

    def _measurement_layers(self):
        from .measure import AREA_LAYER_NAME, LINE_LAYER_NAME
        project = QgsProject.instance()
        return [lyr for name in (LINE_LAYER_NAME, AREA_LAYER_NAME)
                for lyr in project.mapLayersByName(name) if lyr.featureCount()]

    def export(self):
        layers = self._measurement_layers()
        if not layers:
            self.iface.messageBar().pushInfo(
                PLUGIN_NAME, tr("Nothing to export yet – finish a measurement first."))
            return
        path, _f = QFileDialog.getSaveFileName(
            self.iface.mainWindow(), tr("Export measurements"),
            os.path.join(os.path.expanduser("~"), "geodrafter_measurements.gpkg"), "GeoPackage (*.gpkg)")
        if not path:
            return
        if not path.lower().endswith(".gpkg"):
            path += ".gpkg"
        errors = export_layers(layers, path, QgsProject.instance().transformContext())
        if errors:
            self.iface.messageBar().pushWarning(PLUGIN_NAME, "; ".join(errors))
        else:
            self.iface.messageBar().pushSuccess(PLUGIN_NAME, tr("Saved {}").format(path))

    def share(self):
        share_as_web_map(self.iface, PLUGIN_NAME)

    def unload(self):
        if self.tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() is self.tool:
                canvas.unsetMapTool(self.tool)
            self.tool.cleanup()
            self.tool = None
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        remove_actions(self.iface, self.actions)
        self.actions = []
