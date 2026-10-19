# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""The GeoDrafter Coordinate Finder and Converter panel.

Go to field, pick/follow buttons and a table of every format.
"""

from qgis.PyQt.QtCore import Qt, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QGuiApplication, QKeySequence
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QPushButton, QTableWidget, QTableWidgetItem, QToolButton,
    QVBoxLayout, QWidget,
)
from qgis.core import QgsApplication
from qgis.gui import QgsDockWidget, QgsProjectionSelectionWidget

try:  # Qt6 / QGIS 4
    from qgis.PyQt.QtGui import QShortcut
except ImportError:  # Qt5 / QGIS 3.40
    from qgis.PyQt.QtWidgets import QShortcut

CONVERTER_URL = "https://geodrafter.com/coordinate-converter/"
GOTO_HINT = (
    "Type a position and press Enter:\n"
    "• two numbers in the chosen CRS (lat, lon when it is geographic)\n"
    "• 57.0488N 9.9217E · 57°02′53″N 9°55′06″E · N57 02.890 E9 55.102\n"
    "• UTM: 32V 552000 6320000 (zone + latitude band)\n"
    "• MGRS: 32V NJ 52000 20000")


def _icon(name):
    return QgsApplication.getThemeIcon(name)


class CoordinatesPanel(QgsDockWidget):
    """Shows one position in every format. Emits ``go_requested(text)`` from the Go to field."""

    go_requested = pyqtSignal(str)

    def __init__(self, rows, parent=None):
        """``rows`` = [(key, label)] in display order (see Readout.keys_and_labels)."""
        super().__init__(parent)
        self.setObjectName("GeoDrafterCoordinateFinderPanel")
        self.setWindowTitle(self.tr("Coordinate Finder and Converter"))
        self._keys = [key for key, _label in rows]

        page = QWidget(self)
        outer = QVBoxLayout(page)
        self.setWidget(page)

        # Go to
        go_row = QHBoxLayout()
        self.go_field = QLineEdit(page)
        self.go_field.setObjectName("go_field")
        self.go_field.setPlaceholderText(self.tr("Go to: 57.0488, 9.9217 or 32V NJ 52000 20000"))
        self.go_field.setToolTip(self.tr(GOTO_HINT))
        self.go_field.setClearButtonEnabled(True)
        self.go_button = QToolButton(page)
        self.go_button.setIcon(_icon("/mActionZoomToSelected.svg"))
        self.go_button.setToolTip(self.tr("Centre the map on this position"))
        self.go_field.returnPressed.connect(self._emit_go)
        self.go_button.clicked.connect(self._emit_go)
        go_row.addWidget(self.go_field, 1)
        go_row.addWidget(self.go_button)
        outer.addLayout(go_row)

        # Pick / follow
        mode_row = QHBoxLayout()
        self.pick_button = QToolButton(page)
        self.pick_button.setText(self.tr("Pick on map"))
        self.pick_button.setIcon(_icon("/mActionCapturePoint.svg"))
        self.pick_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.pick_button.setCheckable(True)
        self.pick_button.setToolTip(
            self.tr("Click on the map to read a position. Right click or Esc stops."))
        self.follow_button = QToolButton(page)
        self.follow_button.setText(self.tr("Follow mouse"))
        self.follow_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.follow_button.setCheckable(True)
        self.follow_button.setToolTip(
            self.tr("Update while the mouse moves over the map; a click freezes it."))
        mode_row.addWidget(self.pick_button)
        mode_row.addWidget(self.follow_button)
        mode_row.addStretch(1)
        outer.addLayout(mode_row)

        # Chosen CRS
        form = QFormLayout()
        self.crs_picker = QgsProjectionSelectionWidget(page)
        self.crs_picker.setToolTip(self.tr("CRS of the 'Chosen CRS' row and of two typed numbers"))
        form.addRow(self.tr("Chosen CRS"), self.crs_picker)
        outer.addLayout(form)

        # Table of formats
        self.table = QTableWidget(len(rows), 2, page)
        self.table.setObjectName("formats")
        self.table.setHorizontalHeaderLabels([self.tr("Format"), self.tr("Value")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.cellDoubleClicked.connect(lambda row, _col: self.copy_key(self._keys[row]))
        self.table.setToolTip(self.tr("Double click a row (or Ctrl+C) to copy its value"))
        for row, (key, label) in enumerate(rows):
            name = QTableWidgetItem(self.tr(label))
            name.setData(Qt.ItemDataRole.UserRole, key)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(""))
        copy_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self.table)
        copy_shortcut.activated.connect(self.copy_selected)
        outer.addWidget(self.table, 1)

        # Copy on pick, copy all, converter
        self.copy_on_pick = QComboBox(page)
        self.copy_on_pick.addItem(self.tr("Don't copy"), "")
        for key, label in rows:
            self.copy_on_pick.addItem(self.tr(label), key)
        self.copy_on_pick.setToolTip(self.tr("Put this format on the clipboard every time you pick"))
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel(self.tr("On pick:"), page))
        bottom.addWidget(self.copy_on_pick, 1)
        self.copy_all_button = QPushButton(_icon("/mActionEditCopy.svg"), self.tr("Copy all"), page)
        self.copy_all_button.clicked.connect(self.copy_all)
        bottom.addWidget(self.copy_all_button)
        outer.addLayout(bottom)
        link_text = self.tr("Batch conversion: GeoDrafter coordinate converter")
        link = QLabel('<a href="%s">%s</a>' % (CONVERTER_URL, link_text), page)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.converter_link = link
        outer.addWidget(link)

    # -- values ------------------------------------------------------------------

    def show_rows(self, rows):
        """Fill the table from [(key, label, text)]."""
        for key, _label, text in rows:
            if key in self._keys:
                self.table.item(self._keys.index(key), 1).setText(text or "")

    def value(self, key):
        return self.table.item(self._keys.index(key), 1).text()

    # -- clipboard -----------------------------------------------------------------

    def copy_key(self, key):
        text = self.value(key)
        if text:
            QGuiApplication.clipboard().setText(text)
        return text

    def copy_selected(self):
        row = self.table.currentRow()
        return self.copy_key(self._keys[row]) if row >= 0 else ""

    def copy_all(self):
        lines = []
        for row, key in enumerate(self._keys):
            if self.value(key):
                lines.append("%s: %s" % (self.table.item(row, 0).text(), self.value(key)))
        text = "\n".join(lines)
        if text:
            QGuiApplication.clipboard().setText(text)
        return text

    def _table_menu(self, pos):
        row = self.table.rowAt(pos.y())
        menu = QMenu(self.table)
        if row >= 0:
            copy_one = menu.addAction(_icon("/mActionEditCopy.svg"), self.tr("Copy"))
            copy_one.triggered.connect(lambda _checked=False: self.copy_key(self._keys[row]))
        copy_every = menu.addAction(self.tr("Copy all"))
        copy_every.triggered.connect(lambda _checked=False: self.copy_all())
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _emit_go(self):
        self.go_requested.emit(self.go_field.text())
