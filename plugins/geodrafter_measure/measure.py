# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Geodesic distance, area and radius measurement on the ellipsoid.

Lengths and areas are always computed on the ellipsoid (the project's, or
WGS84 when the project has none), never in the planar map units, so results
match geodrafter.com's web tools whatever the map projection.
"""

import math

from qgis.PyQt.QtCore import Qt, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QColor, QDesktopServices, QGuiApplication
from qgis.PyQt.QtWidgets import (
    QButtonGroup, QComboBox, QDockWidget, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QRadioButton, QWidget,
)
from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDistanceArea,
    QgsFeature, QgsField, QgsFields, QgsGeometry, QgsMemoryProviderUtils,
    QgsPointXY, QgsProject,
)
from qgis.gui import QgsMapTool, QgsRubberBand

from . import units


def _field(name, kind):
    """QgsField with QMetaType (QGIS >= 3.38, required on QGIS 4) or QVariant (older)."""
    try:
        from qgis.PyQt.QtCore import QMetaType
        return QgsField(name, QMetaType.Type.Double if kind == "double" else QMetaType.Type.QString)
    except (TypeError, AttributeError):
        from qgis.PyQt.QtCore import QVariant
        return QgsField(name, QVariant.Double if kind == "double" else QVariant.String)


DISTANCE, AREA, RADIUS = "distance", "area", "radius"
CIRCLE_SEGMENTS = 120
WGS84 = "EPSG:4326"
LINE_LAYER_NAME = "GeoDrafter distances"
AREA_LAYER_NAME = "GeoDrafter areas"


class MeasureEngine:
    """Geodesic calculations for points given in ``crs`` (testable without GUI)."""

    def __init__(self, crs, project=None):
        self.project = project or QgsProject.instance()
        self.set_crs(crs)

    def set_crs(self, crs):
        self.crs = crs
        self.da = QgsDistanceArea()
        self.da.setSourceCrs(crs, self.project.transformContext())
        ellipsoid = self.project.ellipsoid()
        if not ellipsoid or ellipsoid.upper() == "NONE":
            ellipsoid = "EPSG:7030"   # WGS84
        self.da.setEllipsoid(ellipsoid)
        self.ellipsoid = ellipsoid
        self._to_ll = QgsCoordinateTransform(crs, QgsCoordinateReferenceSystem(WGS84), self.project)
        self._from_ll = QgsCoordinateTransform(QgsCoordinateReferenceSystem(WGS84), crs, self.project)

    def _metres(self, value):
        return self.da.convertLengthMeasurement(value, Qgis.DistanceUnit.Meters)

    def _square_metres(self, value):
        return self.da.convertAreaMeasurement(value, Qgis.AreaUnit.SquareMeters)

    def segment_lengths(self, points):
        return [self._metres(self.da.measureLine(a, b)) for a, b in zip(points, points[1:])]

    def line_length(self, points):
        return sum(self.segment_lengths(points))

    def polygon_area(self, points):
        if len(points) < 3:
            return 0.0
        return self._square_metres(self.da.measurePolygon(list(points) + [points[0]]))

    def polygon_perimeter(self, points):
        if len(points) < 3:
            return self.line_length(points)
        return self.line_length(list(points) + [points[0]])

    def bearing(self, a, b):
        """Initial geodesic bearing a -> b in degrees (0–360)."""
        deg = math.degrees(self.da.bearing(a, b)) % 360
        return 0.0 if deg > 360 - 1e-9 else deg

    def circle(self, centre, radius_m, segments=CIRCLE_SEGMENTS):
        """Geodesic circle (points in ``crs``) – every vertex exactly radius_m from centre."""
        c_ll = self._to_ll.transform(centre)
        wgs = QgsDistanceArea()
        wgs.setSourceCrs(QgsCoordinateReferenceSystem(WGS84), self.project.transformContext())
        wgs.setEllipsoid(self.ellipsoid)
        ring = []
        for i in range(segments):
            p_ll = wgs.computeSpheroidProject(c_ll, radius_m, 2 * math.pi * i / segments)
            ring.append(self._from_ll.transform(p_ll))
        return ring

    def radius_between(self, centre, edge):
        return self._metres(self.da.measureLine(centre, edge))


class Measurement:
    """One finished or in-progress measurement."""

    def __init__(self, mode):
        self.mode = mode
        self.points = []
        self.radius_m = None
        self.fixed_radius = False

    def geometry(self, engine):
        if self.mode == DISTANCE and len(self.points) >= 2:
            return QgsGeometry.fromPolylineXY(self.points)
        if self.mode == AREA and len(self.points) >= 3:
            return QgsGeometry.fromPolygonXY([self.points + [self.points[0]]])
        if self.mode == RADIUS and self.points and self.radius_m:
            ring = engine.circle(self.points[0], self.radius_m)
            return QgsGeometry.fromPolygonXY([ring + [ring[0]]])
        return None

    def values(self, engine):
        """dict with length_m / area_m2 / perimeter_m / radius_m as applicable."""
        if self.mode == DISTANCE:
            segs = engine.segment_lengths(self.points)
            return {"length_m": sum(segs), "segments_m": segs}
        if self.mode == AREA:
            return {"area_m2": engine.polygon_area(self.points),
                    "perimeter_m": engine.polygon_perimeter(self.points)}
        r = self.radius_m or 0.0
        out = {"radius_m": r}
        if r and self.points:
            ring = engine.circle(self.points[0], r)
            out["area_m2"] = engine.polygon_area(ring)
            out["perimeter_m"] = engine.polygon_perimeter(ring)
        return out


def describe(mode, values, length_unit=None, area_unit=None, imperial=False):
    """Human-readable summary lines for the dock and the layer's label field."""
    lu = length_unit
    au = area_unit
    lines = []
    if mode == DISTANCE:
        total = values.get("length_m", 0.0)
        lines.append("Distance: " + units.fmt_length(total, lu or units.auto_length_unit(total, imperial)))
        segs = values.get("segments_m", [])
        if len(segs) > 1:
            for i, s in enumerate(segs, 1):
                lines.append("  %d: %s" % (i, units.fmt_length(s, lu or units.auto_length_unit(s, imperial))))
    else:
        if mode == RADIUS:
            r = values.get("radius_m", 0.0)
            lines.append("Radius: " + units.fmt_length(r, lu or units.auto_length_unit(r, imperial)))
        a = values.get("area_m2", 0.0)
        p = values.get("perimeter_m", 0.0)
        lines.append("Area: " + units.fmt_area(a, au or units.auto_area_unit(a, imperial)))
        lines.append(("Circumference: " if mode == RADIUS else "Perimeter: ")
                     + units.fmt_length(p, lu or units.auto_length_unit(p, imperial)))
    return lines


def measurement_fields():
    fields = QgsFields()
    for name, kind in (("kind", "string"), ("length_m", "double"), ("area_m2", "double"),
                       ("radius_m", "double"), ("label", "string")):
        fields.append(_field(name, kind))
    return fields


def layer_name(mode):
    return LINE_LAYER_NAME if mode == DISTANCE else AREA_LAYER_NAME


def measurements_layer(project, crs, mode, create=True):
    """The project's memory layer for this kind of measurement (lines or areas)."""
    name = layer_name(mode)
    for lyr in project.mapLayersByName(name):
        if lyr.providerType() == "memory" and lyr.crs() == crs:
            return lyr
    if not create:
        return None
    wkb = Qgis.WkbType.LineString if mode == DISTANCE else Qgis.WkbType.Polygon
    layer = QgsMemoryProviderUtils.createMemoryLayer(name, measurement_fields(), wkb, crs)
    project.addMapLayer(layer)
    return layer


def add_to_layer(layer, measurement, engine, label):
    geom = measurement.geometry(engine)
    if geom is None:
        return None
    vals = measurement.values(engine)
    f = QgsFeature(layer.fields())
    f.setGeometry(geom)
    f["kind"] = measurement.mode
    f["length_m"] = vals.get("length_m", vals.get("perimeter_m"))
    f["area_m2"] = vals.get("area_m2")
    f["radius_m"] = vals.get("radius_m")
    f["label"] = label
    ok = layer.dataProvider().addFeatures([f])[0]
    layer.updateExtents()
    layer.triggerRepaint()
    return f if ok else None


class MeasureTool(QgsMapTool):
    """Left click adds a point, right click / Enter / double click finishes, Esc clears.

    Radius mode: first click = centre, mouse move = radius, second click finishes.
    With a typed radius, a single click places the circle.
    """

    changed = pyqtSignal()
    finished = pyqtSignal(object)   # Measurement

    def __init__(self, canvas):
        super().__init__(canvas)
        self.engine = MeasureEngine(canvas.mapSettings().destinationCrs())
        self.mode = DISTANCE
        self.fixed_radius_m = None
        self.current = Measurement(self.mode)
        self.hover = None
        self.band = QgsRubberBand(canvas, Qgis.GeometryType.Polygon)
        self.band.setStrokeColor(QColor(255, 106, 0, 230))
        self.band.setFillColor(QColor(255, 106, 0, 50))
        self.band.setWidth(2)
        canvas.destinationCrsChanged.connect(self._crs_changed)

    def _crs_changed(self):
        self.engine.set_crs(self.canvas().mapSettings().destinationCrs())
        self.clear()

    def set_mode(self, mode, fixed_radius_m=None):
        self.mode = mode
        self.fixed_radius_m = fixed_radius_m if mode == RADIUS else None
        self.clear()

    def clear(self):
        self.current = Measurement(self.mode)
        self.hover = None
        self.band.reset(Qgis.GeometryType.Polygon)
        self.changed.emit()

    def preview(self):
        """The measurement including the point under the cursor."""
        m = Measurement(self.mode)
        m.points = list(self.current.points)
        m.radius_m = self.current.radius_m
        if self.mode == RADIUS:
            if m.points and self.fixed_radius_m:
                m.radius_m = self.fixed_radius_m
            elif m.points and self.hover is not None:
                m.radius_m = self.engine.radius_between(m.points[0], self.hover)
            elif not m.points and self.hover is not None and self.fixed_radius_m:
                m.points = [self.hover]
                m.radius_m = self.fixed_radius_m
        elif self.hover is not None:
            m.points.append(self.hover)
        return m

    def _redraw(self):
        m = self.preview()
        geom = m.geometry(self.engine)
        if geom is None and len(m.points) == 2:
            geom = QgsGeometry.fromPolylineXY(m.points)
        if geom is None:
            self.band.reset(Qgis.GeometryType.Polygon)
        else:
            kind = Qgis.GeometryType.Line if self.mode == DISTANCE else Qgis.GeometryType.Polygon
            self.band.reset(kind)
            self.band.setToGeometry(geom, None)
        self.changed.emit()

    # -- events (thin wrappers around add_point / move / finish for testing) --

    def canvasMoveEvent(self, e):  # noqa: N802
        self.move(QgsPointXY(self.toMapCoordinates(e.pos())))

    def canvasReleaseEvent(self, e):  # noqa: N802
        point = QgsPointXY(self.toMapCoordinates(e.pos()))
        if e.button() == Qt.MouseButton.LeftButton:
            self.add_point(point)
        elif e.button() == Qt.MouseButton.RightButton:
            self.finish()

    def canvasDoubleClickEvent(self, e):  # noqa: N802
        self.finish()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.clear()
            e.ignore()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish()
            e.ignore()
        elif e.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            if self.current.points:
                self.current.points.pop()
                self._redraw()
            e.ignore()

    def move(self, point):
        self.hover = point
        self._redraw()

    def add_point(self, point):
        if self.mode == RADIUS:
            if not self.current.points:
                self.current.points = [point]
                if self.fixed_radius_m:
                    self.current.radius_m = self.fixed_radius_m
                    self.current.fixed_radius = True
                    self.finish()
                    return
            else:
                self.current.radius_m = self.engine.radius_between(self.current.points[0], point)
                self.finish()
                return
        else:
            if self.current.points and self.current.points[-1] == point:
                return   # second click of a double click
            self.current.points.append(point)
        self._redraw()

    def finish(self):
        m = self.current
        if m.geometry(self.engine) is None:
            return None
        self.finished.emit(m)
        self.current = Measurement(self.mode)
        self.hover = None
        return m

    def deactivate(self):
        super().deactivate()

    def cleanup(self):
        try:
            self.canvas().destinationCrsChanged.disconnect(self._crs_changed)
        except (TypeError, RuntimeError):
            pass
        self.band.reset(Qgis.GeometryType.Polygon)


class MeasureDock(QDockWidget):
    modeChanged = pyqtSignal(str, object)   # mode, fixed radius (m) or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GeoDrafterMeasureDock")
        self.setWindowTitle(self.tr("GeoDrafter Measure"))
        body = QWidget(self)
        grid = QGridLayout(body)
        self.setWidget(body)

        modes = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for mode, text in ((DISTANCE, "Distance"), (AREA, "Area"), (RADIUS, "Radius")):
            b = QRadioButton(self.tr(text), body)
            self.mode_group.addButton(b)
            self.mode_buttons[mode] = b
            modes.addWidget(b)
        self.mode_buttons[DISTANCE].setChecked(True)
        grid.addLayout(modes, 0, 0, 1, 2)

        grid.addWidget(QLabel(self.tr("Fixed radius"), body), 1, 0)
        self.radius_edit = QLineEdit(body)
        self.radius_edit.setPlaceholderText(self.tr("e.g. 5 km – empty: drag with the mouse"))
        self.radius_edit.editingFinished.connect(self._emit_mode)
        for b in self.mode_buttons.values():
            b.toggled.connect(self._emit_mode)
        grid.addWidget(self.radius_edit, 1, 1)

        grid.addWidget(QLabel(self.tr("Units"), body), 2, 0)
        self.unit_combo = QComboBox(body)
        self.unit_combo.addItem(self.tr("Metric (auto)"), "metric")
        self.unit_combo.addItem(self.tr("Imperial (auto)"), "imperial")
        for key, (label, _f) in units.LENGTH_UNITS.items():
            self.unit_combo.addItem(label, "L:" + key)
        for key, (label, _f) in units.AREA_UNITS.items():
            self.unit_combo.addItem(label, "A:" + key)
        grid.addWidget(self.unit_combo, 2, 1)

        self.result = QPlainTextEdit(body)
        self.result.setReadOnly(True)
        self.result.setMinimumHeight(90)
        grid.addWidget(self.result, 3, 0, 1, 2)

        self.ellipsoid_label = QLabel(body)
        self.ellipsoid_label.setWordWrap(True)
        grid.addWidget(self.ellipsoid_label, 4, 0, 1, 2)

        row1 = QHBoxLayout()
        self.copy_button = QPushButton(self.tr("Copy"), body)
        self.copy_button.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.result.toPlainText()))
        self.keep_button = QPushButton(self.tr("Keep on map"), body)
        self.keep_button.setToolTip(self.tr(
            "Add finished measurements to the 'GeoDrafter distances' / 'GeoDrafter areas' layers"))
        self.keep_button.setCheckable(True)
        self.keep_button.setChecked(True)
        self.clear_button = QPushButton(self.tr("Clear"), body)
        for b in (self.copy_button, self.keep_button, self.clear_button):
            row1.addWidget(b)
        grid.addLayout(row1, 5, 0, 1, 2)

        row2 = QHBoxLayout()
        self.export_button = QPushButton(self.tr("Export…"), body)
        self.export_button.setToolTip(self.tr("Save the measurement layers to a GeoPackage"))
        self.share_button = QPushButton(self.tr("Share as web map…"), body)
        self.web_button = QPushButton(self.tr("Web tool…"), body)
        self.web_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(units.TOOL_URLS[self.mode()])))
        for b in (self.export_button, self.share_button, self.web_button):
            row2.addWidget(b)
        grid.addLayout(row2, 6, 0, 1, 2)
        grid.setRowStretch(7, 1)
        self._update_radius_enabled()

    def mode(self):
        for mode, b in self.mode_buttons.items():
            if b.isChecked():
                return mode
        return DISTANCE

    def fixed_radius(self):
        if self.mode() != RADIUS:
            return None
        return units.parse_length(self.radius_edit.text())

    def units_choice(self):
        """(length_unit or None, area_unit or None, imperial)"""
        data = self.unit_combo.currentData() or "metric"
        if data.startswith("L:"):
            return data[2:], None, False
        if data.startswith("A:"):
            return None, data[2:], False
        return None, None, data == "imperial"

    def _update_radius_enabled(self):
        self.radius_edit.setEnabled(self.mode() == RADIUS)

    def _emit_mode(self, *_):
        sender = self.sender()
        if isinstance(sender, QRadioButton) and not sender.isChecked():
            return   # only react to the button that became checked
        self._update_radius_enabled()
        self.modeChanged.emit(self.mode(), self.fixed_radius())

    def show_lines(self, lines):
        self.result.setPlainText("\n".join(lines))
