# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Stream Survey – plugin wiring: toolbar button, menu, dock panel and the steps."""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsMessageLog, QgsPointXY,
    QgsProject, QgsRectangle)

try:  # Qt6 / QGIS 4
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 / QGIS 3.40
    from qgis.PyQt.QtWidgets import QAction

from ..geodrafter_common import show_about
# no "Share as web map" until GeoDrafter Publish is online
from ..geodrafter_common.links import PUBLISH_AVAILABLE  # noqa: F401
from ..geodrafter_common.toolbar import MENU_NAME, add_to_toolbar, remove_actions
from . import i18n
from .i18n import tr

PLUGIN_NAME = "GeoDrafter Stream Survey"
CRS = "EPSG:25832"


def line_coords(layer, prefer_selected=True, near=None):
    """Vertices (EPSG:25832) of one line feature: the selected one, else the one nearest ``near``."""
    feats = list(layer.selectedFeatures()) if prefer_selected else []
    if not feats:
        feats = list(layer.getFeatures())
    if not feats:
        raise ValueError("The line layer has no features.")
    xf = None
    target = QgsCoordinateReferenceSystem(CRS)
    if layer.crs() != target:
        xf = QgsCoordinateTransform(layer.crs(), target, QgsProject.instance().transformContext())

    def geom(f):
        g = QgsGeometry(f.geometry())
        if xf is not None:
            g.transform(xf)
        return g
    geoms = [geom(f) for f in feats]
    if near is not None and len(geoms) > 1:
        pt = QgsGeometry.fromPointXY(QgsPointXY(*near))
        geoms.sort(key=lambda g: g.distance(pt))
    g = geoms[0]
    if g.isMultipart():
        parts = g.asMultiPolyline()
        if near is not None:
            pt = QgsGeometry.fromPointXY(QgsPointXY(*near))
            parts.sort(key=lambda pl: QgsGeometry.fromPolylineXY(pl).distance(pt))
        line = parts[0]
    else:
        line = g.asPolyline()
    if g.type() != Qgis.GeometryType.Line or len(line) < 2:
        raise ValueError("The feature is not a line.")
    return [(p.x(), p.y()) for p in line]


class GeoDrafterStreamSurveyPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.actions = []
        self.action = None
        self.dock = None
        self.state = None
        self.layers = {}
        self.view = None
        self.pick_tool = None
        i18n.install(self.plugin_dir)

    # -- QGIS plugin API ------------------------------------------------------------------
    def initGui(self):  # noqa: N802
        icon = QIcon(os.path.join(self.plugin_dir, "icon.svg"))
        self.action = QAction(icon, tr("Stream Survey"), self.iface.mainWindow())
        self.action.setObjectName("GeoDrafterStreamSurveyAction")
        self.action.setCheckable(True)
        self.action.setToolTip(tr("GeoDrafter Stream Survey – cross-sections from a field survey, "
                                  "extended onto terrain with a terrain model."))
        self.action.triggered.connect(self.toggle)
        about = QAction(tr("About GeoDrafter Stream Survey"), self.iface.mainWindow())
        about.triggered.connect(lambda: show_about(self.iface.mainWindow(), self.plugin_dir))
        add_to_toolbar(self.iface, self.action)
        for action in (self.action, about):
            self.iface.addPluginToMenu(MENU_NAME, action)
            self.actions.append(action)

    def unload(self):
        remove_actions(self.iface, self.actions)
        self.actions = []
        if self.pick_tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() is self.pick_tool:
                canvas.unsetMapTool(self.pick_tool)
            self.pick_tool = None
        for attr in ("view", "dock"):
            w = getattr(self, attr)
            if w is not None:
                self.iface.removeDockWidget(w)
                w.deleteLater()
                setattr(self, attr, None)
        i18n.remove()

    # -- dock -----------------------------------------------------------------------------
    def _ensure(self):
        if self.dock is not None:
            return
        from .dock import StreamSurveyDock
        from .project import SurveyState
        from . import terrain_source as ts

        self.state = SurveyState()
        self.dock = StreamSurveyDock(self.iface.mainWindow())
        self.dock.runStep.connect(self.run_step)
        self.dock.checkClicked.connect(self.zoom_to)
        self.dock.exportCodeLibrary.connect(self.export_code_library)
        self.dock.makeCodeTable.connect(self.make_code_table)
        self.dock.unknownCodes.connect(self.unknown_codes)
        self.dock.saveCheckSettings.connect(self.save_check_settings)
        self.dock.exportRequested.connect(self.export_dialog)
        self.load_check_choices()
        self.dock.saveToken.connect(self.save_token)
        self.dock.visibilityChanged.connect(lambda v: self.action.setChecked(v))
        self.dock.token_status.setText(tr("Token saved in the QGIS password manager.") if ts.stored_authcfg()
                                       else tr("No token saved yet."))
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

    def toggle(self, checked=True):
        self._ensure()
        self.dock.setVisible(bool(checked) or not self.dock.isVisible())
        if self.dock.isVisible():
            self.dock.raise_()

    def info(self, text, level=None):
        self.dock.message.setText(text)
        bar = self.iface.messageBar()
        if bar is not None and level is not None:
            bar.pushMessage(PLUGIN_NAME, text, level, 6)

    # -- steps ------------------------------------------------------------------------------
    def run_step(self, step):
        try:
            getattr(self, "step_" + step)()
            failed = ()
        except Exception as e:  # shown to the user, the panel stays usable
            self.info(tr("Step failed: %s") % e, Qgis.MessageLevel.Warning)
            failed = (step,)
        self.dock.set_status(self.state.done, failed)
        self.dock.set_checks(self.state.checks)
        if step in self.state.done:
            self.write_and_show()
            if step in ("profiles", "terrain") and self.state.profiles:
                self.show_view()

    def step_import(self):
        d = self.dock
        path = d.file_edit.text().strip()
        if not path or not os.path.exists(path):
            raise ValueError(tr("Choose a field file."))
        kind = d.reader_combo.currentData() or None
        opts = {}
        if kind == "field_text":
            opts["layout"] = d.text_layout()
        table = d.table_path() or None
        s = self.state.run_import(path, code_table_path=table, kind=kind, **opts)
        if not d.gpkg_edit.text().strip():
            d.gpkg_edit.setText(os.path.splitext(path)[0] + "_stream_survey.gpkg")
        types = {}
        for p in s.points:
            types[p.point_type] = types.get(p.point_type, 0) + 1
        fix = sum(1 for p in s.points if p.is_fix)
        summary = tr("%d points read (%s); %d with FIX.") % (
            len(s.points), ", ".join("%s %d" % kv for kv in sorted(types.items())), fix)
        if self.state.vasp_codes:
            unsure = sum(1 for m in self.state.vasp_codes if m.suggestion.confidence != "sure")
            summary += " " + tr("%d VASP codes recognised and paired automatically (%d uncertain) – "
                                "the code button below shows them.") % (len(self.state.vasp_codes), unsure)
        d.import_summary.setText(summary)
        d.set_point_names([p.name for p in s.points])
        from ..core.codemap import unknown_codes
        n_unknown = len(unknown_codes(s, self.state.code_table).rows)
        n_vasp = len(self.state.vasp_codes)
        d.unknown_button.setEnabled(n_unknown > 0 or n_vasp > 0)
        if n_unknown:
            d.unknown_button.setText(tr("Unknown codes in the file (%d)…") % n_unknown)
        elif n_vasp:
            d.unknown_button.setText(tr("Check the VASP codes (%d)…") % n_vasp)
        else:
            d.unknown_button.setText(tr("Unknown codes in the file…"))
        self.info(tr("%d points imported from %s.") % (len(s.points), os.path.basename(path)))

    def step_structures(self):
        res = self.state.run_structures()
        self.dock.set_structures(res)
        drains = [s for s in res if s.point.point_type == "drain_outlet"]
        self.info(tr("%d structures and drains on station (%d drains).") % (len(res), len(drains)))

    def step_check(self):
        found = self.state.run_check(self.dock.check_settings())
        if "structures" in self.state.done:
            self.dock.set_structures(self.state.structures)
        n = {k: sum(1 for c in found if c.severity == k) for k in ("error", "warning", "info")}
        self.dock.chk_summary.setText(tr("%d errors, %d warnings, %d notes.") % (
            n["error"], n["warning"], n["info"]))
        self.info(self.dock.chk_summary.text())

    EXPORT_FILTERS = {"csv": ("_sections.csv", "CSV (*.csv)"),
                      "long_csv": ("_long_profile.csv", "CSV (*.csv)"),
                      "hecras": (".g01", "HEC-RAS geometry (*.g01)"),
                      "mike": ("_mike_xns.txt", "Text (*.txt)"),
                      "pdf": ("_profiles.pdf", "PDF (*.pdf)")}

    def export_dialog(self, kind):
        if not self.state.profiles:
            self.info(tr("Build the cross-sections first."))
            return
        suffix, filt = self.EXPORT_FILTERS[kind]
        base = os.path.splitext(self.dock.gpkg_edit.text().strip() or self.state.path or "survey")[0]
        path, _f = QFileDialog.getSaveFileName(self.dock, tr("Export"), base + suffix, filt)
        if path:
            self.export_to(kind, path)

    def export_to(self, kind, path):
        """Write one export; returns the path."""
        from ..core import export
        secs = self.state.section_data()
        name = self.dock.river_edit.text().strip() or os.path.splitext(os.path.basename(self.state.path))[0]
        if kind == "csv":
            text = export.sections_csv(secs)
        elif kind == "long_csv":
            text = export.long_profile_csv(secs)
        elif kind == "hecras":
            text = export.hecras_geometry(secs, self.state.centerline.coords, title=name, river=name)
        elif kind == "mike":
            text = export.mike_cross_sections(secs, river=name)
        elif kind == "pdf":
            from .pdf_export import write_sheets
            n = write_sheets(path, secs, name, self.state.water_level,
                             self.state.extension_settings.transition,
                             export.long_profile(secs))
            self.dock.export_summary.setText(tr("%s written (%d pages).") % (os.path.basename(path), n))
            return path
        else:
            raise ValueError(kind)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        self.dock.export_summary.setText(tr("%s written.") % os.path.basename(path))
        self.state.done.add("export")
        self.dock.set_status(self.state.done)
        return path

    def _check_dir(self):
        from .codemap_dialog import user_table_dir
        d = os.path.join(os.path.dirname(user_table_dir()), "checksettings")
        os.makedirs(d, exist_ok=True)
        return d

    def load_check_choices(self, select=None):
        from ..core.checks import CheckSettings, load_settings
        choices = [("GeoDrafter standard", CheckSettings())]
        d = self._check_dir()
        for fn in sorted(os.listdir(d)):
            if fn.endswith((".yaml", ".yml")):
                try:
                    s = load_settings(os.path.join(d, fn))
                    choices.append((s.name, s))
                except Exception as err:  # noqa: BLE001 – a broken user file must not hide the others
                    QgsMessageLog.logMessage("Check settings %s skipped: %s" % (fn, err),
                                             "GeoDrafter Stream Survey", Qgis.MessageLevel.Warning)
        self.dock.set_check_choices(choices, select)

    def save_check_settings(self, name):
        from ..core.checks import save_settings
        from ..core.codemap import slug
        name = (name or "").strip()
        if not name:
            self.info(tr("Give the limits a name, e.g. the municipality."))
            return
        s = self.dock.check_settings(name)
        save_settings(s, os.path.join(self._check_dir(), slug(name) + ".yaml"))
        self.load_check_choices(select=name)
        self.info(tr("Limits saved as %s.") % name)

    def _point_xy(self, name):
        for p in self.state.survey.points:
            if p.name == name:
                return (p.x, p.y)
        return None

    def step_centerline(self):
        d = self.dock
        coords = features = None
        source = ""
        failed = ""
        self.state.line_fetched = self.state.line_attribution = ""
        if d.cl_inspire.isChecked():
            from . import inspire
            try:
                features, source, fetched = inspire.fetch(self.state.survey.points)
                self.state.line_fetched, self.state.line_attribution = fetched, inspire.ATTRIBUTION
            except Exception as e:
                features = None
                failed = str(e)
        elif d.cl_layer.isChecked():
            layer = d.cl_layer_combo.currentLayer()
            if layer is None:
                raise ValueError(tr("Choose a line layer."))
            pts = self.state.survey.points
            near = (sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts))
            coords = line_coords(layer, bool(d.cl_selected_only.currentData()), near)
            source = layer.name()
        sp = d.station_point.currentData() or ""
        up = d.upstream_combo.currentData() or ""
        cl = self.state.run_centerline(
            coords, upstream_point=self._point_xy(up) if up else None,
            station_point=self._point_xy(sp) if sp else None, station_value=d.station_value.value(),
            grouping=d.grouping_combo.currentData(), max_gap=d.max_gap.value(),
            min_points=d.min_points.value(), features=features, source=source,
            fit_to_bed=d.cl_fit.isChecked(), max_distance=d.cl_max_dist.value())
        if failed:
            from .project import Check
            p0 = self.state.survey.points[0]
            self.state.checks_by_step.setdefault("centerline", []).append(Check(
                "warning", "centerline_source",
                "INSPIRE line not available (%s) – the centre line is built from the bed points." % failed,
                p0.x, p0.y))
        d.cl_summary.setText(tr("Centre line %.1f m, station %.2f – %.2f. %s") % (
            cl.length, cl.station_shift, cl.station_shift + cl.length,
            " ".join([tr("Source: %s.") % (self.state.notes_source or cl.source)] + self.state.notes)))
        self.info(d.cl_summary.text())

    def step_profiles(self):
        d = self.dock
        profs = self.state.run_profiles(d.grouping_combo.currentData(), max_gap=d.max_gap.value(),
                                        min_points=d.min_points.value(),
                                        tangent_window=d.tangent_window.value())
        if profs:
            spacing = [b.station - a.station for a, b in zip(profs, profs[1:])]
            d.pr_summary.setText(tr("%d cross-sections, station %.1f – %.1f, largest spacing %.1f m; "
                                    "%d single points (structures, drains …).") % (
                len(profs), profs[0].station, profs[-1].station, max(spacing) if spacing else 0.0,
                len(self.state.located)))
        else:
            d.pr_summary.setText(tr("No cross-sections found."))
        self.info(d.pr_summary.text())

    def _terrain_layer(self):
        from . import terrain_source as ts
        d = self.dock
        if d.src_dhm.isChecked():
            cfg = ts.stored_authcfg()
            if not cfg:
                raise ValueError(tr("Save your Dataforsyningen token first."))
            layer = ts.dhm_layer(cfg, ts.setting("wcs_url", ts.DEFAULT_WCS_URL),
                                 ts.setting("wcs_coverage", ts.DEFAULT_COVERAGE))
        elif d.src_file.isChecked():
            path = d.dem_file_edit.text().strip()
            if not path or not os.path.exists(path):
                raise ValueError(tr("Choose a terrain model file."))
            layer = ts.file_layer(path)
        else:
            layer = d.raster_combo.currentLayer()
            if layer is None:
                raise ValueError(tr("Choose a raster layer."))
        if not layer.isValid():
            raise ValueError(tr("The terrain model could not be opened: %s") % layer.error().summary())
        return layer

    def step_terrain(self):
        from ..core.terrain import ExtensionSettings
        from .terrain_source import RasterTerrain
        d = self.dock
        layer = self._terrain_layer()
        rt = RasterTerrain(layer, QgsCoordinateReferenceSystem(CRS))
        version = d.dhm_version.text().strip() or layer.name()
        st = ExtensionSettings(length=d.ext_length.value(), step=d.ext_step.value(),
                               tolerance=d.ext_tol.value(),
                               transition=d.ext_transition.value(), error_limit=d.ext_error.value(),
                               thin_tolerance=d.ext_thin.value(), control_points=d.ext_controls.currentData(),
                               dhm_version=version)
        exts = self.state.run_terrain(rt.for_profile, st)
        n = {"ok": 0, "review": 0, "error": 0}
        for e in exts:
            n[e.status] += 1
        d.tr_summary.setText(tr("%d sections extended: %d OK, %d to review, %d errors.") % (
            len(exts), n["ok"], n["review"], n["error"]))
        self.info(d.tr_summary.text())

    # -- output -----------------------------------------------------------------------------
    def write_and_show(self):
        from .layers import build_layers, load_geopackage, write_geopackage
        path = self.dock.gpkg_edit.text().strip()
        if not path:
            return
        layers = build_layers(self.state)
        errors = write_geopackage(layers, path)
        if errors:
            self.info(tr("Could not write the GeoPackage: %s") %
                      "; ".join(errors), Qgis.MessageLevel.Critical)
            return
        self.layers = load_geopackage(path)

    # -- profile view (block 10) ------------------------------------------------------------
    def _ensure_view(self):
        if self.view is not None:
            return
        from .profile_view import ProfileView
        self.view = ProfileView(self.iface.mainWindow())
        self.view.profileChanged.connect(self.show_profile)
        self.view.pointMoved.connect(self.on_point_moved)
        self.view.codeChanged.connect(self.on_code_changed)
        self.view.dhmRemoved.connect(self.on_dhm_removed)
        self.view.pick_button.toggled.connect(self.toggle_pick)
        self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.view)

    def show_view(self, pid=None):
        self._ensure_view()
        table = self.state.code_table
        codes = [(e.code, e.description) for e in table.entries] if table is not None else []
        self.view.set_profiles([p.id for p in self.state.profiles], codes)
        from ..core.export import long_profile
        self.view.set_long_profile(long_profile(self.state.section_data()))
        self.view.show()
        self.view.raise_()
        self.view.select(pid or self.view.current() or self.state.profiles[0].id)

    def show_profile(self, pid):
        pr = self.state.profile(pid)
        if pr is None or self.view is None:
            return
        ext = self.state.extended_profile(pid)
        self.view.show_profile(pid, pr.station, self.state.section_points(pid), self.state.water_level(pid),
                               ext.status if ext is not None else "",
                               self.state.extension_settings.transition)
        lay = self.layers.get("profiles")
        if lay is not None:
            try:
                ids = [f.id() for f in lay.getFeatures() if f["profile_id"] == pid]
                lay.blockSignals(True)
                lay.selectByIds(ids)
            finally:
                lay.blockSignals(False)

    def _after_edit(self, pid):
        from ..core.export import long_profile
        self.write_and_show()
        self.view.set_long_profile(long_profile(self.state.section_data()))
        self.dock.set_checks(self.state.checks)
        self.show_profile(pid)

    def on_point_moved(self, pid, index, offset, z):
        self.state.move_point(pid, index, offset, z)
        self._after_edit(pid)

    def on_code_changed(self, pid, index, code):
        self.state.set_point_code(pid, index, code)
        self._after_edit(pid)

    def on_dhm_removed(self, pid, side):
        self.state.remove_dhm(pid, side)
        self._after_edit(pid)

    def nearest_profile(self, x, y, tolerance):
        """The section whose line passes nearest (x, y) in EPSG:25832, within ``tolerance`` metres."""
        best, bd = None, tolerance
        for pr in self.state.profiles:
            pts = self.state.section_points(pr.id)
            (ax, ay), (bx, by) = pr.line()
            if pts:
                nx, ny = pr.normal
                ax, ay = pr.x + pts[0].offset * nx, pr.y + pts[0].offset * ny
                bx, by = pr.x + pts[-1].offset * nx, pr.y + pts[-1].offset * ny
            g = QgsGeometry.fromPolylineXY([QgsPointXY(ax, ay), QgsPointXY(bx, by)])
            d = g.distance(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            if d <= bd:
                best, bd = pr.id, d
        return best

    def toggle_pick(self, on):
        from qgis.gui import QgsMapToolEmitPoint
        canvas = self.iface.mapCanvas()
        if on:
            if self.pick_tool is None:
                self.pick_tool = QgsMapToolEmitPoint(canvas)
                self.pick_tool.canvasClicked.connect(self.on_map_click)
            canvas.setMapTool(self.pick_tool)
        elif self.pick_tool is not None and canvas.mapTool() is self.pick_tool:
            canvas.unsetMapTool(self.pick_tool)

    def on_map_click(self, point, _button=None):
        canvas = self.iface.mapCanvas()
        xf = QgsCoordinateTransform(canvas.mapSettings().destinationCrs(), QgsCoordinateReferenceSystem(CRS),
                                    QgsProject.instance().transformContext())
        p = xf.transform(point)
        tol = max(canvas.mapUnitsPerPixel() * 8, 1.0)
        pid = self.nearest_profile(p.x(), p.y(), tol)
        if pid:
            self.show_view(pid)

    def zoom_to(self, x, y):
        canvas = self.iface.mapCanvas()
        xf = QgsCoordinateTransform(QgsCoordinateReferenceSystem(CRS), canvas.mapSettings().destinationCrs(),
                                    QgsProject.instance().transformContext())
        r = xf.transformBoundingBox(QgsRectangle(x - 25, y - 25, x + 25, y + 25))
        canvas.setExtent(r)
        canvas.refresh()

    def make_code_table(self):
        from .codemap_dialog import CodeMapDialog
        dlg = CodeMapDialog(self.dock)
        dlg.open_list()
        if dlg.mapped and dlg.exec():
            self._table_saved(dlg.saved_path)

    def unknown_codes(self):
        from ..core.codemap import map_codes, unknown_codes
        from .codemap_dialog import CodeMapDialog
        if self.state.survey is None or self.state.code_table is None:
            return
        base = self.state.base_code_table or self.state.code_table
        mapped = list(self.state.vasp_codes)
        mapped += map_codes(unknown_codes(self.state.survey, self.state.code_table))
        dlg = CodeMapDialog(self.dock, mapped, name="%s (+)" % base.name, base_table=base, extend=True)
        if dlg.exec():
            self._table_saved(dlg.saved_path)

    def _table_saved(self, path):
        if not path:
            return
        self.dock.refresh_tables(select=path)
        self.info(tr("Code table saved: %s – import the file again to use it.") % os.path.basename(path))

    def export_code_library(self):
        from ..core import codes
        table = self.state.code_table or codes.standard_table()
        path, _f = QFileDialog.getSaveFileName(self.dock, tr("Code library for Emlid Flow 360"),
                                               "geodrafter_stream_codes.csv", "CSV (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(codes.emlid_library_csv(table))
            self.info(tr("Saved %s – import it in Emlid Flow 360 under Code libraries.") %
                      os.path.basename(path))

    def save_token(self, token):
        from . import terrain_source as ts
        try:
            ts.save_token(token, ts.setting("wcs_header", ts.DEFAULT_HEADER), ts.stored_authcfg() or None)
        except Exception as e:
            self.dock.token_status.setText(tr("Not saved: %s") % e)
            return
        self.dock.token_edit.clear()
        self.dock.token_status.setText(tr("Token saved in the QGIS password manager."))
        self.dock.src_dhm.setChecked(True)
