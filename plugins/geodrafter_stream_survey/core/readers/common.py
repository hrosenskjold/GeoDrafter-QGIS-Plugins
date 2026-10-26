# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Shared helpers for the readers: column names, numbers, text decoding, CRS check."""

import re

from ..model import SurveyPoint

# Field key → accepted column names (normalised: lower case, no units in
# brackets, single spaces). Emlid Flow names first; the others cover generic CSV
# files and Emlid's "Custom CSV" where columns can be renamed or missing.
COLUMN_ALIASES = {
    "name": ("name", "point name", "point", "pt", "id", "point id", "punkt", "punktnr", "nr"),
    "code": ("code", "feature code", "kode", "survey code"),
    "x": ("easting", "east", "x", "e", "øst", "oest"),
    "y": ("northing", "north", "y", "n", "nord"),
    "z": ("elevation", "height", "z", "h", "orthometric height", "kote", "højde"),
    "description": ("description", "desc", "note", "notes", "beskrivelse", "bemærkning"),
    "code_description": ("code description", "code desc", "codedesc", "kodebeskrivelse"),
    "lon": ("longitude", "lon", "long"),
    "lat": ("latitude", "lat"),
    # Emlid's shapefile/DXF exports shorten the names ("Ellips ht", "RMS E", "Elev RMS", "Antenna ht" …)
    "ellipsoidal_height": ("ellipsoidal height", "ellipsoid height", "ell height", "ellips ht"),
    "solution_status": ("solution status", "solution", "status", "fix type"),
    "rms_e": ("easting rms", "rms easting", "e rms", "rms e"),
    "rms_n": ("northing rms", "rms northing", "n rms", "rms n"),
    "rms_z": ("elevation rms", "rms elevation", "height rms", "vertical rms", "z rms", "elev rms"),
    "rms_lateral": ("lateral rms", "horizontal rms", "later rms"),
    "antenna_height": ("antenna height", "antenna", "ant height", "antenna ht"),
    "antenna_height_units": ("antenna height units", "antenna height unit", "antenna units"),
    "time_start": ("averaging start", "start time", "time", "timestamp", "date time", "collected",
                   "avg start"),
    "time_end": ("averaging end", "end time", "avg end"),
    "samples": ("samples", "epochs"),
    "pdop": ("pdop",),
    "cs_name": ("cs name", "coordinate system", "crs", "cs"),
}

NUMERIC = {"x", "y", "z", "lon", "lat", "ellipsoidal_height", "rms_e", "rms_n", "rms_z",
           "rms_lateral", "antenna_height", "pdop"}


def norm_header(h):
    h = (h or "").replace("﻿", "").strip().lower()
    h = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*", " ", h)  # "Easting (m)" -> "easting"
    h = re.sub(r"[_\s]+", " ", h).strip()
    return h


def map_columns(headers, overrides=None, dbf=False):
    """{field key: column index} from a header row.

    ``overrides`` maps field key → column name or 0-based index and wins over
    the automatic match. ``dbf`` also accepts names cut to 10 characters
    (shapefile attribute tables).
    """
    normed = [norm_header(h) for h in headers]
    out = {}
    for key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            for i, h in enumerate(normed):
                if i in out.values():
                    continue
                if h == alias or (dbf and len(h) >= 9 and alias.startswith(h) and len(alias) > len(h)):
                    out[key] = i
                    break
            if key in out:
                break
    for key, col in (overrides or {}).items():
        if isinstance(col, int):
            out[key] = col
        elif col is None or col == "":
            out.pop(key, None)
        else:
            n = norm_header(col)
            if n not in normed:
                raise ValueError("Column '%s' not found (columns: %s)" % (col, ", ".join(headers)))
            out[key] = normed.index(n)
    return out


def parse_float(s, decimal_comma=False):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace("−", "-")
    if not s:
        return None
    if decimal_comma:
        if s.count(",") == 1 and s.count(".") >= 1:   # 1.234,5
            s = s.replace(".", "")
        s = s.replace(",", ".")
    m = re.match(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", s)
    if not m:
        return None
    return float(m.group(0))


def parse_int(s):
    f = parse_float(s)
    return None if f is None else int(round(f))


_FT = 0.3048
_US_FT = 1200.0 / 3937.0


def antenna_to_m(value, unit_text):
    """Antenna height in metres; Emlid writes the unit in its own column (m / ft / us_ft)."""
    if value is None:
        return None
    u = (unit_text or "").strip().lower().replace(" ", "").replace("-", "_")
    if u in ("ft", "feet", "intl_ft", "international_feet"):
        return value * _FT
    if u in ("us_ft", "usft", "us_feet", "ussurveyfeet", "us_survey_feet"):
        return value * _US_FT
    if u in ("mm",):
        return value / 1000.0
    if u in ("cm",):
        return value / 100.0
    return value


def decode_bytes(raw):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def read_text_file(path):
    with open(path, "rb") as f:
        return decode_bytes(f.read())


def point_from_fields(seq, values, decimal_comma=False, extra=None):
    """A SurveyPoint from {field key: raw text}. Returns None without X/Y."""
    def num(k):
        return parse_float(values.get(k), decimal_comma)

    x, y = num("x"), num("y")
    if x is None or y is None:
        return None
    ant = num("antenna_height")
    unit = (values.get("antenna_height_units") or "").strip()
    raw_ant = (values.get("antenna_height") or "").strip()
    return SurveyPoint(
        seq=seq,
        name=(values.get("name") or "").strip() or str(seq + 1),
        x=x, y=y, z=num("z"),
        code=(values.get("code") or "").strip(),
        description=(values.get("description") or "").strip(),
        code_description=(values.get("code_description") or "").strip(),
        lon=num("lon"), lat=num("lat"),
        ellipsoidal_height=num("ellipsoidal_height"),
        solution_status=(values.get("solution_status") or "").strip().upper(),
        rms_e=num("rms_e"), rms_n=num("rms_n"), rms_z=num("rms_z"), rms_lateral=num("rms_lateral"),
        antenna_height=antenna_to_m(ant, unit),
        antenna_height_raw=(raw_ant + (" " + unit if unit else "")).strip(),
        time_start=(values.get("time_start") or "").strip(),
        time_end=(values.get("time_end") or "").strip(),
        samples=parse_int(values.get("samples")),
        pdop=num("pdop"),
        cs_name=(values.get("cs_name") or "").strip(),
        extra=dict(extra or {}),
    )


def check_crs(survey):
    """Warn when the points are not in ETRS89 / UTM 32N with DVR90 heights.

    Uses Emlid's ``CS name`` (e.g. "ETRS89 / UTM zone 32N + DVR90 height") when
    present; otherwise a plausibility check of the coordinates for Denmark.
    Adds the warnings to ``survey.warnings`` and returns them.
    """
    warnings = []
    names = sorted({p.cs_name for p in survey.points if p.cs_name})
    for n in names:
        u = n.upper().replace("_", " ")
        horizontal_ok = ("25832" in u or "UTM ZONE 32N" in u or "UTM32" in u.replace(" ", "")) \
            and ("ETRS" in u or "25832" in u or "EUREF" in u)
        vertical_ok = "DVR90" in u.replace(" ", "") or "5799" in u
        if not horizontal_ok:
            warnings.append("Coordinate system '%s' is not ETRS89 / UTM zone 32N (EPSG:25832)." % n)
        elif not vertical_ok:
            warnings.append("Coordinate system '%s' does not name DVR90 heights – check the elevations." % n)
    if not names and survey.points:
        bad = [p for p in survey.points if not (100000 <= p.x <= 1000000 and 5900000 <= p.y <= 6500000)]
        if bad:
            warnings.append("%d of %d points lie outside Denmark in UTM 32N – is the file in EPSG:25832?"
                            % (len(bad), len(survey.points)))
    survey.warnings.extend(warnings)
    return warnings
