# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Which field holds the survey codes (pure Python).

Exports differ: Emlid's ``Code`` may hold only a number from the code library
(``13``) while ``Code description`` holds the meaning (``13PROFILPKT``); other
files keep the code in a note or a custom column. The plugin therefore looks at
every text field and uses the one whose values the code table (or the VASP
codes) understands best – and the user can choose the field.
"""

from . import vasp

CODE = "code"                    # the reader's code column
CODE_DESCRIPTION = "code_description"
DESCRIPTION = "description"
LABELS = {CODE: "Code", CODE_DESCRIPTION: "Code description", DESCRIPTION: "Description"}


def value(point, column):
    if column == CODE:
        return point.code
    if column == CODE_DESCRIPTION:
        return point.code_description
    if column == DESCRIPTION:
        return point.description
    return str(point.extra.get(column, "") or "").strip()


def _numeric(v):
    try:
        float(v.replace(",", "."))
        return True
    except ValueError:
        return False


def candidate_columns(survey):
    """Fields that could hold codes: code, code description, description, and other text fields
    with few distinct values (not coordinates, times or ids)."""
    out = [c for c in (CODE, CODE_DESCRIPTION, DESCRIPTION)
           if any(value(p, c) for p in survey.points)]
    n = len(survey.points)
    keys = []
    for p in survey.points:
        for k in p.extra:
            if k not in keys:
                keys.append(k)
    for k in keys:
        vals = [value(p, k) for p in survey.points]
        filled = [v for v in vals if v]
        if not filled or all(_numeric(v) for v in filled):
            continue
        distinct = set(filled)
        if 1 < len(distinct) <= max(40, n // 3):
            out.append(k)
    return out


def known_share(survey, column, table):
    """Share of the points whose value in ``column`` the table or the VASP codes know."""
    if not survey.points:
        return 0.0
    known = 0
    for p in survey.points:
        v = value(p, column)
        if v and (table.lookup(v) is not None or vasp.classify(v) is not None):
            known += 1
    return known / len(survey.points)


def best_column(survey, table, margin=0.2):
    """(column, share) of the best field when it beats the code column by ``margin``, else (None, share)."""
    base = known_share(survey, CODE, table)
    best, best_share = None, base
    for c in candidate_columns(survey):
        if c == CODE:
            continue
        s = known_share(survey, c, table)
        if s > best_share + 1e-9 and s >= base + margin:
            best, best_share = c, s
    return best, best_share


def use_column(survey, column):
    """Take the codes from ``column``; the original code is kept in ``extra['Code (file)']``."""
    if column in (None, "", CODE):
        return survey
    for p in survey.points:
        if p.code and "Code (file)" not in p.extra:
            p.extra["Code (file)"] = p.code
        p.code = value(p, column)
    return survey


def label(column):
    return LABELS.get(column, column)
