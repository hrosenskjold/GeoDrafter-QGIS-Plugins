# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Delimited text readers: Emlid Flow CSV, generic CSV/TXT and field text files.

* ``read_emlid_csv`` – Emlid Flow / Flow 360 CSV export: comma or tab separated
  (Custom CSV: any separator, columns renamed or missing), columns found by name.
  Also the header-less "PENZD" / "PNEZD" layouts.
* ``read_delimited`` – any CSV/TXT with a header; columns found by name or given.
* ``read_field_text`` – header-less text files with whitespace or a separator,
  columns given by position (``layout``), e.g. ``["name", "x", "y", "z", "code"]``.
  Lines starting with a comment character are skipped. Used for surveyors' own
  text formats until a real example file defines a fixed preset.

The row order of the file is the survey order and is kept (``SurveyPoint.seq``).
"""

import csv
import io
import os

from ..model import Survey
from .common import COLUMN_ALIASES, map_columns, norm_header, parse_float, point_from_fields, read_text_file

SEPARATORS = ("\t", ";", ",", "|")

LAYOUTS = {
    "PENZD": ["name", "x", "y", "z", "description"],
    "PNEZD": ["name", "y", "x", "z", "description"],
    "PENZ": ["name", "x", "y", "z"],
    "PNEZ": ["name", "y", "x", "z"],
    "PENZC": ["name", "x", "y", "z", "code"],
    "PENZCD": ["name", "x", "y", "z", "code", "description"],
}


def sniff_separator(lines):
    """The separator that splits the first lines into the same number (>1) of fields."""
    sample = [ln for ln in lines[:20] if ln.strip()]
    if not sample:
        return ","
    best, best_score = ",", -1
    for sep in SEPARATORS:
        counts = [len(next(csv.reader([ln], delimiter=sep))) for ln in sample]
        if counts[0] < 2:
            continue
        same = sum(1 for c in counts if c == counts[0])
        score = same * 100 + counts[0]
        if score > best_score:
            best, best_score = sep, score
    return best


def _looks_like_header(fields):
    numeric = sum(1 for f in fields if parse_float(f) is not None)
    known = sum(1 for f in fields if any(norm_header(f) in a for a in COLUMN_ALIASES.values()))
    return known >= 2 or numeric == 0


def _rows(text, sep):
    return [r for r in csv.reader(io.StringIO(text), delimiter=sep) if any(c.strip() for c in r)]


def _decimal_comma(rows, cols, sep):
    """True when numbers use a decimal comma (only possible with a non-comma separator)."""
    if sep == ",":
        return False
    for r in rows[:20]:
        for k in ("x", "y"):
            i = cols.get(k)
            if i is not None and i < len(r) and "," in r[i] and "." not in r[i]:
                return True
    return False


def _build(rows, headers, cols, source, reader, sep):
    survey = Survey(source=os.path.basename(source), reader=reader)
    dec = _decimal_comma(rows, cols, sep)
    used = set(cols.values())
    skipped = 0
    for r in rows:
        values = {k: (r[i] if i < len(r) else "") for k, i in cols.items()}
        extra = {}
        if headers:
            extra = {headers[i].strip(): r[i] for i in range(min(len(headers), len(r)))
                     if i not in used and headers[i].strip() and r[i].strip()}
        p = point_from_fields(len(survey.points), values, dec, extra)
        if p is None:
            skipped += 1
            continue
        survey.points.append(p)
    if skipped:
        survey.warnings.append("%d rows without Easting/Northing were skipped." % skipped)
    if "z" not in cols:
        survey.warnings.append("No elevation column found.")
    return survey


def _guess_layout(rows):
    """PENZD or PNEZD for a header-less file: in UTM 32N the northing is the larger number."""
    a = parse_float(rows[0][1]) if len(rows[0]) > 2 else None
    b = parse_float(rows[0][2]) if len(rows[0]) > 2 else None
    n = len(rows[0])
    if a is not None and b is not None and a > b:
        return LAYOUTS["PNEZD"][:n] if n <= 5 else LAYOUTS["PNEZD"]
    return LAYOUTS["PENZD"][:n] if n <= 5 else LAYOUTS["PENZD"]


def read_delimited(path, columns=None, separator=None, has_header=None, layout=None,
                   reader="csv", text=None):
    """Read a delimited text file into a Survey.

    columns: {field key: column name or index} overriding the automatic match.
    layout: list of field keys by position (header-less files), or a LAYOUTS name.
    """
    text = read_text_file(path) if text is None else text
    lines = text.splitlines()
    sep = separator or sniff_separator(lines)
    rows = _rows(text, sep)
    if not rows:
        return Survey(source=os.path.basename(path), reader=reader, warnings=["The file is empty."])
    if has_header is None:
        has_header = layout is None and _looks_like_header(rows[0])
    if has_header:
        headers = rows[0]
        cols = map_columns(headers, columns)
        rows = rows[1:]
    else:
        headers = []
        if isinstance(layout, str):
            layout = LAYOUTS[layout.upper()]
        layout = layout or _guess_layout(rows)
        cols = {k: i for i, k in enumerate(layout) if k}
        cols.update({k: v for k, v in (columns or {}).items() if isinstance(v, int)})
    if "x" not in cols or "y" not in cols:
        raise ValueError("No Easting/Northing columns found in %s (columns: %s)"
                         % (os.path.basename(path), ", ".join(headers) or "none"))
    return _build(rows, headers, cols, path, reader, sep)


def read_emlid_csv(path, columns=None, text=None):
    """Read an Emlid Flow / Flow 360 CSV export (All columns, Custom CSV, PENZD or PNEZD)."""
    s = read_delimited(path, columns=columns, reader="emlid_csv", text=text)
    if s.points and not any(p.solution_status for p in s.points):
        s.warnings.append("No 'Solution status' column – FIX/FLOAT cannot be checked.")
    return s


def read_field_text(path, layout, separator=None, comment="#*;", text=None):
    """Header-less field text file, columns by position.

    ``separator`` None = any run of whitespace. Fields may be skipped with None
    in ``layout``; fields after the last layout key are kept in ``extra``.
    """
    text = read_text_file(path) if text is None else text
    if isinstance(layout, str):
        layout = LAYOUTS[layout.upper()]
    survey = Survey(source=os.path.basename(path), reader="field_text")
    skipped = 0
    for ln in text.splitlines():
        s = ln.strip()
        if not s or (comment and s[0] in comment):
            continue
        parts = s.split(separator) if separator else s.split()
        parts = [p.strip() for p in parts]
        values = {k: parts[i] for i, k in enumerate(layout) if k and i < len(parts)}
        extra = {"col%d" % (i + 1): parts[i] for i in range(len(layout), len(parts))}
        dec = separator not in (None, ",") and any("," in (values.get(k) or "") for k in ("x", "y"))
        p = point_from_fields(len(survey.points), values, dec, extra)
        if p is None:
            skipped += 1
            continue
        survey.points.append(p)
    if skipped:
        survey.warnings.append("%d lines without Easting/Northing were skipped." % skipped)
    return survey
