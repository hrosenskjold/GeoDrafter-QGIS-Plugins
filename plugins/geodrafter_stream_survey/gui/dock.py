# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""The dock panel: the seven steps with status, the settings of the selected step, data check below."""

import os

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton, QSpinBox, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .i18n import tr

STEP_TITLES = (
    "Import survey", "Centre line and station", "Cross-sections", "Terrain extension",
    "Structures and drains", "Data check", "Long profile and export")

READERS = (("", "Automatic"), ("emlid_csv", "Emlid Flow CSV"), ("csv", "Other CSV"),
           ("field_text", "Text file, columns by position"), ("shapefile", "Shapefile (.shp/.zip)"),
           ("dxf", "DXF"))
EXPORTS = (("csv", "Section points as CSV…"), ("long_csv", "Long profile as CSV…"),
           ("hecras", "HEC-RAS geometry (.g01)…"), ("mike", "MIKE cross-sections (.txt)…"),
           ("pdf", "PDF profile sheets…"))
STRUCTURE_COLUMNS = ("Name", "Code", "Type", "Station", "Offset", "Elevation", "Bed", "Water level",
                     "Above bed", "Below water")
GROUPING = (("auto", "Automatic"), ("attribute", "Section number in the code attribute (Profil)"),
            ("name", "Section number in the point name (P12-03)"),
            ("description", "Section number in the description"), ("order", "Survey order and distance"))


def _layer_filter(kind):
    try:
        from qgis.core import Qgis
        return {"line": Qgis.LayerFilter.LineLayer, "raster": Qgis.LayerFilter.RasterLayer}[kind]
    except AttributeError:  # older QGIS
        from qgis.core import QgsMapLayerProxyModel
        return {"line": QgsMapLayerProxyModel.LineLayer, "raster": QgsMapLayerProxyModel.RasterLayer}[kind]


def _spin(lo, hi, value, step=0.1, decimals=2, suffix=" m"):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    s.setSuffix(suffix)
    return s


class StreamSurveyDock(QDockWidget):
    runStep = pyqtSignal(str)            # step key
    checkClicked = pyqtSignal(float, float)
    exportCodeLibrary = pyqtSignal()
    makeCodeTable = pyqtSignal()
    saveCheckSettings = pyqtSignal(str)
    exportRequested = pyqtSignal(str)
    unknownCodes = pyqtSignal()
    saveToken = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(tr("GeoDrafter Stream Survey"), parent)
        self.setObjectName("GeoDrafterStreamSurveyDock")
        body = QWidget()
        lay = QVBoxLayout(body)

        out = QHBoxLayout()
        out.addWidget(QLabel(tr("GeoPackage:")))
        self.gpkg_edit = QLineEdit()
        self.gpkg_edit.setPlaceholderText(tr("one GeoPackage per survey (next to the field file)"))
        out.addWidget(self.gpkg_edit, 1)
        b = QPushButton("…")
        b.setMaximumWidth(28)
        b.clicked.connect(self._browse_gpkg)
        out.addWidget(b)
        lay.addLayout(out)

        split = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        self.steps = QListWidget()
        self.steps.setMaximumWidth(190)
        for i, t in enumerate(STEP_TITLES):
            QListWidgetItem("%d  %s" % (i + 1, tr(t)), self.steps)
        tl.addWidget(self.steps)
        self.pages = QStackedWidget()
        for build in (self._page_import, self._page_centerline, self._page_profiles, self._page_terrain):
            self.pages.addWidget(build())
        self.pages.addWidget(self._page_structures())
        self.pages.addWidget(self._page_check())
        self.pages.addWidget(self._page_export())
        tl.addWidget(self.pages, 1)
        self.steps.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.steps.setCurrentRow(0)
        split.addWidget(top)

        chk = QGroupBox(tr("Data check"))
        cl = QVBoxLayout(chk)
        self.check_list = QListWidget()
        self.check_list.itemClicked.connect(self._check_clicked)
        cl.addWidget(self.check_list)
        split.addWidget(chk)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        self.setWidget(body)
        self.set_status(set())

    # -- pages ------------------------------------------------------------------------
    def _run_button(self, step, text):
        b = QPushButton(tr(text))
        b.setObjectName("run_" + step)
        b.clicked.connect(lambda _c=False, s=step: self.runStep.emit(s))
        return b

    def _page_import(self):
        w = QWidget()
        f = QFormLayout(w)
        row = QHBoxLayout()
        self.file_edit = QLineEdit()
        row.addWidget(self.file_edit, 1)
        b = QPushButton("…")
        b.setMaximumWidth(28)
        b.clicked.connect(self._browse_file)
        row.addWidget(b)
        f.addRow(tr("Field file:"), row)
        self.reader_combo = QComboBox()
        for key, label in READERS:
            self.reader_combo.addItem(tr(label), key)
        f.addRow(tr("Format:"), self.reader_combo)
        self.layout_edit = QLineEdit("name x y z code")
        self.layout_edit.setToolTip(tr("Columns of a text file, in order: name, x, y, z, code, description, "
                                       "or - to skip a column."))
        f.addRow(tr("Text columns:"), self.layout_edit)
        row2 = QHBoxLayout()
        self.table_combo = QComboBox()
        self.table_combo.setToolTip(tr("Translates the survey codes to point types."))
        row2.addWidget(self.table_combo, 1)
        b2 = QPushButton("…")
        b2.setMaximumWidth(28)
        b2.setToolTip(tr("Open a code table file (.yaml)"))
        b2.clicked.connect(self._browse_table)
        row2.addWidget(b2)
        f.addRow(tr("Code table:"), row2)
        self.refresh_tables()
        make = QPushButton(tr("Make a code table from a code list…"))
        make.setToolTip(tr("Any code list (municipality appendix, surveyor's list, Emlid code library, "
                           "spreadsheet): point types are suggested, you review and save."))
        make.clicked.connect(self.makeCodeTable.emit)
        f.addRow(make)
        self.unknown_button = QPushButton(tr("Unknown codes in the file…"))
        self.unknown_button.setEnabled(False)
        self.unknown_button.clicked.connect(self.unknownCodes.emit)
        f.addRow(self.unknown_button)
        lib = QPushButton(tr("Export code library for Emlid Flow…"))
        lib.clicked.connect(self.exportCodeLibrary.emit)
        f.addRow(lib)
        f.addRow(self._run_button("import", "Import"))
        self.import_summary = QLabel("")
        self.import_summary.setWordWrap(True)
        f.addRow(self.import_summary)
        return w

    def _page_centerline(self):
        from qgis.gui import QgsMapLayerComboBox
        w = QWidget()
        f = QFormLayout(w)
        self.cl_inspire = QRadioButton(tr("Watercourse from INSPIRE Hydrography (Dataforsyningen, no token)"))
        self.cl_layer = QRadioButton(tr("Own line layer (e.g. regulation line or a line you drew)"))
        self.cl_build = QRadioButton(tr("Build from the lowest bed point of each section"))
        self.cl_inspire.setChecked(True)
        g = QButtonGroup(w)
        for r in (self.cl_inspire, self.cl_layer, self.cl_build):
            g.addButton(r)
            f.addRow(r)
        self.cl_layer_combo = QgsMapLayerComboBox()
        self.cl_layer_combo.setFilters(_layer_filter("line"))
        f.addRow(tr("Line layer:"), self.cl_layer_combo)
        self.cl_selected_only = QComboBox()
        self.cl_selected_only.addItem(tr("Selected feature (or the first)"), True)
        self.cl_selected_only.addItem(tr("Nearest feature to the survey"), False)
        f.addRow(tr("Feature:"), self.cl_selected_only)
        self.cl_fit = QCheckBox(tr("Fit the line to the surveyed bed points"))
        self.cl_fit.setToolTip(tr("Moves the line through the lowest bed point of each section between the "
                                  "first and the last section and keeps the rest, so the station follows "
                                  "the actual stream."))
        f.addRow(self.cl_fit)
        self.cl_max_dist = _spin(0.5, 100, 5.0, 0.5, 1)
        self.cl_max_dist.setToolTip(tr("Bed points further from the line give a warning in the data check."))
        f.addRow(tr("Warn when bed points are further than:"), self.cl_max_dist)
        self.station_value = _spin(-100000, 1000000, 0.0, 1.0, 2)
        f.addRow(tr("Station:"), self.station_value)
        self.station_point = QComboBox()
        self.station_point.setToolTip(tr("The fixed point the station value refers to."))
        self.station_point.addItem(tr("Start of the centre line"), "")
        f.addRow(tr("at point:"), self.station_point)
        self.upstream_combo = QComboBox()
        self.upstream_combo.addItem(tr("From the fall of the bed"), "")
        self.upstream_combo.setToolTip(tr("Flow direction: from the fall of the bed, or the end of the line "
                                          "nearest a point you know is upstream."))
        f.addRow(tr("Upstream point:"), self.upstream_combo)
        f.addRow(self._run_button("centerline", "Build stationing"))
        self.cl_summary = QLabel("")
        self.cl_summary.setWordWrap(True)
        f.addRow(self.cl_summary)
        return w

    def _page_profiles(self):
        w = QWidget()
        f = QFormLayout(w)
        self.grouping_combo = QComboBox()
        for key, label in GROUPING:
            self.grouping_combo.addItem(tr(label), key)
        f.addRow(tr("Group points by:"), self.grouping_combo)
        self.max_gap = _spin(1, 500, 15.0, 1.0, 1)
        self.max_gap.setToolTip(tr("Survey order: a new section starts after a jump longer than this."))
        f.addRow(tr("Max. jump within a section:"), self.max_gap)
        self.min_points = QSpinBox()
        self.min_points.setRange(2, 50)
        self.min_points.setValue(3)
        f.addRow(tr("Min. points per section:"), self.min_points)
        self.tangent_window = _spin(0, 50, 5.0, 0.5, 1)
        self.tangent_window.setToolTip(tr("The section line is perpendicular to the centre line over ± this "
                                          "distance, so sections in a bend follow the bisector."))
        f.addRow(tr("Direction over ±:"), self.tangent_window)
        f.addRow(self._run_button("profiles", "Build cross-sections"))
        self.pr_summary = QLabel("")
        self.pr_summary.setWordWrap(True)
        f.addRow(self.pr_summary)
        return w

    def _page_terrain(self):
        from qgis.gui import QgsMapLayerComboBox
        w = QWidget()
        f = QFormLayout(w)
        self.src_dhm = QRadioButton(tr("Danmarks Højdemodel (Dataforsyningen, your token)"))
        self.src_layer = QRadioButton(tr("Raster layer in the project"))
        self.src_file = QRadioButton(tr("Local terrain model file (GeoTIFF/VRT)"))
        self.src_layer.setChecked(True)
        g = QButtonGroup(w)
        for r in (self.src_dhm, self.src_layer, self.src_file):
            g.addButton(r)
            f.addRow(r)
        tok = QHBoxLayout()
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText(tr("token from dataforsyningen.dk"))
        tok.addWidget(self.token_edit, 1)
        save = QPushButton(tr("Save"))
        save.setToolTip(tr("Stores the token in the QGIS password manager; it is sent as a header, "
                           "never saved in the project."))
        save.clicked.connect(lambda: self.saveToken.emit(self.token_edit.text()))
        tok.addWidget(save)
        f.addRow(tr("Token:"), tok)
        self.token_status = QLabel("")
        f.addRow(self.token_status)
        self.raster_combo = QgsMapLayerComboBox()
        self.raster_combo.setFilters(_layer_filter("raster"))
        self.raster_combo.setAllowEmptyLayer(True)
        f.addRow(tr("Raster layer:"), self.raster_combo)
        row = QHBoxLayout()
        self.dem_file_edit = QLineEdit()
        row.addWidget(self.dem_file_edit, 1)
        b = QPushButton("…")
        b.setMaximumWidth(28)
        b.clicked.connect(self._browse_dem)
        row.addWidget(b)
        f.addRow(tr("File:"), row)
        self.dhm_version = QLineEdit()
        self.dhm_version.setPlaceholderText(tr("e.g. DHM/Terræn 0.4 m, 2023"))
        f.addRow(tr("Terrain model version:"), self.dhm_version)
        self.ext_length = _spin(5, 50, 10.0, 1.0, 1)
        f.addRow(tr("Extension beyond bank top:"), self.ext_length)
        self.ext_step = _spin(0.1, 5, 0.4, 0.1, 1)
        self.ext_step.setToolTip(tr("Distance between the points read from the terrain model. "
                                    "0.4 m matches the grid of DHM/Terræn."))
        f.addRow(tr("Point spacing in the terrain part:"), self.ext_step)
        self.ext_tol = _spin(0, 0.5, 0.10, 0.01, 2)
        f.addRow(tr("Join directly up to:"), self.ext_tol)
        self.ext_transition = _spin(0, 20, 3.0, 0.5, 1)
        f.addRow(tr("Transition zone:"), self.ext_transition)
        self.ext_error = _spin(0.05, 5, 0.50, 0.05, 2)
        f.addRow(tr("Error limit:"), self.ext_error)
        self.ext_thin = _spin(0, 0.5, 0.02, 0.01, 3)
        f.addRow(tr("Thinning tolerance:"), self.ext_thin)
        self.ext_controls = QComboBox()
        self.ext_controls.addItem(tr("Check against the terrain model"), "check")
        self.ext_controls.addItem(tr("Keep in the section, extend beyond them"), "keep")
        f.addRow(tr("Terrain points beyond bank top:"), self.ext_controls)
        f.addRow(self._run_button("terrain", "Extend sections"))
        self.tr_summary = QLabel("")
        self.tr_summary.setWordWrap(True)
        f.addRow(self.tr_summary)
        return w

    def _page_structures(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(self._run_button("structures", "Locate structures and drains"))
        self.st_table = QTableWidget(0, len(STRUCTURE_COLUMNS))
        self.st_table.setHorizontalHeaderLabels([tr(c) for c in STRUCTURE_COLUMNS])
        self.st_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.st_table.cellDoubleClicked.connect(self._structure_clicked)
        v.addWidget(self.st_table, 1)
        note = QLabel(tr("Bed and water level are interpolated between the neighbouring sections. "
                         "Double-click a row to zoom to it."))
        note.setWordWrap(True)
        v.addWidget(note)
        return w

    def set_structures(self, results):
        self.st_table.setRowCount(len(results))
        self._structures = results

        def fmt(v, n=2):
            return "" if v is None else ("%." + str(n) + "f") % v
        for r, s in enumerate(results):
            p = s.point
            vals = (p.name, p.code, p.point_type, fmt(s.located.station, 1), fmt(s.located.offset),
                    fmt(p.z, 3), fmt(s.bed_z, 3), fmt(s.water_z, 3), fmt(s.above_bed), fmt(s.below_water))
            for c, val in enumerate(vals):
                self.st_table.setItem(r, c, QTableWidgetItem(val))

    def _structure_clicked(self, row, _col):
        s = getattr(self, "_structures", [])[row]
        self.checkClicked.emit(float(s.point.x), float(s.point.y))

    def _page_check(self):
        w = QWidget()
        f = QFormLayout(w)
        row = QHBoxLayout()
        self.chk_combo = QComboBox()
        self.chk_combo.setToolTip(tr("Limits saved per municipality."))
        row.addWidget(self.chk_combo, 1)
        f.addRow(tr("Limits:"), row)
        self.chk_spacing = _spin(10, 1000, 120.0, 10, 0)
        f.addRow(tr("Max. distance between sections:"), self.chk_spacing)
        self.chk_along = _spin(0.05, 20, 1.0, 0.1, 2)
        f.addRow(tr("Max. distance from the section line:"), self.chk_along)
        self.chk_rms = _spin(0.001, 0.5, 0.03, 0.005, 3)
        f.addRow(tr("Max. elevation RMS:"), self.chk_rms)
        self.chk_dhm = _spin(0.01, 2, 0.10, 0.01, 2)
        f.addRow(tr("Max. terrain model jump at bank top:"), self.chk_dhm)
        self.chk_bed_ws = _spin(0, 1, 0.0, 0.01, 2)
        f.addRow(tr("Bed may lie above water level by:"), self.chk_bed_ws)
        self.chk_fix = QCheckBox(tr("GNSS points must be FIX"))
        self.chk_fix.setChecked(True)
        f.addRow(self.chk_fix)
        self.chk_ws = QCheckBox(tr("Every section needs a water level"))
        self.chk_ws.setChecked(True)
        f.addRow(self.chk_ws)
        self.chk_banks = QCheckBox(tr("Every section needs a bank top on both sides"))
        self.chk_banks.setChecked(True)
        f.addRow(self.chk_banks)
        save = QHBoxLayout()
        self.chk_name = QLineEdit()
        self.chk_name.setPlaceholderText(tr("e.g. Aabenraa Kommune"))
        save.addWidget(self.chk_name, 1)
        b = QPushButton(tr("Save limits"))
        b.clicked.connect(lambda: self.saveCheckSettings.emit(self.chk_name.text()))
        save.addWidget(b)
        f.addRow(tr("Save as:"), save)
        f.addRow(self._run_button("check", "Run data check"))
        self.chk_summary = QLabel("")
        self.chk_summary.setWordWrap(True)
        f.addRow(self.chk_summary)
        self.chk_combo.currentIndexChanged.connect(self._check_settings_chosen)
        self._check_choices = []
        return w

    def set_check_choices(self, choices, select=None):
        """choices: [(name, CheckSettings)]"""
        self._check_choices = list(choices)
        self.chk_combo.blockSignals(True)
        self.chk_combo.clear()
        for name, _s in self._check_choices:
            self.chk_combo.addItem(name)
        self.chk_combo.blockSignals(False)
        names = [n for n, _s in self._check_choices]
        idx = names.index(select) if select in names else 0
        self.chk_combo.setCurrentIndex(idx)
        self._check_settings_chosen(idx)

    def _check_settings_chosen(self, i):
        if not (0 <= i < len(self._check_choices)):
            return
        s = self._check_choices[i][1]
        self.chk_spacing.setValue(s.max_spacing)
        self.chk_along.setValue(s.max_along)
        self.chk_rms.setValue(s.max_rms_z)
        self.chk_dhm.setValue(s.max_dhm_jump)
        self.chk_bed_ws.setValue(s.bed_above_water_tol)
        self.chk_fix.setChecked(s.require_fix)
        self.chk_ws.setChecked(s.require_water_level)
        self.chk_banks.setChecked(s.require_bank_tops)

    def check_settings(self, name=None):
        from ..core.checks import CheckSettings
        return CheckSettings(
            name=name or self.chk_combo.currentText() or "GeoDrafter standard",
            max_spacing=self.chk_spacing.value(), max_along=self.chk_along.value(),
            max_rms_z=self.chk_rms.value(), require_fix=self.chk_fix.isChecked(),
            bed_above_water_tol=self.chk_bed_ws.value(), max_dhm_jump=self.chk_dhm.value(),
            require_water_level=self.chk_ws.isChecked(), require_bank_tops=self.chk_banks.isChecked())

    def _page_export(self):
        w = QWidget()
        f = QFormLayout(w)
        lab = QLabel(tr("The long profile is shown in the cross-section panel (tab Long profile)."))
        lab.setWordWrap(True)
        f.addRow(lab)
        self.river_edit = QLineEdit()
        self.river_edit.setPlaceholderText(tr("stream name (for HEC-RAS and MIKE)"))
        f.addRow(tr("Stream:"), self.river_edit)
        for kind, label in EXPORTS:
            b = QPushButton(tr(label))
            b.setObjectName("export_" + kind)
            b.clicked.connect(lambda _c=False, k=kind: self.exportRequested.emit(k))
            f.addRow(b)
        self.export_summary = QLabel("")
        self.export_summary.setWordWrap(True)
        f.addRow(self.export_summary)
        return w

    def _page_later(self):
        w = QWidget()
        v = QVBoxLayout(w)
        lab = QLabel(tr("Comes in a later version."))
        lab.setWordWrap(True)
        v.addWidget(lab)
        v.addStretch(1)
        return w

    # -- helpers ----------------------------------------------------------------------
    def _browse_file(self):
        start = os.path.dirname(self.file_edit.text())
        filt = tr("Survey files (*.csv *.txt *.shp *.zip *.dxf);;All files (*)")
        path, _f = QFileDialog.getOpenFileName(self, tr("Field file"), start, filt)
        if path:
            self.file_edit.setText(path)
            if not self.gpkg_edit.text():
                self.gpkg_edit.setText(os.path.splitext(path)[0] + "_stream_survey.gpkg")

    def _browse_table(self):
        path, _f = QFileDialog.getOpenFileName(self, tr("Code table"), "", tr("Code tables (*.yaml *.yml)"))
        if path:
            self.refresh_tables(select=path, extra=path)

    def refresh_tables(self, select=None, extra=None):
        """Code tables to choose from: the standard ones, the user's saved ones, and a chosen file."""
        from ..core import codes
        from .codemap_dialog import saved_tables
        cur = select or self.table_path()
        self.table_combo.clear()
        self.table_combo.addItem(tr("GeoDrafter standard"), codes.STANDARD_TABLE)
        self.table_combo.addItem(tr("GeoDrafter standard (English)"), codes.STANDARD_TABLE_EN)
        self.table_combo.addItem(tr("VASP codes (VASPGPS)"), codes.VASP_TABLE)
        paths = [codes.STANDARD_TABLE, codes.STANDARD_TABLE_EN, codes.VASP_TABLE]
        for name, path in saved_tables():
            self.table_combo.addItem(name, path)
            paths.append(path)
        for p in (extra, cur):
            if p and p not in paths:
                self.table_combo.addItem(os.path.basename(p), p)
                paths.append(p)
        if cur in paths:
            self.table_combo.setCurrentIndex(paths.index(cur))

    def table_path(self):
        return self.table_combo.currentData() if hasattr(self, "table_combo") else None

    def _browse_dem(self):
        path, _f = QFileDialog.getOpenFileName(self, tr("Terrain model"), "",
                                               tr("Rasters (*.tif *.tiff *.vrt *.asc);;All files (*)"))
        if path:
            self.dem_file_edit.setText(path)
            self.src_file.setChecked(True)

    def _browse_gpkg(self):
        path, _f = QFileDialog.getSaveFileName(self, tr("Survey GeoPackage"), self.gpkg_edit.text(),
                                               "GeoPackage (*.gpkg)")
        if path:
            self.gpkg_edit.setText(path if path.lower().endswith(".gpkg") else path + ".gpkg")

    def text_layout(self):
        keys = []
        for k in self.layout_edit.text().replace(",", " ").split():
            keys.append(None if k in ("-", "_", "skip") else k.strip().lower())
        return keys

    def set_status(self, done, failed=()):
        from ..gui.project import STEPS
        for i, key in enumerate(STEPS):
            item = self.steps.item(i)
            if key in failed:
                item.setForeground(QBrush(QColor("#c0392b")))
            elif key in done:
                item.setForeground(QBrush(QColor("#2e8b3e")))
            else:
                item.setForeground(QBrush(QColor("#6b7785" if i >= 6 else "#1f2933")))

    def set_checks(self, checks):
        self.check_list.clear()
        colors = {"error": "#c0392b", "warning": "#b9770e", "info": "#5d6d7e"}
        for c in checks:
            it = QListWidgetItem("%s  %s" % ({"error": "✖", "warning": "!", "info": "·"}.get(c.severity, ""),
                                             c.message))
            it.setForeground(QBrush(QColor(colors.get(c.severity, "#1f2933"))))
            it.setData(Qt.ItemDataRole.UserRole, (c.x, c.y))
            self.check_list.addItem(it)
        if not checks:
            self.check_list.addItem(tr("No remarks."))

    def _check_clicked(self, item):
        xy = item.data(Qt.ItemDataRole.UserRole)
        if xy:
            self.checkClicked.emit(float(xy[0]), float(xy[1]))

    def set_point_names(self, names):
        for combo, first in ((self.station_point, tr("Start of the centre line")),
                             (self.upstream_combo, tr("From the fall of the bed"))):
            combo.clear()
            combo.addItem(first, "")
            for n in names:
                combo.addItem(n, n)
