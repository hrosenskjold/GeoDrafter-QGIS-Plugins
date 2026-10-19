# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Read a typed coordinate for "Go to" – the inverse of coordfmt.

Pure Python, no QGIS. ``parse(text)`` returns one of

* ``{"kind": "wgs84", "lat": .., "lon": ..}`` – DD with hemisphere letters,
  DMS or DDM (anything with °, ′, ″ or N/S/E/W),
* ``{"kind": "utm", "zone": .., "north": .., "easting": .., "northing": ..}``
  – UTM ("32V 552000 6320000", "32V 552000 E 6320000 N") or MGRS
  ("32V NJ 52000 20000", "32VNJ5200020000", fewer digits = coarser square),
* ``{"kind": "xy", "a": .., "b": ..}`` – two plain numbers; the caller decides
  the CRS (lat, lon order when that CRS is geographic, as in the dock),

and raises ``ValueError`` with a short English message otherwise.

The letter after a UTM zone is the latitude band, as coordfmt writes it
(C–M south, N–X north), so "33S" means band S (northern hemisphere).
Decimal commas are accepted: "57,05 9,92".
"""

import math
import re

from . import coordfmt

_NUM = r"\d+(?:[.,]\d+)?"
_BANDS = "C-HJ-NP-X"

_MGRS = re.compile(
    r"^(\d{1,2})([%s])([A-HJ-NP-Z])([A-HJ-NP-V])(\d*)$" % _BANDS)
_UTM = re.compile(
    r"^(\d{1,2})\s*([%s])[\s,;]*(%s)\s*(?:M?E\b)?[\s,;]*(%s)\s*(?:M?N)?$" % (_BANDS, _NUM, _NUM))
_TOKEN = re.compile(r"[NSEW]|[-+]?%s|°" % _NUM)
_HEMI_SIGN = {"N": 1, "E": 1, "S": -1, "W": -1}


def _num(text):
    return float(text.replace(",", "."))


def _check(lat, lon):
    if not (-90 <= lat <= 90):
        raise ValueError("Latitude must be between -90 and 90")
    if not (-180 <= lon <= 180):
        raise ValueError("Longitude must be between -180 and 180")
    return {"kind": "wgs84", "lat": lat, "lon": coordfmt.norm_lon(lon)}


def _band_north(band):
    return band >= "N"


def _parse_mgrs(m):
    zone, band, col, row, digits = int(m.group(1)), m.group(2), m.group(3), m.group(4), m.group(5)
    if not 1 <= zone <= 60:
        raise ValueError("UTM zone must be 1–60")
    if len(digits) % 2 or len(digits) > 10:
        raise ValueError("MGRS needs the same number of digits for easting and northing")
    cols = coordfmt.MGRS_COLS[zone % 3]
    if col not in cols:
        raise ValueError("MGRS column letter %s is not used in zone %d" % (col, zone))
    k = len(digits) // 2
    size = 10 ** (5 - k)                    # side of the square the reference names
    e_in = int(digits[:k]) * size if k else 0
    n_in = int(digits[k:]) * size if k else 0
    half = size / 2 if k < 5 else 0         # centre of a coarser square
    easting = (cols.index(col) + 1) * 100000 + e_in + half
    row_i = (coordfmt.MGRS_ROWS.index(row) - (5 if zone % 2 == 0 else 0)) % 20
    northing = row_i * 100000 + n_in + half
    # The row letters repeat every 2000 km: pick the cycle that lands in the band.
    band_lat = -80 + 8 * coordfmt.BANDS.index(band)
    lon0 = (zone - 1) * 6 - 180 + 3
    band_min = coordfmt.to_utm(band_lat, lon0, zone)["northing"]
    if band_lat == 0:
        band_min = 0.0                       # band N starts at the equator (northing 0)
    while northing < band_min - 100000:
        northing += 2000000
    return {"kind": "utm", "zone": zone, "north": _band_north(band),
            "easting": easting, "northing": northing}


def _parse_utm(m):
    zone = int(m.group(1))
    if not 1 <= zone <= 60:
        raise ValueError("UTM zone must be 1–60")
    return {"kind": "utm", "zone": zone, "north": _band_north(m.group(2)),
            "easting": _num(m.group(3)), "northing": _num(m.group(4))}


def _sexagesimal(nums):
    if not 1 <= len(nums) <= 3:
        raise ValueError("Write degrees, minutes and seconds as e.g. 57°02′53″N 9°55′06″E")
    neg = nums[0].startswith("-")
    vals = [abs(_num(n)) for n in nums]
    for v in vals[1:]:
        if v >= 60:
            raise ValueError("Minutes and seconds must be below 60")
    deg = vals[0] + sum(v / 60 ** i for i, v in enumerate(vals[1:], start=1))
    return -deg if neg else deg


def _parse_angles(text):
    """DD/DMS/DDM with hemisphere letters and/or degree signs -> wgs84 dict."""
    tokens = _TOKEN.findall(text)
    letters = [t for t in tokens if t in _HEMI_SIGN]
    groups = []                              # [(letter or None, [numbers])]
    if letters:
        if len(letters) != 2:
            raise ValueError("Give one N/S and one E/W")
        prefix = tokens[0] in _HEMI_SIGN
        cur = []
        for t in tokens:
            if t == "°":
                continue
            if t in _HEMI_SIGN:
                if prefix:
                    cur = []
                    groups.append((t, cur))
                else:
                    groups.append((t, cur))
                    cur = []
            elif prefix and not groups:
                raise ValueError("Could not read the coordinate")
            else:
                cur.append(t)
        if not prefix and cur:
            raise ValueError("Every number needs its N/S/E/W")
    else:
        # Degree signs mark where each coordinate starts: lat first, then lon
        for i, t in enumerate(tokens):
            if t == "°":
                continue
            if i + 1 < len(tokens) and tokens[i + 1] == "°":
                groups.append((None, [t]))
            elif groups:
                groups[-1][1].append(t)
            else:
                raise ValueError("Could not read the coordinate")
    if len(groups) != 2:
        raise ValueError("Give both latitude and longitude")
    values = {}
    order = []
    for letter, nums in groups:
        v = _sexagesimal(nums)
        if letter:
            if nums[0].startswith("-"):
                raise ValueError("Use either a minus sign or S/W, not both")
            axis = "lat" if letter in "NS" else "lon"
            v *= _HEMI_SIGN[letter]
        else:
            axis = "lat" if not order else "lon"
        if axis in values:
            raise ValueError("Give one latitude (N/S) and one longitude (E/W)")
        values[axis] = v
        order.append(axis)
    return _check(values["lat"], values["lon"])


def parse(text):
    """Parse a typed coordinate; see the module docstring."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Type a coordinate")
    up = raw.upper().replace("Ø", "E")       # Danish "Ø" for east
    for a, b in (("′", "'"), ("’", "'"), ("″", '"'), ("”", '"'), ("''", '"'), ("º", "°")):
        up = up.replace(a, b)

    compact = re.sub(r"\s+", "", up)
    m = _MGRS.match(compact)
    if m:
        return _parse_mgrs(m)
    m = _UTM.match(up)
    if m:
        return _parse_utm(m)

    if re.search(r"[NSEW°'\"]", up):
        return _parse_angles(up.replace("'", " ").replace('"', " "))

    nums = re.findall(r"[-+]?%s" % _NUM, up)
    if len(nums) == 1 and "," in nums[0]:
        nums = nums[0].split(",")            # "552000,6320000"
    if len(nums) in (4, 6):                   # "57 02 53.4 9 55 6.1" (lat, lon)
        h = len(nums) // 2
        return _check(_sexagesimal(nums[:h]), _sexagesimal(nums[h:]))
    if len(nums) != 2 or re.sub(r"[-+\d.,;\s]", "", up):
        raise ValueError("Could not read the coordinate")
    a, b = _num(nums[0]), _num(nums[1])
    if not (math.isfinite(a) and math.isfinite(b)):
        raise ValueError("Could not read the coordinate")
    return {"kind": "xy", "a": a, "b": b}


def looks_like_lat_lon(a, b):
    """True when two plain numbers can only sensibly be latitude, longitude."""
    return abs(a) <= 90 and abs(b) <= 180
