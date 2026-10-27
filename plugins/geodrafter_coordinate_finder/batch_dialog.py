# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Dialog: coordinates for all (or the selected) points or vertices of a layer."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QGuiApplication
from qgis.PyQt.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel,
    QRadioButton, QVBoxLayout,
)
from qgis.core import Qgis, QgsProject
from qgis.gui import QgsMapLayerComboBox

from . import batch

WRITE, VERTICES, TABLE = "write", "vertices", "table"


def _layer_filter():
    try:
        return Qgis.LayerFilter.PointLayer | Qgis.LayerFilter.LineLayer | Qgis.LayerFilter.PolygonLayer
    except AttributeError:  # older QGIS
        from qgis.core import QgsMapLayerProxyModel
        return QgsMapLayerProxyModel.PointLayer | QgsMapLayerProxyModel.LineLayer | \
            QgsMapLayerProxyModel.PolygonLayer


class BatchDialog(QDialog):
    """Pick a layer, formats and an output; ``run()`` does the work and returns a message."""

    def __init__(self, chosen_crs, layer=None, parent=None):
        super().__init__(parent)
        self.setObjectName("GeoDrafterCoordinateFinderBatch")
        self.setWindowTitle(self.tr("Coordinates for points and vertices"))
        self.chosen_crs = chosen_crs
        self.result_layer = None
        outer = QVBoxLayout(self)

        form = QFormLayout()
        self.layer_box = QgsMapLayerComboBox(self)
        self.layer_box.setFilters(_layer_filter())
        if layer is not None:
            self.layer_box.setLayer(layer)
        form.addRow(self.tr("Layer"), self.layer_box)
        self.selected_only = QCheckBox(self.tr("Selected features only"), self)
        form.addRow("", self.selected_only)
        outer.addLayout(form)

        formats = QGroupBox(self.tr("Formats"), self)
        fl = QVBoxLayout(formats)
        self.format_boxes = {}
        for key, label in batch.FORMATS.items():
            text = self.tr(label)
            if key == "chosen":
                text = "%s – %s" % (self.tr("Chosen CRS"), chosen_crs.authid() or chosen_crs.description())
            box = QCheckBox(text, formats)
            box.setChecked(key in batch.DEFAULT_FORMATS)
            fl.addWidget(box)
            self.format_boxes[key] = box
        outer.addWidget(formats)

        out = QGroupBox(self.tr("Output"), self)
        ol = QVBoxLayout(out)
        self.output = QButtonGroup(self)
        self.out_write = QRadioButton(self.tr("Write into the layer's attribute table (point layers)"), out)
        self.out_vertices = QRadioButton(self.tr("New point layer with one point per vertex"), out)
        self.out_table = QRadioButton(self.tr("Copy as a table (paste into a spreadsheet)"), out)
        for button in (self.out_write, self.out_vertices, self.out_table):
            self.output.addButton(button)
            ol.addWidget(button)
        self.hint = QLabel(out)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(mid);")
        ol.addWidget(self.hint)
        outer.addWidget(out)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr("Run"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)

        self.layer_box.layerChanged.connect(self._layer_changed)
        for box in self.format_boxes.values():
            box.toggled.connect(self._update_state)
        self.output.buttonToggled.connect(lambda *_a: self._update_state())
        self._layer_changed(self.layer_box.currentLayer())

    # ------------------------------------------------------------------ state

    def formats(self):
        return {k for k, box in self.format_boxes.items() if box.isChecked()}

    def choice(self):
        if self.out_write.isChecked():
            return WRITE
        if self.out_vertices.isChecked():
            return VERTICES
        return TABLE

    def _layer_changed(self, layer):
        points = batch.is_point_layer(layer)
        self.out_write.setEnabled(points)
        if points:
            self.out_write.setChecked(True)
        elif layer is not None:
            self.out_vertices.setChecked(True)
        has_selection = layer is not None and layer.selectedFeatureCount() > 0
        self.selected_only.setChecked(has_selection)
        self.selected_only.setEnabled(has_selection)
        self._update_state()

    def _update_state(self):
        layer = self.layer_box.currentLayer()
        hints = {
            WRITE: self.tr("Adds fields such as lat, lon and x_25832 (existing ones are overwritten). "
                           "The layer is left in edit mode: save the edits to keep them, Ctrl+Z undoes."),
            VERTICES: self.tr("A temporary point layer with the fields src_fid, part, ring and vertex "
                              "plus the coordinates. Save it with Make Permanent if you need it."),
            TABLE: self.tr("Tab-separated with a header row – one row per point, or per vertex for lines "
                           "and polygons."),
        }
        self.hint.setText(hints[self.choice()])
        self.ok_button.setEnabled(layer is not None and bool(self.formats()))

    # ------------------------------------------------------------------ run

    def run(self):
        """Do the selected output. Returns a short message; raises ValueError on user errors."""
        layer = self.layer_box.currentLayer()
        if layer is None:
            raise ValueError(self.tr("Choose a layer"))
        formats = self.formats()
        selected = self.selected_only.isChecked()
        choice = self.choice()
        if choice == WRITE:
            n = batch.write_to_layer(layer, formats, self.chosen_crs, selected)
            message = self.tr("Coordinates written to {} feature(s) in {} – save the edits to keep them.")
            return message.format(n, layer.name())
        if choice == VERTICES:
            out = batch.vertices_layer(layer, formats, self.chosen_crs, selected)
            QgsProject.instance().addMapLayer(out)
            self.result_layer = out
            return self.tr("Layer \"{}\" added with {} point(s).").format(out.name(), out.featureCount())
        text = batch.as_table(layer, formats, self.chosen_crs, selected)
        QGuiApplication.clipboard().setText(text)
        return self.tr("Copied {} row(s) – paste into a spreadsheet.").format(text.count("\n") - 1)


def open_dialog(iface, chosen_crs, plugin_name):
    """Show the dialog for the active layer and report the result in the message bar."""
    dlg = BatchDialog(chosen_crs, iface.activeLayer(), iface.mainWindow())
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    if not dlg.exec():
        return None
    try:
        message = dlg.run()
    except ValueError as e:
        iface.messageBar().pushWarning(plugin_name, str(e))
        return None
    iface.messageBar().pushInfo(plugin_name, message)
    iface.mapCanvas().refresh()
    return message
