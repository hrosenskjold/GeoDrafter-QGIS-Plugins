# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Cross-section view: a dock under the map with the section drawing and a point table.

The drawing shows the measured part (solid, dark blue), the terrain-model part
(dashed, orange), transition zones (shaded) and the water level (blue). Points
can be dragged (new offset and elevation) and given a new code with a right
click; the terrain-model part of a side can be removed. Previous/next steps
through the sections in station order.
"""

from qgis.PyQt.QtCore import QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor, QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QComboBox, QDockWidget, QHBoxLayout, QLabel, QMenu, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget)

from .i18n import tr

COL_MEASURED = QColor("#1f3a5f")
COL_DHM = QColor("#ff6a00")
COL_TRANSITION = QColor(241, 196, 15, 70)
COL_WATER = QColor("#2fa4e7")
COL_GRID = QColor("#d5dbe1")
PICK_PX = 8
SOURCE_LABELS = {"measured": "Measured", "dhm": "Terrain model", "transition": "Transition"}


class ProfileCanvas(QWidget):
    """Draws one section; emits edits. Data: list of ExtPoint-like objects (offset, z, source, point)."""

    pointMoved = pyqtSignal(int, float, float)        # index, offset, z
    codeRequested = pyqtSignal(int, object)            # index, global position (QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setMouseTracking(True)
        self.points = []
        self.water = None            # (z, left, right)
        self.transition = 0.0
        self.selected = -1
        self._drag = -1
        self._drag_pos = None
        self._box = None             # (xmin, xmax, zmin, zmax)

    def set_data(self, points, water=None, transition=0.0):
        self.points = list(points)
        self.water = water
        self.transition = transition
        self.selected = -1
        self._fit()
        self.update()

    def _fit(self):
        pts = [(e.offset, e.z) for e in self.points if e.z is not None]
        if not pts:
            self._box = None
            return
        xs, zs = [p[0] for p in pts], [p[1] for p in pts]
        if self.water:
            zs.append(self.water[0])
        dx = max(max(xs) - min(xs), 1.0)
        dz = max(max(zs) - min(zs), 0.5)
        self._box = (min(xs) - 0.03 * dx, max(xs) + 0.03 * dx, min(zs) - 0.1 * dz, max(zs) + 0.15 * dz)

    def _plot_rect(self):
        o = getattr(self, "_outer", None) or QRectF(0, 0, self.width(), self.height())
        return QRectF(o.left() + 48, o.top() + 8, max(o.width() - 56, 10), max(o.height() - 30, 10))

    def to_px(self, offset, z):
        r = self._plot_rect()
        x0, x1, z0, z1 = self._box
        return QPointF(r.left() + (offset - x0) / (x1 - x0) * r.width(),
                       r.bottom() - (z - z0) / (z1 - z0) * r.height())

    def from_px(self, px, py):
        r = self._plot_rect()
        x0, x1, z0, z1 = self._box
        return (x0 + (px - r.left()) / r.width() * (x1 - x0), z0 + (r.bottom() - py) / r.height() * (z1 - z0))

    def nearest(self, px, py):
        best, bd = -1, PICK_PX
        for i, e in enumerate(self.points):
            if e.z is None:
                continue
            q = self.to_px(e.offset, e.z)
            d = ((q.x() - px) ** 2 + (q.y() - py) ** 2) ** 0.5
            if d <= bd:
                best, bd = i, d
        return best

    # -- painting ---------------------------------------------------------------------------
    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        self._outer = None
        self.render_to(p, QRectF(0, 0, self.width(), self.height()))
        p.end()

    def render_to(self, p, outer):
        """Draw the section into ``outer`` on any painter (widget, PDF page)."""
        self._outer = outer
        try:
            self._draw(p, outer)
        finally:
            self._outer = None

    def _draw(self, p, outer):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(outer, QColor("#ffffff"))
        if self._box is None:
            p.setPen(QColor("#6b7785"))
            p.drawText(outer, Qt.AlignmentFlag.AlignCenter, tr("No section selected."))
            return
        r = self._plot_rect()
        x0, x1, z0, z1 = self._box
        p.setPen(QPen(COL_GRID, 1))
        p.drawRect(r)
        p.setPen(QColor("#4b5563"))
        for i in range(5):
            z = z0 + (z1 - z0) * i / 4.0
            y = self.to_px(x0, z).y()
            p.drawText(QRectF(0, y - 8, 44, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       "%.2f" % z)
        for i in range(5):
            off = x0 + (x1 - x0) * i / 4.0
            x = self.to_px(off, z0).x()
            p.drawText(QRectF(x - 30, r.bottom() + 2, 60, 16), Qt.AlignmentFlag.AlignHCenter, "%.1f" % off)
        # transition zones (shaded)
        tr_pts = [e for e in self.points if e.source == "transition"]
        for side in (-1, 1):
            s = [e.offset for e in tr_pts if (e.offset > 0) == (side > 0)]
            if s:
                a, b = self.to_px(min(s), z1), self.to_px(max(s), z0)
                p.fillRect(QRectF(a, b).normalized(), QBrush(COL_TRANSITION))
        # water level
        if self.water:
            wz, wl, wr = self.water
            p.setPen(QPen(COL_WATER, 2))
            p.drawLine(self.to_px(wl, wz), self.to_px(wr, wz))
        # the section line: solid where both ends are measured, dashed otherwise
        pts = [e for e in self.points if e.z is not None]
        for a, b in zip(pts, pts[1:]):
            measured = a.source == "measured" and b.source == "measured"
            pen = QPen(COL_MEASURED if measured else COL_DHM, 2)
            if not measured:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(self.to_px(a.offset, a.z), self.to_px(b.offset, b.z))
        for i, e in enumerate(self.points):
            if e.z is None:
                continue
            q = self.to_px(e.offset, e.z)
            col = COL_MEASURED if e.source == "measured" else COL_DHM
            p.setPen(QPen(QColor("#ffd400") if i == self.selected else QColor("#ffffff"), 2))
            p.setBrush(QBrush(col))
            p.drawEllipse(q, 4.5 if e.source == "measured" else 3.0, 4.5 if e.source == "measured" else 3.0)

    # -- mouse ------------------------------------------------------------------------------
    def _pos(self, event):
        pos = event.position() if hasattr(event, "position") else event.pos()
        return pos.x(), pos.y()

    def mousePressEvent(self, event):  # noqa: N802
        if self._box is None:
            return
        x, y = self._pos(event)
        i = self.nearest(x, y)
        self.selected = i
        if i >= 0 and event.button() == Qt.MouseButton.RightButton:
            gp = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            self.codeRequested.emit(i, gp)
        elif i >= 0:
            self._drag = i
            self._drag_pos = (x, y)
        self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag >= 0:
            self._drag_pos = self._pos(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag >= 0:
            x, y = self._pos(event)
            if self._moved(self._drag, x, y):
                off, z = self.from_px(x, y)
                self.pointMoved.emit(self._drag, off, z)
        self._drag = -1

    def _moved(self, i, x, y):
        e = self.points[i]
        q = self.to_px(e.offset, e.z)
        return abs(q.x() - x) > 2 or abs(q.y() - y) > 2


LONG_LABELS = {"bed": "Bed", "water": "Water level", "bank_left": "Bank top left",
               "bank_right": "Bank top right", "terrain_left": "Terrain left",
               "terrain_right": "Terrain right"}
LONG_SERIES = tuple((k, LONG_LABELS[k], c, d) for k, c, d in (
    ("bed", "#1f3a5f", False), ("water", "#2fa4e7", False), ("bank_left", "#2e8b3e", False),
    ("bank_right", "#7fb04f", False), ("terrain_left", "#ff6a00", True), ("terrain_right", "#d35400", True)))


class LongProfileCanvas(QWidget):
    """Long profile: bed, water level, bank tops and terrain on both sides along the station."""

    stationClicked = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.rows = []
        self.current_station = None

    def set_rows(self, rows, current_station=None):
        self.rows = list(rows)
        self.current_station = current_station
        self.update()

    def _box(self):
        zs = [getattr(r, k) for r in self.rows for k, _l, _c, _d in LONG_SERIES if getattr(r, k) is not None]
        st = [r.station for r in self.rows]
        if not zs or not st:
            return None
        ds = max(max(st) - min(st), 1.0)
        dz = max(max(zs) - min(zs), 0.5)
        return (min(st) - 0.02 * ds, max(st) + 0.02 * ds, min(zs) - 0.1 * dz, max(zs) + 0.2 * dz)

    def _map(self, outer, box, s, z):
        r = QRectF(outer.left() + 48, outer.top() + 8,
                   max(outer.width() - 56, 10), max(outer.height() - 30, 10))
        x0, x1, z0, z1 = box
        return QPointF(r.left() + (s - x0) / (x1 - x0) * r.width(),
                       r.bottom() - (z - z0) / (z1 - z0) * r.height())

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        self.render_to(p, QRectF(0, 0, self.width(), self.height()))
        p.end()

    def render_to(self, p, outer):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(outer, QColor("#ffffff"))
        box = self._box()
        if box is None:
            p.setPen(QColor("#6b7785"))
            p.drawText(outer, Qt.AlignmentFlag.AlignCenter, tr("Build the cross-sections first."))
            return
        x0, x1, z0, z1 = box
        p.setPen(QColor("#4b5563"))
        for i in range(5):
            z = z0 + (z1 - z0) * i / 4.0
            y = self._map(outer, box, x0, z).y()
            p.drawText(QRectF(outer.left(), y - 8, 44, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "%.2f" % z)
        for i in range(5):
            s = x0 + (x1 - x0) * i / 4.0
            q = self._map(outer, box, s, z0)
            p.drawText(QRectF(q.x() - 30, q.y() + 2, 60, 16), Qt.AlignmentFlag.AlignHCenter, "%.0f" % s)
        if self.current_station is not None:
            p.setPen(QPen(QColor("#ffd400"), 3))
            p.drawLine(self._map(outer, box, self.current_station, z0),
                       self._map(outer, box, self.current_station, z1))
        lx = outer.left() + 56
        for key, label, col, dashed in LONG_SERIES:
            pen = QPen(QColor(col), 2)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            pts = [(r.station, getattr(r, key)) for r in self.rows if getattr(r, key) is not None]
            for (s0, a), (s1, b) in zip(pts, pts[1:]):
                p.drawLine(self._map(outer, box, s0, a), self._map(outer, box, s1, b))
            for s0, a in pts:
                p.drawEllipse(self._map(outer, box, s0, a), 2.0, 2.0)
            p.drawLine(QPointF(lx, outer.top() + 14), QPointF(lx + 16, outer.top() + 14))
            p.drawText(QPointF(lx + 20, outer.top() + 18), tr(label))
            lx += 20 + p.fontMetrics().horizontalAdvance(tr(label)) + 14

    def mousePressEvent(self, event):  # noqa: N802
        box = self._box()
        if box is None:
            return
        pos = event.position() if hasattr(event, "position") else event.pos()
        r = QRectF(48, 8, max(self.width() - 56, 10), max(self.height() - 30, 10))
        x0, x1, _z0, _z1 = box
        self.stationClicked.emit(x0 + (pos.x() - r.left()) / r.width() * (x1 - x0))


class ProfileView(QDockWidget):
    """Dock with the section drawing (tab 1) and the point table with source (tab 2)."""

    profileChanged = pyqtSignal(str)
    pointMoved = pyqtSignal(str, int, float, float)
    codeChanged = pyqtSignal(str, int, str)
    dhmRemoved = pyqtSignal(str, str)

    COLUMN_TITLES = ("Offset", "Elevation", "Name", "Code", "Type", "Source", "Terrain model")
    COLUMNS = COLUMN_TITLES

    def __init__(self, parent=None):
        super().__init__(tr("Cross-section"), parent)
        self.setObjectName("GeoDrafterStreamSurveyProfileView")
        self.ids = []
        self.codes = []
        body = QWidget()
        v = QVBoxLayout(body)
        bar = QHBoxLayout()
        self.prev_button = QPushButton("◀")
        self.prev_button.setToolTip(tr("Previous section (upstream)"))
        self.next_button = QPushButton("▶")
        self.next_button.setToolTip(tr("Next section (downstream)"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(140)
        self.info = QLabel("")
        self.pick_button = QPushButton(tr("Pick on map"))
        self.pick_button.setToolTip(tr("Click a cross-section on the map to show it here."))
        self.pick_button.setCheckable(True)
        self.remove_left = QPushButton(tr("Remove terrain model left"))
        self.remove_right = QPushButton(tr("Remove terrain model right"))
        for w in (self.prev_button, self.combo, self.next_button, self.pick_button, self.info):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.remove_left)
        bar.addWidget(self.remove_right)
        v.addLayout(bar)
        self.tabs = QTabWidget()
        self.canvas = ProfileCanvas()
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(c) for c in self.COLUMNS])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.canvas, tr("Drawing"))
        self.tabs.addTab(self.table, tr("Points"))
        self.long = LongProfileCanvas()
        self.tabs.addTab(self.long, tr("Long profile"))
        self.long.stationClicked.connect(self._station_clicked)
        self.stations = {}
        v.addWidget(self.tabs, 1)
        self.setWidget(body)
        self.prev_button.clicked.connect(lambda: self.step(-1))
        self.next_button.clicked.connect(lambda: self.step(1))
        self.combo.currentIndexChanged.connect(self._combo_changed)
        self.canvas.pointMoved.connect(lambda i, o, z: self.pointMoved.emit(self.current(), i, o, z))
        self.canvas.codeRequested.connect(self._code_menu)
        self.remove_left.clicked.connect(lambda: self.dhmRemoved.emit(self.current(), "left"))
        self.remove_right.clicked.connect(lambda: self.dhmRemoved.emit(self.current(), "right"))

    def set_long_profile(self, rows):
        self.stations = {r.id: r.station for r in rows}
        self.long.set_rows(rows, self.stations.get(self.current()))

    def _station_clicked(self, station):
        if self.stations:
            pid = min(self.stations, key=lambda k: abs(self.stations[k] - station))
            self.select(pid)

    def set_profiles(self, ids, codes=()):
        cur = self.current()
        self.ids = list(ids)
        self.codes = list(codes)
        self.combo.blockSignals(True)
        self.combo.clear()
        for pid in self.ids:
            self.combo.addItem(pid, pid)
        self.combo.blockSignals(False)
        if cur in self.ids:
            self.combo.setCurrentIndex(self.ids.index(cur))

    def current(self):
        return self.combo.currentData() or ""

    def select(self, pid):
        if pid in self.ids:
            self.combo.setCurrentIndex(self.ids.index(pid))
            self.profileChanged.emit(pid)

    def step(self, d):
        if not self.ids:
            return
        i = max(0, min(len(self.ids) - 1, self.combo.currentIndex() + d))
        self.combo.setCurrentIndex(i)

    def _combo_changed(self, _i):
        pid = self.current()
        if pid:
            self.profileChanged.emit(pid)

    def show_profile(self, pid, station, points, water=None, status="", transition=0.0):
        self.info.setText(tr("Station %.1f  ·  %s") % (station, status or "–"))
        self.long.current_station = station
        self.long.update()
        self.canvas.set_data(points, water, transition)
        self.table.setRowCount(len(points))
        for r, e in enumerate(points):
            p = e.point
            vals = ("%.2f" % e.offset, "" if e.z is None else "%.3f" % e.z, p.name if p else "",
                    p.code if p else "", e.point_type, tr(SOURCE_LABELS.get(e.source, e.source)),
                    e.dhm_version)
            for c, val in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(val))
        self.prev_button.setEnabled(self.combo.currentIndex() > 0)
        self.next_button.setEnabled(0 <= self.combo.currentIndex() < len(self.ids) - 1)
        self.remove_left.setEnabled(any(e.source != "measured" and e.offset < 0 for e in points))
        self.remove_right.setEnabled(any(e.source != "measured" and e.offset > 0 for e in points))

    def _code_menu(self, index, global_pos):
        e = self.canvas.points[index]
        if e.point is None or not self.codes:
            return
        menu = QMenu(self)
        for code, label in self.codes:
            act = menu.addAction("%s  %s" % (code, label))
            act.setData(code)
        chosen = menu.exec(global_pos) if hasattr(menu, "exec") else menu.exec_(global_pos)
        if chosen is not None:
            self.codeChanged.emit(self.current(), index, chosen.data())
