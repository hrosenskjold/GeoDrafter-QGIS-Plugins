# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Units and number formatting for GeoDrafter Measure (pure Python, no QGIS)."""

LENGTH_UNITS = {          # key: (label, metres per unit)
    "m": ("m", 1.0),
    "km": ("km", 1000.0),
    "ft": ("ft", 0.3048),
    "mi": ("mi", 1609.344),
    "nmi": ("NM", 1852.0),
}
AREA_UNITS = {            # key: (label, square metres per unit)
    "m2": ("m²", 1.0),
    "ha": ("ha", 10000.0),
    "km2": ("km²", 1e6),
    "ac": ("acres", 4046.8564224),
    "mi2": ("mi²", 2589988.110336),
}

TOOL_URLS = {
    "distance": "https://geodrafter.com/distance-calculator/",
    "area": "https://geodrafter.com/area-calculator/",
    "radius": "https://geodrafter.com/radius-map/",
}


def _num(value, decimals):
    text = "{:,.{d}f}".format(value, d=decimals)
    return text.replace(",", " ")  # narrow no-break space as thousands separator


def _decimals(value):
    a = abs(value)
    if a >= 1000:
        return 1
    if a >= 10:
        return 2
    return 3


def fmt_length(metres, unit="m"):
    label, factor = LENGTH_UNITS[unit]
    v = metres / factor
    return "%s %s" % (_num(v, _decimals(v)), label)


def fmt_area(square_metres, unit="m2"):
    label, factor = AREA_UNITS[unit]
    v = square_metres / factor
    return "%s %s" % (_num(v, _decimals(v)), label)


def auto_length_unit(metres, imperial=False):
    if imperial:
        return "mi" if metres >= 1609.344 else "ft"
    return "km" if metres >= 1000 else "m"


def auto_area_unit(square_metres, imperial=False):
    if imperial:
        return "mi2" if square_metres >= 2589988.110336 else "ac"
    if square_metres >= 1e6:
        return "km2"
    return "ha" if square_metres >= 10000 else "m2"


def parse_length(text, default_unit="m"):
    """'2.5 km', '300', '1,5 mi' -> metres (None if not a positive number)."""
    s = (text or "").strip().lower().replace(",", ".")
    unit = default_unit
    for key in sorted(LENGTH_UNITS, key=len, reverse=True):
        label = LENGTH_UNITS[key][0].lower()
        for suffix in {key, label}:
            if s.endswith(suffix) and s[:-len(suffix)].strip() != "":
                head = s[:-len(suffix)].strip()
                try:
                    float(head)
                except ValueError:
                    continue
                s, unit = head, key
                break
        else:
            continue
        break
    try:
        value = float(s)
    except ValueError:
        return None
    if not value > 0:
        return None
    return value * LENGTH_UNITS[unit][1]
