# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Code translator: any code list → a code table the plugin can read (pure Python).

The user brings their own list – a municipality's code appendix, a
surveyor's list, an Emlid Flow code library, one of our YAML tables, a
spreadsheet or two pasted columns. For every code a point type is suggested
by an explainable, rule-based matcher (no AI service): Danish and English
keywords and abbreviations per point type. Each suggestion carries a
confidence – ``sure``, ``unsure`` or ``unknown`` – and the reason, so the user
only has to look at the uncertain ones. Left/right variants (V/H, L/R) are
recognised and become aliases of their base code.

VASP/VASPGPS code lists (tag files, numbered tag lists, Trimble .fxl libraries) and
VASP field codes in a survey are recognised by their VASP tag (``vasp.py``) and
paired with a point type automatically.

No code lists of others are shipped; the user loads their own file.
"""

import csv
import io
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from . import vasp
from .codes import CodeEntry, CodeTable, standard_table, table_from_dict
from .model import POINT_TYPES

SURE, UNSURE, UNKNOWN = "sure", "unsure", "unknown"

# Keywords found in the description (whole words or word starts), Danish and English.
# Longer, more specific phrases win over shorter ones ("rørbund" over "bund").
KEYWORDS = {
    "bed": ["vandløbsbund", "bundpunkt", "bund", "bed", "channel bed", "thalweg", "streambed", "riverbed",
            "bottom", "invert of channel"],
    "bank_top": ["kronekant", "krone", "top of bank", "bank top", "top bank", "brink top", "skråningstop",
                 "øverste kant"],
    "bank_toe": ["bundkant", "brinkfod", "skråningsfod", "fod", "toe of bank", "bank toe", "toe"],
    "water_level": ["vandspejl", "vandstand", "vsp", "water level", "water surface", "waterline", "water"],
    "terrain": ["terræn", "terraen", "terrænpunkt", "ground", "terrain", "natural ground", "mark"],
    "pipe_invert": ["rørbund", "bundløb", "rør bund", "pipe invert", "invert", "culvert invert",
                    "indløb", "udløb", "rørunderkant"],
    "pipe_top": ["rørtop", "isse", "rør top", "pipe top", "crown", "obvert", "soffit of pipe"],
    "bridge_deck": ["brodæk", "underkant bro", "bro", "bridge deck", "bridge", "soffit", "deck"],
    "weir_crest": ["styrt", "stryg", "overløb", "overfald", "stemmeværk", "weir", "crest", "spillway",
                   "drop"],
    "drain_outlet": ["drænudløb", "drænrør", "dræn", "drain outlet", "drain", "outfall"],
    "staff_gauge": ["skalapæl", "vandstandspæl", "pegel", "staff gauge", "gauge", "gage"],
    "knick": ["knækpunkt", "knæk", "break point", "breakpoint", "break", "grade break"],
    "other": ["andet", "diverse", "other", "misc"],
}

# Abbreviations matched against the code itself (after removing a side suffix and digits).
# Single letters are ambiguous between lists, so they only give "unsure".
ABBREVIATIONS = {
    "bed": ["B", "VB", "BUND", "BED", "BB", "BT", "THW"],
    "bank_top": ["KK", "KR", "TOB", "TB", "BTOP"],
    "bank_toe": ["BK", "BF", "TOE", "FOD"],
    "water_level": ["VS", "VSP", "WS", "WL", "WSE", "VAND"],
    "terrain": ["T", "TR", "TER", "GND", "GR", "NG", "TP"],
    "pipe_invert": ["RB", "INV", "IL", "RUK", "BL"],
    "pipe_top": ["RT", "PTOP", "TOP", "CR", "RTOP"],
    "bridge_deck": ["BRO", "BRDG", "BR", "BD"],
    "weir_crest": ["STY", "ST", "WEIR", "OL", "WR"],
    "drain_outlet": ["DR", "DRN", "DU", "DRAIN"],
    "staff_gauge": ["SP", "GAUGE", "SG", "VP"],
    "knick": ["K", "BRK", "KN", "KNK"],
    "other": ["X", "MISC", "AND"],
}

SIDE_WORDS = {"left": ("venstre", "left", "vstr", "v."), "right": ("højre", "hoejre", "right", "h.")}
SIDE_SUFFIX = {"V": "left", "L": "left", "H": "right", "R": "right"}

CODE_HEADERS = ("code", "kode", "koder", "punktkode", "feature code", "survey code", "nr", "id")
DESC_HEADERS = ("description", "beskrivelse", "betydning", "tekst", "navn", "name", "desc", "forklaring")
TYPE_HEADERS = ("point_type", "punkttype", "geodrafter type", "plugin type")


@dataclass
class CodeRow:
    code: str
    description: str = ""
    given_type: str = ""            # a point type stated in the list itself (our YAML), if any
    given_reason: str = ""          # why (e.g. the VASP tag), shown to the user
    given_sure: bool = True


@dataclass
class Suggestion:
    point_type: str
    confidence: str                  # sure / unsure / unknown
    reason: str
    side: Optional[str] = None       # "left" / "right" for V/H, L/R variants
    base_code: str = ""              # the code without its side suffix


@dataclass
class MappedCode:
    row: CodeRow
    suggestion: Suggestion
    point_type: str = ""             # the user's choice (starts as the suggestion)

    def __post_init__(self):
        if not self.point_type:
            self.point_type = self.suggestion.point_type


@dataclass
class CodeList:
    rows: List[CodeRow] = field(default_factory=list)
    source: str = ""
    warnings: List[str] = field(default_factory=list)


# -- reading -------------------------------------------------------------------------------

def _norm(s):
    return re.sub(r"[_\s]+", " ", (s or "").replace("﻿", "").strip().lower())


def _sniff(lines):
    from .readers.tabular import sniff_separator
    return sniff_separator(lines)


def parse_text(text, source=""):
    """A code list from delimited text (CSV/TXT, semicolon, tab, comma or pasted columns)."""
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    out = CodeList(source=source)
    if not lines:
        out.warnings.append("The list is empty.")
        return out
    sep = _sniff(lines)
    rows = list(csv.reader(lines, delimiter=sep))
    if len(rows[0]) == 1 and sep != "\t":
        # one column: "B  Bund" separated by spaces
        rows = [re.split(r"\s{2,}|\s+[-–=:]\s+|\s", r[0].strip(), maxsplit=1) for r in rows]
    head = [_norm(c) for c in rows[0]]
    ci = di = ti = None
    if any(h in CODE_HEADERS for h in head) or any(h in DESC_HEADERS for h in head):
        for i, h in enumerate(head):
            if ci is None and h in CODE_HEADERS:
                ci = i
            elif di is None and h in DESC_HEADERS:
                di = i
            elif ti is None and h in TYPE_HEADERS:
                ti = i
        rows = rows[1:]
    if ci is None:
        ci = 0
    if di is None:
        di = 1 if ci == 0 else 0
    seen = set()
    for r in rows:
        code = r[ci].strip() if ci < len(r) else ""
        if not code:
            continue
        if code.upper() in seen:
            out.warnings.append("Code '%s' appears more than once – the first is used." % code)
            continue
        seen.add(code.upper())
        desc = r[di].strip() if di is not None and di < len(r) else ""
        given = r[ti].strip() if ti is not None and ti < len(r) else ""
        out.rows.append(CodeRow(code, desc, given if given in POINT_TYPES else ""))
    return out


def read_code_list(path):
    """A code list from a file: .yaml/.yml (our tables), .xlsx (needs openpyxl), otherwise text."""
    ext = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    if ext in (".yaml", ".yml"):
        from .codes import load_table
        t = load_table(path)
        rows = []
        for e in t.entries:
            rows.append(CodeRow(e.code, e.description, e.point_type))
            rows.extend(CodeRow(a, e.description, e.point_type) for a in e.aliases)
        return CodeList(rows, name)
    if ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            raise ValueError("Excel files need the Python package openpyxl, which this QGIS does not have – "
                             "save the sheet as CSV and open that.")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        buf = io.StringIO()
        w = csv.writer(buf, delimiter="\t", lineterminator="\n")
        for row in ws.iter_rows(values_only=True):
            w.writerow(["" if v is None else str(v) for v in row])
        return parse_text(buf.getvalue(), name)
    from .readers.common import read_text_file
    text = read_text_file(path)
    if vasp.looks_like_vasp(text):
        return vasp_code_list(text, name)
    return parse_text(text, name)


def vasp_code_list(text, source=""):
    """A CodeList from a VASPGPS tag file / tag list / .fxl library, each code typed by its VASP tag."""
    title, rows, warnings = vasp.parse(text)
    out = CodeList(source=title or source, warnings=list(warnings))
    for code, tag, desc in rows:
        c = vasp.classify(code, tag)
        if c is None:
            out.rows.append(CodeRow(code, desc))
            continue
        typ, _side, sure, reason = c
        out.rows.append(CodeRow(code, desc or reason.split("(", 1)[-1].rstrip(")"), typ, reason, sure))
    return out


# -- suggesting -----------------------------------------------------------------------------

def _side_of(code, desc):
    d = " %s " % _norm(desc)
    for side, words in SIDE_WORDS.items():
        if any(re.search(r"(^|\W)%s(\W|$)" % re.escape(w.rstrip(".")), d) for w in words if len(w) > 2):
            return side
    return None


def _strip(code):
    """(base code, side) – digits/separators removed, a trailing V/H/L/R taken as side when the rest
    is a known abbreviation."""
    c = re.sub(r"[\s_\-./]*\d+$", "", code.strip().upper())
    known = {a for v in ABBREVIATIONS.values() for a in v}
    if len(c) >= 3 and c[-1] in SIDE_SUFFIX and c[:-1] in known and c not in known:
        return c[:-1], SIDE_SUFFIX[c[-1]]
    return c, None


def _desc_hits(desc):
    """[(keyword length, type, keyword)] of keywords found in a description."""
    d = " %s " % _norm(desc)
    hits = []
    for t, words in KEYWORDS.items():
        for w in words:
            if re.search(r"(^|[^a-zæøå])%s" % re.escape(w), d):
                hits.append((len(w), t, w))
    return hits


def _first_type(desc, hits):
    d = " %s " % _norm(desc)
    best = None
    for _l, t, w in hits:
        m = re.search(r"(^|[^a-zæøå])%s" % re.escape(w), d)
        if m and (best is None or m.start() < best[0] or (m.start() == best[0] and len(w) > best[2])):
            best = (m.start(), t, len(w))
    return best[1] if best else None


def suggest(code, description=""):
    """A point type for one code, with confidence and reason."""
    v = vasp.classify(code)
    if v is not None:
        typ, vside, sure, reason = v
        return Suggestion(typ, SURE if sure else UNSURE, reason, vside, code.strip().upper())
    base, side = _strip(code)
    side = side or _side_of(code, description)
    hits = _desc_hits(description) if description else []
    desc_type = desc_word = None
    ambiguous = False
    others = []
    if hits:
        top = max(h[0] for h in hits)
        desc_type = sorted({h[1] for h in hits if h[0] == top})[0]
        desc_word = next(h[2] for h in hits if h[0] == top and h[1] == desc_type)
        # another type's keyword counts against it unless it is part of the winning word
        # ("bundkant" contains "bund"), so "udløb af dræn" stays uncertain
        others = sorted({h[1] for h in hits if h[1] != desc_type and h[2] not in desc_word})
        ambiguous = bool(others)
    abbr_type = None
    for t, abbrs in ABBREVIATIONS.items():
        if base in abbrs:
            abbr_type = t
            break
    if desc_type and not ambiguous:
        if abbr_type and abbr_type != desc_type:
            return Suggestion(desc_type, UNSURE, "the word '%s' in the description says %s, the code '%s' "
                              "usually means %s" % (desc_word, desc_type, base, abbr_type), side, base)
        why = "the word '%s' in the description" % desc_word
        if abbr_type == desc_type:
            why += " and the code '%s'" % base
        return Suggestion(desc_type, SURE, why, side, base)
    if desc_type and ambiguous:
        types = sorted([desc_type] + others)
        first = _first_type(description, hits)
        if abbr_type and abbr_type == first:
            return Suggestion(first, SURE, "the code '%s' and the first word of the description agree" % base,
                              side, base)
        pick = abbr_type if abbr_type in types else desc_type
        why = "the description fits several types (%s)" % ", ".join(types)
        return Suggestion(pick, UNSURE, why, side, base)
    if abbr_type:
        if len(base) >= 2:
            return Suggestion(abbr_type, SURE if not description else UNSURE,
                              "the code '%s' is a common abbreviation" % base
                              + ("" if not description else ", the description gives no keyword"), side, base)
        return Suggestion(abbr_type, UNSURE, "the one-letter code '%s' often means %s" % (base, abbr_type),
                          side, base)
    return Suggestion("other", UNKNOWN, "no keyword or known abbreviation", side, base)


def map_codes(code_list):
    """MappedCode for every row; a type given in the list itself is taken as sure."""
    out = []
    for r in code_list.rows:
        if r.given_type:
            s = Suggestion(r.given_type, SURE if r.given_sure else UNSURE,
                           r.given_reason or "the type is given in the list", None, r.code.upper())
        else:
            s = suggest(r.code, r.description)
        out.append(MappedCode(r, s))
    return out


# -- building a table ------------------------------------------------------------------------

def build_table(name, mapped, description="", base=None, case_sensitive=False, prefix_match=True):
    """A CodeTable from the user's choices. Left/right variants whose base code is in the list with the
    same type become aliases of it. Attributes (Profil, Diameter …) are taken from ``base`` (default:
    the GeoDrafter standard table) by point type, so the Emlid Flow code library export keeps them."""
    base = base or standard_table()
    attrs_by_type = {}
    for e in base.entries:
        attrs_by_type.setdefault(e.point_type, list(e.attributes))
    entries = {}
    order = []
    for m in mapped:
        t = m.point_type if m.point_type in POINT_TYPES else "other"
        code = m.row.code.strip()
        b = m.suggestion.base_code
        if m.suggestion.side and b and b.upper() != code.upper():
            key = next((k for k in order if k.upper() == b.upper()), None)
            if key is not None and entries[key].point_type == t:
                entries[key].aliases.append(code)
                continue
        if any(k.upper() == code.upper() for k in order):
            continue
        entries[code] = CodeEntry(code, t, m.row.description, [], list(attrs_by_type.get(t, [])))
        order.append(code)
    used_attrs = {a for e in entries.values() for a in e.attributes}
    defs = {k: v for k, v in base.attribute_defs.items() if k in used_attrs or k == base.profile_attribute}
    return CodeTable(name, [entries[k] for k in order], description=description,
                     case_sensitive=case_sensitive,
                     prefix_match=prefix_match, attribute_defs=defs, profile_attribute=base.profile_attribute)


def extend_table(table, mapped):
    """``table`` plus the mapped codes it does not have yet (for "Unknown codes in the file")."""
    d = table.to_dict()
    have = {c["code"].upper() for c in d["codes"]}
    have |= {a.upper() for c in d["codes"] for a in c.get("aliases", [])}
    attrs = {}
    for c in d["codes"]:
        attrs.setdefault(c["type"], c.get("attributes", []))
    for m in mapped:
        if m.row.code.upper() in have:
            continue
        row = {"code": m.row.code, "type": m.point_type, "description": m.row.description}
        if attrs.get(m.point_type):
            row["attributes"] = list(attrs[m.point_type])
        d["codes"].append(row)
        have.add(m.row.code.upper())
    return table_from_dict(d, table.name)


def unknown_codes(survey, table):
    """CodeRows for the codes of a survey that the table does not know (first description kept)."""
    out, seen = [], set()
    for p in survey.points:
        c = (p.code or "").strip()
        if c and table.lookup(c) is None and c.upper() not in seen:
            seen.add(c.upper())
            out.append(CodeRow(c, p.description))
    return CodeList(out, "survey")


def with_vasp_codes(survey, table, min_share=0.5):
    """``table`` extended with the survey's VASP codes it does not know, or None.

    Used on import: when at least ``min_share`` of the unknown codes are VASP codes, they are paired
    automatically, so a survey made with VASPGPS codes needs no code table of its own."""
    unknown = unknown_codes(survey, table)
    if not unknown.rows or vasp.survey_share([r.code for r in unknown.rows]) < min_share:
        return None
    mapped = [m for m in map_codes(unknown) if m.suggestion.reason.startswith(("VASP", "VASPGPS"))]
    if not mapped:
        return None
    t = extend_table(table, mapped)
    t.name = "%s + VASP" % table.name
    return t, mapped


VASP_TABLE_NAME = "VASP codes (VASPGPS)"


def vasp_table():
    """The built-in VASP table: one code per VASP tag (VASPGPS's own names), other known names as aliases.

    Numbered variants such as ``17ProfilKant`` are not listed; they are paired on import
    (``with_vasp_codes``)."""
    rows = []
    for tag in sorted(vasp.NAMES):
        typ, _side, _sure, what = vasp.TAGS[tag]
        names = vasp.NAMES[tag]
        rows.append({"code": names[0], "type": typ, "description": "VASP tag %d: %s" % (tag, what),
                     "aliases": names[1:]})
    base = standard_table()
    attrs = {}
    for e in base.entries:
        attrs.setdefault(e.point_type, list(e.attributes))
    for r in rows:
        if attrs.get(r["type"]):
            r["attributes"] = list(attrs[r["type"]])
        if not r["aliases"]:
            del r["aliases"]
    d = {"name": VASP_TABLE_NAME,
         "description": "VASP/VASPGPS field codes, typed by their VASP tag. Numbered variants of the names "
                        "(e.g. 17ProfilKant) are recognised automatically on import.",
         "case_sensitive": False, "prefix_match": True,
         "attributes": dict(base.attribute_defs), "profile_attribute": base.profile_attribute, "codes": rows}
    return table_from_dict(d, VASP_TABLE_NAME)


def slug(name):
    s = re.sub(r"[^a-z0-9æøå]+", "_", (name or "").lower()).strip("_")
    return s.replace("æ", "ae").replace("ø", "oe").replace("å", "aa") or "code_table"
