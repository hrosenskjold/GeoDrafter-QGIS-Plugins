# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2024-2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Pro Trace – draw by following the edges of existing layers.

Click once on the network, move the mouse on, and the shortest path along the
visible line and polygon layers is drawn as a preview – ArcGIS Pro-style
tracing. Snapping uses the tool's own engine (vertices and edges of all
visible layers), not the project's snapping settings, so tracing also works
when the project only snaps to the active layer.

Ported to QGIS 4 (Qt6) from Henrik Rosenskjold's own trace tool: scoped Qt
and QGIS enums only, so the same code runs on QGIS 3.40 and 4.x.
"""

import math

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QApplication

from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsCsException,
    QgsFeature,
    QgsFeatureRequest,
    QgsFields,
    QgsGeometry,
    QgsLineString,
    QgsMemoryProviderUtils,
    QgsPoint,
    QgsPointLocator,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsSnappingConfig,
    QgsSnappingUtils,
    QgsTracer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapToolAdvancedDigitizing, QgsRubberBand, QgsSnapIndicator

LINE = Qgis.GeometryType.Line
POLYGON = Qgis.GeometryType.Polygon


def tr(text):
    return QCoreApplication.translate("GeoDrafterProTrace", text)


def truncate_polyline(points, pos):
    """The first ``pos`` map units of a polyline, as a point list."""
    out = [points[0]]
    walked = 0.0
    for a, b in zip(points, points[1:]):
        piece = math.hypot(b.x() - a.x(), b.y() - a.y())
        if piece and walked + piece >= pos:
            t_ = (pos - walked) / piece
            p = QgsPointXY(a.x() + t_ * (b.x() - a.x()), a.y() + t_ * (b.y() - a.y()))
            if p != out[-1]:
                out.append(p)
            return out
        out.append(b)
        walked += piece
    return out


class TraceTool(QgsMapToolAdvancedDigitizing):
    """Map tool that traces along existing lines and polygon edges.

    Usage:

      * Click once on a line to set the start point.
      * Move the mouse along the line. The trace follows the cursor step by
        step and is remembered – it is not lost when the cursor briefly slips
        off the line. Moving back pulls the trace in again.
      * Off the network, the preview shows the trace plus a dashed straight
        tail to the cursor.
      * Left click locks the trace. A click off the network adds a freehand
        vertex – that is how tracing and freehand drawing are mixed.
      * Enter or right click saves the feature. The freehand tail is not
        included; only a click adds a free vertex.
      * Backspace first drops the unlocked trace after the last click, then
        one locked vertex at a time. Esc discards everything.

    With ``mode="split"`` the finished line is not saved as a feature but cuts
    the features of the active layer it crosses (only the selected ones when
    there is a selection), like QGIS' Split Features tool – one undo step.

    Why step by step: computing the shortest path from the last click on every
    mouse move makes a long, winding stream jump to a road or parcel boundary
    that is more direct, and nothing was remembered in between.
    """

    #: Maximum number of features the tracing network is built from.
    MAX_FEATURES = 30000
    #: The network covers a bit more than the visible extent.
    EXTENT_MARGIN = 1.5
    #: Snapping distance in screen pixels.
    SNAP_TOLERANCE_PX = 12

    def __init__(self, iface, mode="draw"):
        if mode not in ("draw", "split"):
            raise ValueError("mode must be 'draw' or 'split'")
        canvas = iface.mapCanvas()
        super().__init__(canvas, iface.cadDockWidget())
        self.iface = iface
        self.canvas = canvas
        self.mode = mode

        # The network traced along: visible lines and polygon edges in the
        # extent, noded at intersections. See _build_network.
        self.net = QgsMemoryProviderUtils.createMemoryLayer(
            "GeoDrafter tracing network", QgsFields(), Qgis.WkbType.LineString,
            canvas.mapSettings().destinationCrs())
        self.net_finder = None        # QgsPointLocator on the network
        self._net_extent = None       # extent the network covers
        self._net_stale = True
        self._failed_need = None      # extent where building failed
        self._source_layers = []      # layers whose edits make the network stale

        self.tracer = QgsTracer()
        self.tracer.setLayers([self.net])

        # Own snapping engine, independent of the project's snapping settings.
        self.snap = QgsSnappingUtils()
        config = QgsSnappingConfig()
        config.setEnabled(True)
        config.setMode(Qgis.SnappingMode.AllLayers)
        types_ = Qgis.SnappingType.Vertex | Qgis.SnappingType.Segment
        try:
            config.setTypeFlag(types_)
        except TypeError:  # PyQt5 builds turn the OR into a plain int
            config.setTypeFlag(Qgis.SnappingTypes(types_))
        config.setTolerance(self.SNAP_TOLERANCE_PX)
        config.setUnits(Qgis.MapToolUnit.Pixels)
        self.snap.setConfig(config)

        self.layer = None
        self.geometry_kind = None     # "line" or "polygon"
        self.points = []              # locked vertices, map CRS
        # The trace after the last click. Starts at points[-1] and follows the
        # cursor; locked on the next click or when finishing.
        self.trace = []
        # Cursor is off the network: the preview gets a straight tail.
        self._free_tail = False
        self._last_point = None       # last snapped cursor position
        self._cursor = None           # cursor position before snapping
        # "Cannot trace here" is reported once per extent, not on every move.
        self._reported = False

        # Orange when drawing, red when the line will cut features.
        locked, preview = ((QColor(255, 80, 0, 220), QColor(255, 140, 0, 200)) if mode == "draw"
                           else (QColor(215, 25, 60, 230), QColor(235, 70, 100, 210)))
        self.band_locked = QgsRubberBand(canvas, LINE)
        self.band_locked.setColor(locked)
        self.band_locked.setWidth(3)

        self.band_preview = QgsRubberBand(canvas, LINE)
        self.band_preview.setColor(preview)
        self.band_preview.setLineStyle(Qt.PenStyle.DashLine)
        self.band_preview.setWidth(3)

        self.snap_indicator = QgsSnapIndicator(canvas)

        for signal, slot in self._canvas_signals():
            signal.connect(slot)

    def _canvas_signals(self):
        return (
            (self.canvas.extentsChanged, self._canvas_moved),
            (self.canvas.layersChanged, self._layers_changed),
            (self.canvas.destinationCrsChanged, self._layers_changed),
        )

    def cleanup(self):
        """Called when the plugin is unloaded."""
        for signal, slot in self._canvas_signals():
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._disconnect_sources()
        self.tracer.setLayers([])
        self.net_finder = None
        self.band_locked.reset(LINE)
        self.band_preview.reset(LINE)

    # ------------------------------------------------------------------
    # activation
    # ------------------------------------------------------------------

    def activate(self):
        super().activate()
        layer = self.iface.activeLayer()
        ok, kind = self.layer_kind(layer)
        if not ok:
            if self.mode == "draw":
                self._tell(tr("First select the layer to draw in – a line or polygon layer."))
            else:
                self._tell(tr("First select the layer to split – a line or polygon layer."))
            self.canvas.unsetMapTool(self)
            return
        if not layer.isEditable() and not layer.startEditing():
            self._tell(tr('Layer "{}" could not be put in edit mode.').format(layer.name()))
            self.canvas.unsetMapTool(self)
            return
        self.layer = layer
        self.geometry_kind = kind
        self._reset_sketch()
        self._net_stale = True
        self._canvas_moved()

    def deactivate(self):
        self._reset_sketch()
        self.layer = None
        self.geometry_kind = None
        super().deactivate()

    def _tell(self, message):
        self.iface.messageBar().pushMessage(
            "GeoDrafter Pro Trace", message, level=Qgis.MessageLevel.Warning, duration=6)

    def _report(self, message):
        if not self._reported:
            self._reported = True
            self._tell(message)

    @staticmethod
    def layer_kind(layer):
        if layer is None or not hasattr(layer, "wkbType"):
            return False, None
        geometry = QgsWkbTypes.geometryType(layer.wkbType())
        if geometry == LINE:
            return True, "line"
        if geometry == POLYGON:
            return True, "polygon"
        return False, None

    # ------------------------------------------------------------------
    # tracing network
    # ------------------------------------------------------------------

    def traceable_layers(self):
        """Line and polygon layers that are switched on in the Layers panel (layer and its groups)
        and shown at the current scale – the layers drawn on the map. Only these are traced
        (Henrik 17/10). The canvas layer set follows the Layers panel check boxes."""
        scale = self.canvas.scale()
        layers = []
        for lyr in self.canvas.layers():
            if not hasattr(lyr, "wkbType"):
                continue
            if QgsWkbTypes.geometryType(lyr.wkbType()) not in (LINE, POLYGON):
                continue
            if lyr.hasScaleBasedVisibility() and not lyr.isInScaleRange(scale):
                continue
            layers.append(lyr)
        return layers

    def _canvas_moved(self):
        # Pixel snapping tolerance is converted to map units from the extent.
        self.snap.setMapSettings(self.canvas.mapSettings())
        self._reported = False
        # Zooming past a layer's scale range shows or hides it: rebuild the network then.
        if self.net_finder is not None:
            if {lyr.id() for lyr in self.traceable_layers()} != {lyr.id() for lyr in self._source_layers}:
                self._mark_stale()

    def _layers_changed(self, *_):
        # A layer switched on or off in the Layers panel: snap to and trace the new set at once,
        # not only after the next pan or zoom.
        self.snap.setMapSettings(self.canvas.mapSettings())
        self._mark_stale()

    def _mark_stale(self, *_):
        self._net_stale = True

    def _disconnect_sources(self):
        for lyr in self._source_layers:
            try:
                lyr.layerModified.disconnect(self._mark_stale)
                lyr.dataChanged.disconnect(self._mark_stale)
            except (TypeError, RuntimeError):
                pass
        self._source_layers = []

    def _ensure_network(self):
        """Make sure the network covers the screen and the end of the trace."""
        need = self.canvas.extent()
        end = self.trace[-1] if self.trace else (self.points[-1] if self.points else None)
        if end is not None:
            need.combineExtentWith(end.x(), end.y())

        if not self._net_stale:
            if self._net_extent is not None and self._net_extent.contains(need):
                return
            if self._failed_need is not None and self._failed_need == need:
                return        # do not retry on every mouse move

        extent = QgsRectangle(need)
        extent.scale(self.EXTENT_MARGIN)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok = self._build_network(extent)
        finally:
            QApplication.restoreOverrideCursor()
        self._net_stale = False
        self._net_extent = extent if ok else None
        self._failed_need = None if ok else QgsRectangle(need)

    def _build_network(self, extent):
        """Build the network for ``extent`` (map CRS). False if not possible.

        QgsTracer nodes lines itself with GEOS but does not check the result;
        when GEOS gives up (nearly coincident lines) the graph is empty and
        nothing can be traced. So lines are noded here first with unaryUnion,
        and both tracing and snapping use the result.
        """
        project = QgsProject.instance()
        map_crs = self.canvas.mapSettings().destinationCrs()
        self._disconnect_sources()
        self.net_finder = None
        self.net.dataProvider().truncate()
        self.tracer.invalidateGraph()

        geometries = []
        count = 0
        for lyr in self.traceable_layers():
            lyr.layerModified.connect(self._mark_stale)
            lyr.dataChanged.connect(self._mark_stale)
            self._source_layers.append(lyr)

            to_map = None
            layer_extent = extent
            if lyr.crs() != map_crs:
                to_map = QgsCoordinateTransform(lyr.crs(), map_crs, project)
                try:
                    layer_extent = QgsCoordinateTransform(
                        map_crs, lyr.crs(), project).transformBoundingBox(extent)
                except QgsCsException:
                    continue

            request = QgsFeatureRequest().setFilterRect(layer_extent).setNoAttributes()
            for feature in lyr.getFeatures(request):
                count += 1
                if count > self.MAX_FEATURES:
                    self._report(tr(
                        "There are more than {:,} features in view, so tracing is off. "
                        "Zoom in, or hide heavy layers such as parcels – all visible "
                        "line and polygon layers count.").format(self.MAX_FEATURES))
                    return False
                geom = self.as_lines(feature.geometry())
                if geom is None:
                    continue
                if to_map is not None:
                    try:
                        geom.transform(to_map)
                    except QgsCsException:
                        continue
                geometries.append(geom)

        if not geometries:
            return True       # nothing to trace here – not an error

        parts = [p for p in self.node_lines(geometries, map_crs).asGeometryCollection()
                 if not p.isEmpty()]
        features = []
        for part in parts:
            f = QgsFeature()
            f.setGeometry(part)
            features.append(f)
        self.net.setCrs(map_crs)
        self.net.dataProvider().addFeatures(features)
        self.net.updateExtents()
        self.net_finder = QgsPointLocator(self.net)
        self.tracer.setDestinationCrs(map_crs, project.transformContext())
        self.tracer.invalidateGraph()

        if parts and not self.tracer.isPointSnapped(QgsPointXY(parts[0].vertexAt(0))):
            self._report(tr(
                "The lines in view could not be joined into a network, so tracing is "
                "off here. This happens when lines lie almost on top of each other – "
                "hide those layers or zoom elsewhere."))
            return False
        return True

    @staticmethod
    def as_lines(geom):
        """The geometry as 2D lines: lines as they are, polygons as their edges."""
        if geom is None or geom.isNull() or geom.isEmpty():
            return None
        if QgsWkbTypes.isCurvedType(geom.wkbType()):
            geom.convertToStraightSegment()
        kind = QgsWkbTypes.geometryType(geom.wkbType())
        if kind == POLYGON:
            edge = geom.constGet().boundary()
            if edge is None:
                return None
            geom = QgsGeometry(edge)
        elif kind != LINE:
            return None
        abstract = geom.get()
        abstract.dropZValue()
        abstract.dropMValue()
        return geom

    @staticmethod
    def node_lines(geometries, crs):
        """The lines noded at every intersection (unaryUnion, then grid snap, then as-is)."""
        collected = QgsGeometry.collectGeometry(geometries)
        grid = 1e-9 if crs.isGeographic() else 1e-4
        for attempt in (
                lambda: QgsGeometry.unaryUnion(geometries),
                lambda: collected.snappedToGrid(grid, grid).node()):
            noded = attempt()
            if noded is not None and not noded.isNull() and not noded.isEmpty():
                return noded
        return collected

    def _trace_path(self, start, end):
        """Shortest path along the network, or None."""
        if start == end:
            return None
        self._ensure_network()
        if self.net_finder is None:
            return None
        points, error = self.tracer.findShortestPath(start, end)
        if error == QgsTracer.PathError.ErrNone and points:
            return list(points)
        return None

    def _resolve_point(self, e):
        """Cursor position – snapped with the own engine, then moved onto the network."""
        map_point = QgsPointXY(e.originalMapPoint())
        return self.resolve_map_point(map_point)

    def resolve_map_point(self, map_point):
        self._cursor = map_point
        match = self.snap.snapToMap(map_point)
        if match.isValid() and match.layer() is not None and \
                match.layer().id() not in {lyr.id() for lyr in self.traceable_layers()}:
            match = QgsPointLocator.Match()  # never snap to a layer that is switched off
        self.snap_indicator.setMatch(match)
        point = QgsPointXY(match.point()) if match.isValid() else map_point
        return self._on_network(point) or point

    def _on_network(self, point):
        self._ensure_network()
        if self.net_finder is None:
            return None
        tolerance = self.canvas.mapUnitsPerPixel()
        match = self.net_finder.nearestVertex(point, tolerance)
        if not match.isValid():
            match = self.net_finder.nearestEdge(point, tolerance)
        return QgsPointXY(match.point()) if match.isValid() else None

    def _neighbours(self, cursor):
        """Nearest point on each network piece within the snapping distance."""
        if self.net_finder is None:
            return []
        r = self.canvas.mapUnitsPerPixel() * self.SNAP_TOLERANCE_PX
        rect = QgsRectangle(cursor.x() - r, cursor.y() - r, cursor.x() + r, cursor.y() + r)
        pieces = {m.featureId() for m in self.net_finder.edgesInRect(rect)}
        cursor_geom = QgsGeometry.fromPointXY(cursor)
        out = []
        for fid in pieces:
            geom = self.net.getFeature(fid).geometry()
            point = geom.nearestPoint(cursor_geom).asPoint()
            if point.distance(cursor) <= r:
                out.append(QgsPointXY(point))
        return out

    # ------------------------------------------------------------------
    # mouse and keyboard
    # ------------------------------------------------------------------

    def cadCanvasMoveEvent(self, e):
        self.handle_move(self._resolve_point(e))

    def handle_move(self, point):
        self._last_point = point
        if not self.points:
            self.band_preview.reset(LINE)
            return
        self._follow(point)
        self._show_preview(point)

    def cadCanvasPressEvent(self, e):
        if self.layer is None:
            return
        point = self._resolve_point(e)
        if e.button() == Qt.MouseButton.RightButton:
            self.handle_click(point, finish=True)
        elif e.button() == Qt.MouseButton.LeftButton:
            self.handle_click(point)

    def handle_click(self, point, finish=False):
        self._last_point = point
        if finish:
            if self.points:
                self._follow(point)
                self._lock_trace()
            self._finish_sketch()
            return
        if not self.points:
            self.points = [point]
            self.trace = [point]
            self._free_tail = False
        else:
            self._follow(point)
            # A click off the network is a free vertex.
            self._lock_trace(point if self._free_tail else None)
        self._update_band()
        self.band_preview.reset(LINE)

    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key.Key_Escape:
            self._reset_sketch()
            e.ignore()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.points:
                self._lock_trace()
            self._finish_sketch()
            e.ignore()
            return
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.undo_step()
            e.ignore()
            return
        super().keyPressEvent(e)

    def undo_step(self):
        if len(self.trace) > 1:
            # First the unlocked trace after the last click.
            self.trace = [self.points[-1]]
            self._free_tail = False
        elif self.points:
            self.points.pop()
            self.trace = [self.points[-1]] if self.points else []
            self._free_tail = False
        self._update_band()
        if self._last_point is not None and self.points:
            self._show_preview(self._last_point)
        else:
            self.band_preview.reset(LINE)

    # ------------------------------------------------------------------
    # the trace
    # ------------------------------------------------------------------

    def _tolerance(self):
        """How close to the trace the cursor must be to pull it back (map units)."""
        return max(self.canvas.mapUnitsPerPixel() * 2.0, 1e-9)

    def _follow(self, point):
        """Advance the trace towards the cursor – or pull it back.

        Candidates are the snapped ``point`` and the nearest point on each
        network piece within the snapping distance. For each candidate: on the
        trace before its end -> the user moved back, truncate; at the end ->
        stay; otherwise trace from the end to it. Cost is the distance to the
        cursor plus the detour, which makes the trace sticky: a closer line
        that can only be reached by a detour does not steal the trace. With no
        candidate (cursor off the network) the trace stays and the preview
        gets a free tail.
        """
        if not self.trace:
            return
        tol = self._tolerance()
        cursor = self._cursor if self._cursor is not None else point
        end = self.trace[-1]
        line = QgsGeometry.fromPolylineXY(self.trace) if len(self.trace) >= 2 else None
        max_detour = self.canvas.mapUnitsPerPixel() * 25

        best = None                   # (cost, action, data)
        for candidate in [point] + self._neighbours(cursor):
            choice = None
            distance = cursor.distance(candidate)
            pg = QgsGeometry.fromPointXY(candidate)
            if candidate.distance(end) <= tol:
                choice = (distance, "stay", None)
            elif line is not None and line.distance(pg) <= tol:
                pos = line.lineLocatePoint(pg)
                if pos < line.length() - tol:
                    choice = (distance, "back", pos)
            if choice is None:
                path = self._trace_path(end, candidate)
                if not path:
                    continue
                straight = end.distance(candidate)
                detour = QgsGeometry.fromPolylineXY(path).length() - straight
                if detour > 3 * straight + max_detour:
                    continue
                choice = (distance + detour, "forward", path)
            if best is None or choice[0] < best[0]:
                best = choice

        if best is None:
            self._free_tail = point.distance(end) > tol
            return
        _cost, action, data = best
        if action == "back":
            self.trace = truncate_polyline(self.trace, data)
        elif action == "forward":
            # The old end usually lies mid-piece on the segment the trace now
            # continues along – then it is a redundant vertex.
            if len(self.trace) >= 2 and QgsGeometry.fromPolylineXY(
                    [self.trace[-2], data[1]]).distance(
                    QgsGeometry.fromPointXY(end)) <= tol / 200:
                self.trace.pop()
            self.trace.extend(data[1:])
        self._free_tail = False

    def _lock_trace(self, free_point=None):
        """Lock the trace – and optionally a free vertex after it."""
        if not self.points:
            return
        self.points.extend(self.trace[1:])
        if free_point is not None and free_point != self.points[-1]:
            self.points.append(free_point)
        self.trace = [self.points[-1]]
        self._free_tail = False

    def _show_preview(self, point):
        show = list(self.trace)
        if self._free_tail and (not show or point != show[-1]):
            show.append(point)
        if len(show) >= 2:
            self.band_preview.setToGeometry(QgsGeometry.fromPolylineXY(show), None)
        else:
            self.band_preview.reset(LINE)

    # ------------------------------------------------------------------
    # the sketch
    # ------------------------------------------------------------------

    def _update_band(self):
        if len(self.points) >= 2:
            self.band_locked.setToGeometry(QgsGeometry.fromPolylineXY(self.points), None)
        else:
            self.band_locked.reset(LINE)

    def _reset_sketch(self):
        self.points = []
        self.trace = []
        self._free_tail = False
        self._last_point = None
        self._reported = False
        self.band_locked.reset(LINE)
        self.band_preview.reset(LINE)

    def sketch_geometry(self):
        """The finished sketch as a geometry in the layer's CRS, or None if too short."""
        if self.geometry_kind == "line":
            if len(self.points) < 2:
                return None
            geom = QgsGeometry.fromPolylineXY(self.points)
        else:
            if len(self.points) < 3:
                return None
            ring = list(self.points)
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            geom = QgsGeometry.fromPolygonXY([ring])
        geom = self._to_layer_crs(geom)
        if QgsWkbTypes.isMultiType(self.layer.wkbType()):
            geom.convertToMultiType()
        return geom

    def _finish_sketch(self):
        if self.layer is None:
            return
        if self.mode == "split":
            self._split_features()
            return
        geom = self.sketch_geometry()
        if geom is None:
            self._reset_sketch()
            return
        ok, _feature = self.iface.vectorLayerTools().addFeature(self.layer, {}, geom)
        self._reset_sketch()
        if ok:
            # The new feature must be traceable right away.
            self._net_stale = True

    def _to_layer_crs(self, geom):
        map_crs = self.canvas.mapSettings().destinationCrs()
        layer_crs = self.layer.crs()
        if map_crs != layer_crs:
            geom.transform(QgsCoordinateTransform(map_crs, layer_crs, QgsProject.instance()))
        return geom

    # ------------------------------------------------------------------
    # split mode
    # ------------------------------------------------------------------

    def split_line(self):
        """The traced line in the layer's CRS, or None if it has fewer than two points."""
        if len(self.points) < 2:
            return None
        return self._to_layer_crs(QgsGeometry.fromPolylineXY(self.points))

    def _split_features(self):
        """Cut the features of the active layer along the traced line (one undo step)."""
        line = self.split_line()
        self._reset_sketch()
        if line is None:
            return None
        points = [QgsPoint(p) for p in line.asPolyline()]
        topological = QgsProject.instance().topologicalEditing()
        layer = self.layer
        before = layer.featureCount()
        layer.beginEditCommand(tr("Split features with Pro Trace"))
        try:
            result = layer.splitFeatures(QgsLineString(points), False, topological)
        except TypeError:  # bindings without the curve overload
            result = layer.splitFeatures([QgsPointXY(p.x(), p.y()) for p in points], topological)
        if isinstance(result, tuple):
            result = result[0]
        if result == Qgis.GeometryOperationResult.Success:
            layer.endEditCommand()
            self._net_stale = True
            self.canvas.refresh()
            added = layer.featureCount() - before
            self.iface.messageBar().pushMessage(
                "GeoDrafter Pro Trace", tr("Split – {} new feature(s).").format(max(added, 1)),
                level=Qgis.MessageLevel.Info, duration=3)
        else:
            layer.destroyEditCommand()
            if result == Qgis.GeometryOperationResult.NothingHappened:
                self._tell(tr("Nothing was split. The line must cross a feature completely "
                              "(only selected features are split when there is a selection)."))
            elif result in (Qgis.GeometryOperationResult.InvalidBaseGeometry,
                            Qgis.GeometryOperationResult.GeometryEngineError):
                self._tell(tr("The feature could not be split – its geometry may be invalid."))
            else:
                self._tell(tr("Nothing was split ({}).").format(getattr(result, "name", result)))
        return result
