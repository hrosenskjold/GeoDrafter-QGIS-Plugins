# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""The state of one survey and the steps that change it (no widgets here).

Steps (as in the dock panel): 1 import, 2 centre line and station, 3 sections,
4 terrain extension, 5 structures and drains, 6 data check, 7 long profile
and export. Each step can be run again; later steps are reset when an earlier
one changes. Steps 5–7 come in later versions (blocks 11–12).
"""

from dataclasses import dataclass, field
from typing import List, Optional

from ..core import codes
from ..core.checks import Check, CheckSettings, locate_structures, run_checks
from ..core.geometry import (
    DEFAULT_PROFILE_ATTRIBUTES, Centerline, build_profiles, centerline_from_points, group_profiles,
    locate_points, orient_downstream)
from ..core.centerline_source import bed_distance, watercourse_centerline
from ..core.centerline_source import fit_to_bed as fit_to_bed_line
from ..core.readers import read_survey
from ..core.terrain import ExtensionSettings, extend_profile

STEPS = ("import", "centerline", "profiles", "terrain", "structures", "check", "export")

# point types that are never part of a cross-section on their own
STRUCTURE_TYPES = ("pipe_invert", "pipe_top", "bridge_deck", "weir_crest", "drain_outlet", "staff_gauge")


def marker_checks(profiles, ungrouped):
    """Notes on sections measured with start/end codes (VASPGPS), where a forgotten code joins or splits
    sections: no end code, two mid-stream points, section points outside any section."""
    out = []
    for pr in profiles:
        roles = [getattr(pp.point, "section_role", "") for pp in pr.points]
        if "section_start" not in roles:
            continue
        if "section_end" not in roles:
            out.append(Check("warning", "no_end_code", "Section %s has no end code – the next start code "
                             "or the end of the file closed it." % pr.id, pr.x, pr.y, pr.id))
        if roles.count("section_mid") > 1:
            n = roles.count("section_mid")
            out.append(Check("warning", "two_mid_points", "Section %s has %d mid-stream points – a start or "
                             "end code may be missing, so two sections became one." % (pr.id, n),
                             pr.x, pr.y, pr.id))
    stray = [p for p in ungrouped if p.point_type in ("knick", "bank_top", "water_level", "bed")
             and getattr(p, "section_role", "") not in ("centerline", "kill")]
    if not (profiles and stray and any(getattr(pp.point, "section_role", "") for pr in profiles
                                       for pp in pr.points)):
        return out
    runs = [[stray[0]]]
    for p in stray[1:]:                       # one note per run of consecutive points
        if p.seq == runs[-1][-1].seq + 1:
            runs[-1].append(p)
        else:
            runs.append([p])
    for run in runs:
        a, b = run[0], run[-1]
        names = a.name if a is b else "%s–%s" % (a.name, b.name)
        out.append(Check("warning", "outside_section", "Point%s %s (%d section point%s) lie%s outside a "
                         "section – after an end code or before a start code – and are not used."
                         % ("" if a is b else "s", names, len(run), "" if a is b else "s",
                            "s" if a is b else ""), a.x, a.y))
    return out


@dataclass
class SurveyState:
    path: str = ""
    code_table: object = None
    vasp_codes: list = field(default_factory=list)   # VASP codes paired automatically on import
    base_code_table: object = None                   # the chosen table before the VASP codes were added
    code_column: object = None                       # field the codes were taken from (None = Code)
    code_column_auto: bool = False                   # True when the plugin chose that field itself
    code_columns: list = field(default_factory=list)  # fields that could hold the codes
    survey: object = None
    groups: dict = field(default_factory=dict)
    ungrouped: list = field(default_factory=list)
    centerline: Optional[Centerline] = None
    profiles: list = field(default_factory=list)
    located: list = field(default_factory=list)
    extended: list = field(default_factory=list)
    extension_settings: ExtensionSettings = field(default_factory=ExtensionSettings)
    notes: List[str] = field(default_factory=list)
    notes_source: str = ""
    line_fetched: str = ""          # date the national line was fetched (kept in the GeoPackage)
    line_attribution: str = ""
    line_fit: object = None
    done: set = field(default_factory=set)
    checks_by_step: dict = field(default_factory=dict)
    structures: list = field(default_factory=list)
    check_settings: CheckSettings = field(default_factory=CheckSettings)

    @property
    def checks(self):
        out = []
        for s in STEPS:
            out.extend(self.checks_by_step.get(s, []))
        return out

    def _reset_from(self, step):
        i = STEPS.index(step)
        for s in STEPS[i:]:
            self.done.discard(s)
            self.checks_by_step.pop(s, None)
        if i <= STEPS.index("centerline"):
            self.centerline = None
        if i <= STEPS.index("profiles"):
            self.profiles, self.located, self.groups, self.ungrouped = [], [], {}, []
        if i <= STEPS.index("terrain"):
            self.extended = []
        if i <= STEPS.index("structures"):
            self.structures = []

    # -- step 1 -----------------------------------------------------------------------
    def run_import(self, path, code_table_path=None, kind=None, auto_vasp=True, reader=None,
                   code_column="auto", **options):
        """Step 1. ``reader(code_table) -> Survey`` replaces the file readers (a layer in the project).

        ``code_column``: the field that holds the codes – "auto" (the field the code table and the VASP
        codes know best), "" / "code" (the code column) or a field name."""
        from ..core import codefield
        self._reset_from("import")
        self.code_table = codes.load_table(code_table_path) if code_table_path else codes.standard_table()
        if reader is None:
            def reader(table):
                return read_survey(path, code_table=table, kind=kind, **options)
        self.survey = reader(self.code_table)
        self.path = path
        self.vasp_codes = []
        self.base_code_table = self.code_table
        self.code_columns = codefield.candidate_columns(self.survey)
        if code_column == "auto":
            self.code_column, _share = codefield.best_column(self.survey, self.code_table)
            self.code_column_auto = self.code_column is not None
        else:
            self.code_column, self.code_column_auto = (code_column or None), False
        if self.code_column and self.code_column != codefield.CODE:
            codefield.use_column(self.survey, self.code_column)
            self.survey.apply_code_table(self.code_table)
        if auto_vasp and self.survey.points:
            from ..core.codemap import with_vasp_codes
            found = with_vasp_codes(self.survey, self.code_table)
            if found:
                self.code_table, self.vasp_codes = found
                self.survey.apply_code_table(self.code_table)
        first = self.survey.points[0] if self.survey.points else None
        self.checks_by_step["import"] = [
            Check("warning", "reader", w, first.x if first else 0.0, first.y if first else 0.0)
            for w in self.survey.warnings]
        if not self.survey.points:
            raise ValueError("No points could be read from the file.")
        self.done.add("import")
        return self.survey

    # -- step 2 -----------------------------------------------------------------------
    def run_centerline(self, coords=None, upstream_point=None, station_point=None, station_value=0.0,
                       grouping="auto", pattern=None, max_gap=15.0, min_points=3, features=None,
                       source="", fit_to_bed=False, max_distance=5.0):
        """The centre line from (in this order of preference):

        features – watercourse features (``WatercourseFeature``, e.g. INSPIRE from Dataforsyningen):
                   the best-fitting watercourse is picked, joined and cut to the survey;
        coords   – the user's own line (list of (x, y) in EPSG:25832);
        neither  – built from the lowest bed point of every section.
        ``source`` describes the line (kept in the GeoPackage). With ``fit_to_bed`` the line is moved
        through the surveyed bed points. Bed points further than ``max_distance`` from the line give a
        warning, because stationing and section direction may then be wrong.
        """
        self._need("import")
        self._reset_from("centerline")
        self.notes_source = ""
        pts = [p for p in self.survey.points]
        groups, ungrouped = group_profiles(pts, grouping, pattern, max_gap,
                                           min_points, self.profile_attributes())
        built = None
        try:
            built = centerline_from_points(groups, ungrouped)
        except Exception:
            built = None
        section_bed = list(built.coords) if built is not None else []
        bed_xy = [(p.x, p.y) for p in pts if p.point_type in ("bed", "knick")] or section_bed
        checks = []
        cl = None
        if features is not None:
            line, info = watercourse_centerline(features, bed_xy, [(p.x, p.y) for p in pts])
            if line and len(line) >= 2:
                cl = Centerline(line, source=source or "watercourse")
                self.notes_source = "%s (%s, %d of %d parts%s)" % (
                    source or "watercourse", info["key"].split(":", 1)[-1], info["used"], info["parts"],
                    ", %d gap(s) bridged" % len(info["gaps"]) if info["gaps"] else "")
            else:
                checks.append(Check("warning", "centerline_source",
                                    "No watercourse line found near the survey – the centre line is built "
                                    "from the bed points.", pts[0].x, pts[0].y))
        elif coords:
            cl = Centerline(coords, source=source or "layer")
        if cl is None:
            if built is None:
                raise ValueError("Too few bed points to build a centre line – choose a line.")
            cl = built
        elif fit_to_bed and len(section_bed) >= 2:
            cl = fit_to_bed_line(cl, section_bed)
        cl, why = orient_downstream(cl, pts, upstream_point)
        if station_point is not None:
            cl.bind_station(station_point[0], station_point[1], station_value)
        else:
            cl.station_shift = float(station_value)
        self.centerline = cl
        self.notes = ["Flow direction " + why]
        if cl is not built and bed_xy:
            fit = bed_distance(cl, bed_xy)
            self.line_fit = fit
            self.notes.append("Bed points from the line: median %.1f m, max %.1f m." %
                              (fit.median, fit.maximum))
            if fit.maximum > max_distance:
                far = max(bed_xy, key=lambda xy: cl.locate(*xy).distance)
                msg = ("Bed points up to %.1f m from the centre line (median %.1f m, limit %.1f m) – "
                       "stationing and section direction may be wrong; consider fitting the line to the "
                       "bed points." % (fit.maximum, fit.median, max_distance))
                checks.append(Check("warning", "centerline_distance", msg, far[0], far[1],
                                    value=fit.maximum))
        else:
            self.line_fit = None
        self.checks_by_step["centerline"] = checks
        self.done.add("centerline")
        return cl

    # -- step 3 -----------------------------------------------------------------------
    def run_profiles(self, grouping="auto", pattern=None, max_gap=15.0, min_points=3, tangent_window=5.0):
        self._need("centerline")
        self._reset_from("profiles")
        pts = [p for p in self.survey.points]
        groups, ungrouped = group_profiles(pts, grouping, pattern, max_gap,
                                           min_points, self.profile_attributes())
        # structures and drains stay single points even when their name groups them with a section
        for gid in list(groups):
            singles = [p for p in groups[gid] if p.point_type in STRUCTURE_TYPES]
            if singles:
                groups[gid] = [p for p in groups[gid] if p.point_type not in STRUCTURE_TYPES]
                ungrouped.extend(singles)
            if len(groups[gid]) < min_points:
                ungrouped.extend(groups.pop(gid))
        ungrouped.sort(key=lambda p: p.seq)
        self.groups, self.ungrouped = groups, ungrouped
        self.profiles = build_profiles(self.centerline, groups, tangent_window)
        self.located = locate_points(self.centerline, ungrouped)
        checks = []
        for pr in self.profiles:
            types = {pp.point.point_type for pp in pr.points}
            if "bank_top" not in types:
                checks.append(Check("warning", "no_bank_top", "Section %s has no bank top." % pr.id,
                                    pr.x, pr.y, pr.id))
        checks += marker_checks(self.profiles, ungrouped)
        if not self.profiles:
            checks.append(Check("error", "no_profiles", "No cross-sections found – check the grouping.",
                                self.centerline.coords[0][0], self.centerline.coords[0][1]))
        self.checks_by_step["profiles"] = checks
        self.done.add("profiles")
        return self.profiles

    # -- step 4 -----------------------------------------------------------------------
    def run_terrain(self, terrain_for_profile, settings=None):
        """terrain_for_profile(profile, length) -> terrain(x, y) (see terrain_source.RasterTerrain)."""
        self._need("profiles")
        self._reset_from("terrain")
        st = (settings or self.extension_settings).validate()
        self.extension_settings = st
        checks = []
        for pr in self.profiles:
            ext = extend_profile(pr, terrain_for_profile(pr, st.length), st)
            self.extended.append(ext)
            for side, res in ext.sides.items():
                if res.status in ("error", "no_data", "shifted", "from_outer_point"):
                    sev = "warning" if res.status in ("shifted", "from_outer_point") else "error"
                    nx, ny = pr.normal
                    off = res.join_offset or 0.0
                    checks.append(Check(sev, "terrain_" + res.status, "Section %s: %s" % (pr.id, res.message),
                                        pr.x + off * nx, pr.y + off * ny, pr.id, res.dz))
            for c in ext.controls:
                if c.deviation is not None:
                    checks.append(Check("info", "control",
                                        "Section %s: control point %s differs %.2f m from the terrain model."
                                        % (pr.id, c.point.name, c.deviation),
                                        c.point.x, c.point.y, pr.id, c.deviation))
        self.checks_by_step["terrain"] = checks
        self.done.add("terrain")
        return self.extended

    def profile_attributes(self):
        """Code attribute names that carry the section number: the code table's, then the defaults."""
        first = getattr(self.code_table, "profile_attribute", "") or ""
        return tuple([first] if first else []) + tuple(a for a in DEFAULT_PROFILE_ATTRIBUTES if a != first)

    def _need(self, step):
        if step not in self.done:
            raise RuntimeError("Run step '%s' first." % step)

    # -- step 5 -----------------------------------------------------------------------
    def run_structures(self):
        """Structures and drains on station, with bed and water level interpolated from the sections."""
        self._need("profiles")
        self._reset_from("structures")
        self.structures = locate_structures(self.located, self.profiles, self.section_points)
        self.done.add("structures")
        return self.structures

    # -- step 6 -----------------------------------------------------------------------
    def run_check(self, settings=None):
        """All data check rules with the given (municipality) limits."""
        self._need("profiles")
        if "structures" not in self.done:
            self.run_structures()
        self.check_settings = settings or self.check_settings
        self.checks_by_step.pop("check", None)
        found = run_checks(self.survey.points, self.profiles, self.section_points, self.extended,
                           self.structures, self.check_settings)
        # the rules replace the quick checks of steps 3–4 (same findings, now with the set limits)
        for step in ("profiles", "terrain"):
            self.checks_by_step[step] = [c for c in self.checks_by_step.get(step, [])
                                         if c.kind not in ("no_bank_top", "terrain_error", "terrain_shifted",
                                                           "terrain_from_outer_point")]
        self.checks_by_step["check"] = found
        self.done.add("check")
        return found

    # -- edits from the profile view (block 10) -------------------------------------------
    def extended_profile(self, pid):
        for e in self.extended:
            if e.profile.id == pid:
                return e
        return None

    def section_points(self, pid):
        """The points shown for a section: the terrain-extended ones when step 4 has run, else the
        measured ones (as ExtPoint), left → right."""
        ext = self.extended_profile(pid)
        if ext is not None:
            return ext.points
        pr = self.profile(pid)
        if pr is None:
            return []
        from ..core.terrain import ExtPoint
        return [ExtPoint(pp.offset, pp.point.z, pp.point.x, pp.point.y, "measured", pp.point.point_type,
                         pp.point) for pp in pr.points]

    def _ensure_extended(self, pid):
        """Edits work on ExtPoints: make a terrain-less ExtendedProfile when step 4 has not run."""
        ext = self.extended_profile(pid)
        if ext is None:
            from ..core.terrain import ExtendedProfile
            pr = self.profile(pid)
            if pr is None:
                raise KeyError(pid)
            ext = ExtendedProfile(pr, self.section_points(pid))
            self.extended.append(ext)
        return ext

    def move_point(self, pid, index, offset, z):
        """Move a section point in the profile view (new offset along the section line and elevation).
        A measured point keeps a note of its original position in ``extra``."""
        ext = self._ensure_extended(pid)
        e = ext.points[index]
        pr = ext.profile
        nx, ny = pr.normal
        if e.point is not None:
            p = e.point
            p.extra.setdefault("edited_from", "%.3f %.3f %s" %
                               (p.x, p.y, "" if p.z is None else "%.3f" % p.z))
            p.x, p.y, p.z = pr.x + offset * nx, pr.y + offset * ny, z
        e.offset, e.z = offset, z
        e.x, e.y = pr.x + offset * nx, pr.y + offset * ny
        ext.points.sort(key=lambda q: q.offset)
        return ext

    def set_point_code(self, pid, index, code):
        """New survey code for a measured point; its type follows from the code table."""
        ext = self._ensure_extended(pid)
        e = ext.points[index]
        if e.point is None:
            raise ValueError("Only measured points have a code.")
        table = self.code_table or codes.standard_table()
        e.point.code = code
        e.point.point_type, e.point.code_known = table.classify(code)
        e.point_type = e.point.point_type
        return e

    def remove_dhm(self, pid, side):
        """Drop the terrain-model part of one side ("left"/"right") of a section."""
        ext = self._ensure_extended(pid)
        left = side == "left"
        ext.points = [e for e in ext.points if e.source == "measured" or (e.offset < 0) != left]
        res = ext.sides.get(side)
        if res is not None:
            res.status = "removed"
            res.message = "Terrain-model part removed by the user."
        self.checks_by_step["terrain"] = [c for c in self.checks_by_step.get("terrain", [])
                                          if not (c.profile_id == pid and c.kind.startswith("terrain_")
                                                  and ((c.x - ext.profile.x) * ext.profile.normal[0]
                                                       + (c.y - ext.profile.y) * ext.profile.normal[1] < 0)
                                                  == left)]
        return ext

    def section_data(self):
        """The sections as ``core.export.SectionData`` (for the long profile and the exports)."""
        from ..core.export import SectionData
        out = []
        for pr in self.profiles:
            ext = self.extended_profile(pr.id)
            out.append(SectionData(pr.id, pr.station, pr.x, pr.y, pr.normal, self.section_points(pr.id),
                                   ext.status if ext is not None else ""))
        return out

    def water_level(self, pid):
        """(z, left offset, right offset) of the water surface in a section, or None."""
        ws = [e for e in self.section_points(pid) if e.point_type == "water_level" and e.z is not None]
        if not ws:
            return None
        return (sum(e.z for e in ws) / len(ws), min(e.offset for e in ws), max(e.offset for e in ws))

    def profile(self, pid):
        for pr in self.profiles:
            if pr.id == pid:
                return pr
        return None
