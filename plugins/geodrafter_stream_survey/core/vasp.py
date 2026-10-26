# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""VASP / VASPGPS codes → the plugin's point types (pure Python).

Many Danish municipalities and consultants survey streams for the VASP
program. A VASPGPS setup gives every VASP *tag* (a fixed number with a fixed
meaning, e.g. tag 112 = a section point that is also the water level) a field
code of the organisation's own choosing, e.g. ``VANDSPEJL`` or
``9VandSpejl``. This module knows the meaning of the tags – written here in our
own words as point types – and recognises:

* a VASPGPS tag file (``[TAGS]`` with ``TAG_<n>=<code>``, ``.ini``/``.txt``),
* a tag list with numbers and quoted codes (``<n>  "CODE"  "text``),
* a Trimble feature library (``.fxl``) made for VASPGPS (codes such as
  ``13ProfilPkt``; the tag is found from the name),
* single field codes in a survey (``PROFILPKTK``, ``17ProfilKant``, ``47Terren_V`` …).

No code files of others are shipped. Functionality and file formats are not
protected; the type of each tag is our own interpretation for this plugin.
"""

import re
import unicodedata

# tag -> (point type, side or None, confident?, what the tag means)
TAGS = {
    100: ("terrain", "left", False, "first point of a cross-section, left side"),
    101: ("terrain", "right", False, "first point of a cross-section, right side"),
    110: ("knick", None, True, "ordinary cross-section point"),
    111: ("bank_top", None, True, "cross-section point with an edge mark (bank top)"),
    112: ("water_level", None, True, "cross-section point that is also the water level"),
    113: ("bed", None, True, "cross-section point in mid-stream"),
    114: ("knick", None, False, "cross-section point at a bridge pier"),
    120: ("bridge_deck", None, True, "top of the bridge deck in a cross-section"),
    199: ("terrain", None, False, "last point of a cross-section"),
    200: ("drain_outlet", "left", True, "pipe inflow on the left, invert"),
    201: ("drain_outlet", "right", True, "pipe inflow on the right, invert"),
    202: ("drain_outlet", "right", False, "open ditch inflow on the right"),
    203: ("drain_outlet", "left", False, "open ditch inflow on the left"),
    204: ("staff_gauge", "left", True, "staff gauge on the left"),
    205: ("staff_gauge", "right", True, "staff gauge on the right"),
    206: ("terrain", "left", True, "intermediate point, terrain on the left"),
    207: ("terrain", "right", True, "intermediate point, terrain on the right"),
    209: ("other", None, True, "intermediate point at the stream centre (elevation not used)"),
    210: ("water_level", None, True, "intermediate point, water level"),
    220: ("other", None, True, "bend in the stream between cross-sections (elevation not used)"),
    221: ("bed", None, True, "intermediate point on the bed"),
    231: ("other", "left", True, "other point on the left (text only)"),
    232: ("other", "right", True, "other point on the right (text only)"),
    233: ("other", None, True, "other point (text only)"),
    234: ("bed", None, False, "fixed (hard) bed"),
    235: ("bank_top", "left", True, "bank top on the left"),
    236: ("bank_top", "right", True, "bank top on the right"),
    240: ("pipe_top", "left", True, "pipe inflow on the left, top of pipe"),
    241: ("pipe_top", "right", True, "pipe inflow on the right, top of pipe"),
    300: ("pipe_invert", None, True, "pipe/culvert inlet, invert"),
    301: ("pipe_top", None, True, "pipe/culvert inlet, top of pipe"),
    302: ("pipe_invert", None, True, "pipe/culvert outlet, invert"),
    303: ("pipe_top", None, True, "pipe/culvert outlet, top of pipe"),
    304: ("other", None, True, "pipe/culvert, sediment level"),
    305: ("water_level", None, True, "pipe/culvert, water level"),
    306: ("terrain", None, True, "pipe/culvert, terrain"),
    307: ("bridge_deck", None, True, "pipe bridge, top of deck"),
    400: ("other", None, True, "manhole, cover (terrain)"),
    401: ("other", None, True, "manhole, bottom"),
    402: ("other", None, True, "manhole, sediment level"),
    403: ("other", None, True, "manhole inlet, terrain"),
    404: ("pipe_invert", None, True, "manhole inlet pipe, invert"),
    405: ("other", None, True, "manhole inlet, sediment level"),
    406: ("other", None, True, "manhole outlet, terrain"),
    407: ("pipe_invert", None, True, "manhole outlet pipe, invert"),
    408: ("other", None, True, "manhole outlet, sediment level"),
    409: ("other", None, True, "manhole, water level"),
    410: ("drain_outlet", "left", True, "drain inflow on the left inside a manhole"),
    411: ("drain_outlet", "right", True, "drain inflow on the right inside a manhole"),
    992: ("other", None, True, "VASPGPS command: delete the current object (not a survey point)"),
}

# Field-code names seen for each tag (normalised: upper case, letters/digits only, no leading number).
NAMES = {
    100: ["PROFILSTARTV"], 101: ["PROFILSTARTH"],
    110: ["PROFILPKT"], 111: ["PROFILPKTK", "PROFILKANT"], 112: ["VANDSPEJL"],
    113: ["MIDTSTROMS", "PROFILMIDT"], 114: ["PROFILPKTPPILLE", "PROFILPKTPILLE"],
    120: ["PROFBRODAEK", "PROFILBRODEK", "PROFILBRODAEK"], 199: ["PROFILSLUT"],
    200: ["RORTILLOBV", "RORTILLOBVBUND"], 201: ["RORTILLOBH", "RORTILLOBHBUND"],
    202: ["GROFTTILLOBH"], 203: ["GROFTTILLOBV"], 204: ["SKALAPELV"], 205: ["SKALAPELH"],
    206: ["MPTERV", "TERRENV"], 207: ["MPTERH", "TERRENH"], 209: ["MPMIDT", "MIDTVANDLOB"],
    210: ["MPVSP"], 220: ["KNEKPKT"], 221: ["BUNDPUNKT", "BUNDKOTE"],
    231: ["ANDETV"], 232: ["ANDETH"], 233: ["ANDETM"], 234: ["FASTBUND"],
    235: ["KRONEV"], 236: ["KRONEH"], 240: ["RORTILLOBVTOP"], 241: ["RORTILLOBHTOP"],
    300: ["RORINDBUND", "RORINDLOBBUND"], 301: ["RORINDTOP", "RORINDLOBTOP"],
    302: ["RORUDBUND", "RORUDLOBBUND"], 303: ["RORUDTOP", "RORUDLOBTOP"],
    304: ["RORSAND"], 305: ["RORVSP"], 306: ["RORTERREN"], 307: ["RORBRODAEK", "RORBRODEK"],
    400: ["BRNTER", "BRONDDEKSEL"], 401: ["BRNBUND", "BRONDBUND"], 402: ["BRNSAND", "BRONDSAND"],
    403: ["BRNINDTER", "BRONDRORINDTERREN"], 404: ["BRNINDBUND", "BRONDRORINDLOB"],
    405: ["BRNINDSAND", "BRONDRORINDSAND"], 406: ["BRNUDTER", "BRONDRORUDTERREN"],
    407: ["BRNUDBUND", "BRONDRORUDLOB"], 408: ["BRNUDSAND", "BRONDRORUDSAND"], 409: ["BRNVSP"],
    410: ["BRNDRANV", "BRONDDRAENV"], 411: ["BRNDRANH", "BRONDDRAENH"], 992: ["KILL"],
}

# Codes found in VASPGPS feature libraries that are not VASP tags (notes, photos, bed material …).
EXTRA = {
    "NETPUNKT": ("other", "control point"),
    "FIX": ("other", "fixed point"),
    "FOTO": ("other", "photo"),
    "BRAEMMEKANT": ("other", "edge of the buffer strip"),
    "SAND": ("other", "bed material: sand"), "STEN": ("other", "bed material: stones"),
    "GRUS": ("other", "bed material: gravel"), "MUDDER": ("other", "bed material: mud"),
    "SASTGRMU": ("other", "bed material"),
    "BJORNEKLO": ("other", "plant: giant hogweed"), "RODHESTEHOV": ("other", "plant: butterbur"),
    "PILEURT": ("other", "plant: knotweed"),
}
_OVERGANG = re.compile(r"^OVERGANG\d*$")

_BY_NAME = {n: tag for tag, names in NAMES.items() for n in names}


def norm(code):
    """'12PROFILSTART_V', '47Terren_V', 'PROFBRODÆK' → 'PROFILSTARTV', 'TERRENV', 'PROFBRODAEK'."""
    s = (code or "").strip().upper()
    s = s.replace("Æ", "AE").replace("Ø", "OE").replace("Å", "AA")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Z0-9]", "", s)
    return re.sub(r"^\d+", "", s)


def tag_for_code(code):
    """The VASP tag a field code stands for, or None."""
    return _BY_NAME.get(norm(code))


def describe(tag):
    t = TAGS.get(tag)
    return "VASP tag %d (%s)" % (tag, t[3]) if t else "VASP tag %d" % tag


def classify(code, tag=None):
    """(point type, side, confident, reason) for a VASP code, or None when it is not one.

    ``tag`` comes from a tag file; without it the tag is found from the name."""
    if tag is None:
        tag = tag_for_code(code)
    if tag in TAGS:
        typ, side, sure, _what = TAGS[tag]
        return typ, side, sure, describe(tag)
    n = norm(code)
    if n in EXTRA:
        typ, what = EXTRA[n]
        return typ, None, True, "VASPGPS feature library code (%s)" % what
    if _OVERGANG.match(n):
        return "other", None, True, "VASPGPS feature library code (transition marker)"
    return None


# -- tag files --------------------------------------------------------------------------------

_INI_TAG = re.compile(r"^\s*TAG_(\d+)\s*=\s*(.*?)\s*$", re.I)
_LIST_TAG = re.compile(r'^\s*(\d+)\s+"([^"]+)"\s*(?:"([^"]*)"?)?\s*$')
_FXL_CODE = re.compile(r'<(?:Point|Line|Polygon)FeatureDefinition\b[^>]*\bCode="([^"]+)"')


def looks_like_vasp(text):
    return ("[TAGS]" in text.upper() and re.search(r"^\s*TAG_\d+\s*=", text, re.M | re.I) is not None) or \
        bool(re.search(r'^\s*1\d\d\s+"PROFIL', text, re.M)) or \
        ("FeatureCodingDefinitions" in text and bool(re.search(r'Code="\d*Profil', text, re.I)))


def parse(text):
    """(name, [(code, tag or None, description)], warnings) from a VASPGPS tag file, a numbered tag
    list or a Trimble .fxl feature library. Sub-codes (cross-section kinds) are skipped."""
    name, rows, warnings = "", [], []
    if "FeatureCodingDefinitions" in text:
        seen = set()
        for code in _FXL_CODE.findall(text):
            if code.upper() not in seen:
                seen.add(code.upper())
                rows.append((code, None, ""))
        return name, rows, warnings
    section = ""
    skipped = 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(";"):
            continue
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].strip().upper()
            continue
        low = s.lower()
        if low in ("hovedkoder", "main codes"):
            section = "TAGS"
            continue
        if low in ("underkoder", "sub codes", "subcodes"):
            section = "SUBTAGS"
            continue
        if section == "NAVN" and s.upper().startswith("NAVN="):
            name = s.split("=", 1)[1].strip()
            continue
        m = _INI_TAG.match(s)
        if m:
            if section == "SUBTAGS":
                skipped += 1
            elif m.group(2):
                rows.append((m.group(2), int(m.group(1)), ""))
            continue
        m = _LIST_TAG.match(s)
        if m:
            if section == "SUBTAGS":
                skipped += 1
            else:
                rows.append((m.group(2), int(m.group(1)), (m.group(3) or "").strip()))
    if skipped:
        warnings.append("%d VASP sub-codes (kind of cross-section: normal, bridge, weir …) are not point "
                        "codes and were skipped." % skipped)
    # one code may serve several tags (e.g. the water level in a section, at a pipe and in a manhole):
    # keep the first, which is the section/stream meaning
    out, seen = [], {}
    for code, tag, desc in rows:
        key = code.strip().upper()
        if key in seen:
            if TAGS.get(seen[key], ("",))[0] != TAGS.get(tag, ("",))[0]:
                warnings.append("Code '%s' is used for VASP tags %s and %s – the first is used."
                                % (code, seen[key], tag))
            continue
        seen[key] = tag
        out.append((code, tag, desc))
    return name, out, warnings


def survey_share(codes):
    """Share (0–1) of the distinct, non-empty codes that are VASP codes."""
    distinct = {c.strip().upper() for c in codes if c and c.strip()}
    if not distinct:
        return 0.0
    return sum(1 for c in distinct if classify(c) is not None) / len(distinct)
