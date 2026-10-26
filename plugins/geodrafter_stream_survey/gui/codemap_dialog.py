# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Dialog: review the suggested point types of a code list and save it as a code table."""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor, QGuiApplication
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from qgis.core import Qgis, QgsMessageLog

from ..core import codemap, codes
from ..core.model import POINT_TYPES
from .i18n import tr

CONFIDENCE_LABELS = {"sure": "sure", "unsure": "uncertain", "unknown": "unknown"}
CONFIDENCE_COLORS = {"sure": "#2e8b3e", "unsure": "#b9770e", "unknown": "#c0392b"}
TYPE_LABELS = {
    "bed": "Bed", "bank_top": "Bank top", "bank_toe": "Bank toe", "water_level": "Water level",
    "terrain": "Terrain", "pipe_invert": "Pipe invert", "pipe_top": "Pipe top", "bridge_deck": "Bridge deck",
    "weir_crest": "Weir crest", "drain_outlet": "Drain outlet", "staff_gauge": "Staff gauge",
    "knick": "Break point", "other": "Other"}


def user_table_dir():
    """Code tables saved by the user, in the QGIS profile."""
    try:
        from qgis.core import QgsApplication
        base = QgsApplication.qgisSettingsDirPath()
    except Exception:
        base = os.path.expanduser("~")
    d = os.path.join(base, "geodrafter_stream_survey", "codetables")
    os.makedirs(d, exist_ok=True)
    return d


def saved_tables():
    """[(name, path)] of the user's saved code tables."""
    out = []
    d = user_table_dir()
    for fn in sorted(os.listdir(d)):
        if fn.endswith((".yaml", ".yml")):
            path = os.path.join(d, fn)
            try:
                out.append((codes.load_table(path).name, path))
            except Exception as err:  # noqa: BLE001 – a broken user file must not hide the others
                QgsMessageLog.logMessage("Code table %s skipped: %s" % (fn, err), "GeoDrafter Stream Survey",
                                         Qgis.MessageLevel.Warning)
    return out


class CodeMapDialog(QDialog):
    COLUMN_TITLES = ("Code", "Points", "Description", "Point type", "Confidence", "Reason")
    TYPE_COL = 3

    def __init__(self, parent=None, mapped=None, name="", base_table=None, extend=False,
                 fields=None, field=None, on_field=None, intro=""):
        """``fields`` [(key, label)] + ``on_field(key) -> [MappedCode]``: a chooser for the field that holds
        the codes (survey pop-up); ``intro`` is shown on top."""
        super().__init__(parent)
        self.setWindowTitle(tr("Pair the survey codes") if fields else tr("Code table from a code list"))
        self.resize(900, 560)
        self.mapped = list(mapped or [])
        self.base_table = base_table
        self.extend = extend           # True: add the codes to base_table instead of a new table
        self.saved_path = None
        self.on_field = on_field
        self.field = field
        v = QVBoxLayout(self)
        if intro:
            lab = QLabel(intro)
            lab.setWordWrap(True)
            v.addWidget(lab)
        self.field_combo = None
        if fields:
            frow = QHBoxLayout()
            frow.addWidget(QLabel(tr("The codes are in the field:")))
            self.field_combo = QComboBox()
            for key, label in fields:
                self.field_combo.addItem(label, key)
            i = self.field_combo.findData(field)
            if i >= 0:
                self.field_combo.setCurrentIndex(i)
            self.field_combo.currentIndexChanged.connect(self._field_changed)
            frow.addWidget(self.field_combo, 1)
            v.addLayout(frow)
        top = QHBoxLayout()
        self.open_button = QPushButton(tr("Open code list…"))
        self.open_button.setToolTip(tr("CSV/TXT, Excel (.xlsx), an Emlid Flow code library or a GeoDrafter "
                                       "code table (.yaml)"))
        self.paste_button = QPushButton(tr("Paste from clipboard"))
        self.only_unsure = QCheckBox(tr("Only uncertain"))
        top.addWidget(self.open_button)
        top.addWidget(self.paste_button)
        top.addStretch(1)
        top.addWidget(self.only_unsure)
        v.addLayout(top)
        self.table = QTableWidget(0, len(self.COLUMN_TITLES))
        self.table.setHorizontalHeaderLabels([tr(c) for c in self.COLUMN_TITLES])
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)
        self.summary = QLabel("")
        v.addWidget(self.summary)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Name of the code table:")))
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText(tr("e.g. Aabenraa Kommune 2026"))
        row.addWidget(self.name_edit, 1)
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.open_button.clicked.connect(self.open_list)
        self.paste_button.clicked.connect(self.paste)
        self.only_unsure.toggled.connect(self._filter)
        self.fill()

    # -- data --------------------------------------------------------------------------------
    def _field_changed(self, _i):
        self.field = self.field_combo.currentData()
        if self.on_field is not None:
            self.mapped = list(self.on_field(self.field))
            self.fill()

    def set_list(self, code_list):
        self.mapped = codemap.map_codes(code_list)
        if not self.name_edit.text() and code_list.source and code_list.source not in ("survey", "clipboard"):
            self.name_edit.setText(os.path.splitext(code_list.source)[0])
        self.fill()
        if code_list.warnings:
            self.summary.setText(self.summary.text() + "  " + " ".join(code_list.warnings))

    def open_list(self):
        filt = tr("Code lists (*.csv *.txt *.xlsx *.yaml *.yml *.ini *.fxl);;All files (*)")
        path, _f = QFileDialog.getOpenFileName(self, tr("Code list"), "", filt)
        if not path:
            return
        try:
            self.set_list(codemap.read_code_list(path))
        except Exception as e:
            QMessageBox.warning(self, tr("Code list"), str(e))

    def paste(self):
        text = QGuiApplication.clipboard().text()
        self.set_list(codemap.parse_text(text, "clipboard"))

    def fill(self):
        self.table.setRowCount(len(self.mapped))
        for r, m in enumerate(self.mapped):
            self.table.setItem(r, 0, QTableWidgetItem(m.row.code))
            self.table.setItem(r, 1, QTableWidgetItem(str(m.row.count) if getattr(m.row, "count", 0) else ""))
            self.table.setItem(r, 2, QTableWidgetItem(m.row.description))
            combo = QComboBox()
            for t in POINT_TYPES:
                combo.addItem(tr(TYPE_LABELS[t]), t)
            combo.setCurrentIndex(POINT_TYPES.index(m.point_type) if m.point_type in POINT_TYPES else
                                  POINT_TYPES.index("other"))
            combo.currentIndexChanged.connect(lambda _i, row=r, c=combo: self._set_type(row, c.currentData()))
            self.table.setCellWidget(r, self.TYPE_COL, combo)
            conf = QTableWidgetItem(tr(CONFIDENCE_LABELS[m.suggestion.confidence]))
            conf.setForeground(QBrush(QColor(CONFIDENCE_COLORS[m.suggestion.confidence])))
            self.table.setItem(r, 4, conf)
            self.table.setItem(r, 5, QTableWidgetItem(m.suggestion.reason))
            for c in (0, 1, 2, 4, 5):
                it = self.table.item(r, c)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        n = {k: sum(1 for m in self.mapped if m.suggestion.confidence == k) for k in CONFIDENCE_LABELS}
        self.summary.setText(tr("%d codes: %d sure, %d uncertain, %d unknown.") % (
            len(self.mapped), n["sure"], n["unsure"], n["unknown"]))
        self._filter(self.only_unsure.isChecked())

    def _set_type(self, row, t):
        self.mapped[row].point_type = t

    def _filter(self, only):
        for r, m in enumerate(self.mapped):
            self.table.setRowHidden(r, bool(only) and m.suggestion.confidence == "sure")

    def table_result(self):
        name = self.name_edit.text().strip()
        if self.extend and self.base_table is not None:
            t = codemap.extend_table(self.base_table, self.mapped)
            if name:
                t.name = name
            return t
        return codemap.build_table(name or tr("My code table"), self.mapped)

    def save(self):
        if not self.mapped:
            QMessageBox.information(self, tr("Code list"), tr("Open or paste a code list first."))
            return
        try:
            t = self.table_result()
            path = os.path.join(user_table_dir(), codemap.slug(t.name) + ".yaml")
            codes.save_table(t, path)
        except Exception as e:
            QMessageBox.warning(self, tr("Code list"), str(e))
            return
        self.saved_path = path
        self.accept()
