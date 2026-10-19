# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Coordinate formats – a Python port of GeoDrafter's coordinate logic
(geodrafter.com static/js/geo.js + coordfmt.js): DD, DMS, DDM, UTM (Krüger
series to n⁴, incl. the Norway/Svalbard zone exceptions) and MGRS.

Pure Python, no QGIS. Input is WGS84 latitude/longitude in decimal degrees.
"""

import math

BANDS = "CDEFGHJKLMNPQRSTUVWX"
MGRS_COLS = ("STUVWXYZ", "ABCDEFGH", "JKLMNPQR")  # by zone % 3
MGRS_ROWS = "ABCDEFGHJKLMNPQRSTUV"

_A = 6378137.0
_F = 1 / 298.257223563
_K0 = 0.9996
_N = _F / (2 - _F)
_E = math.sqrt(_F * (2 - _F))
_A_RECT = (_A / (1 + _N)) * (1 + _N ** 2 / 4 + _N ** 4 / 64)
_ALPHA = (
    _N / 2 - 2 * _N ** 2 / 3 + 5 * _N ** 3 / 16 + 41 * _N ** 4 / 180,
    13 * _N ** 2 / 48 - 3 * _N ** 3 / 5 + 557 * _N ** 4 / 1440,
    61 * _N ** 3 / 240 - 103 * _N ** 4 / 140,
    49561 * _N ** 4 / 161280,
)


def norm_lon(lon):
    return ((lon + 180) % 360 + 360) % 360 - 180


def fmt_dd(lat, lon, digits=6):
    return "%.*f, %.*f" % (digits, lat, digits, norm_lon(lon))


def _hemi(v, is_lat):
    if is_lat:
        return "S" if v < 0 else "N"
    return "W" if v < 0 else "E"


def to_dms(v, is_lat, dec=2):
    """55.5 -> 55°30′00.00″N"""
    a = abs(v)
    d = math.floor(a)
    m = math.floor((a - d) * 60)
    s = ((a - d) * 60 - m) * 60
    if round(s, dec) >= 60:
        s, m = 0.0, m + 1
    if m >= 60:
        m, d = 0, d + 1
    return "%d°%02d′%0*.*f″%s" % (d, m, dec + 3, dec, s, _hemi(v, is_lat))


def to_ddm(v, is_lat, dec=4):
    """55.5 -> 55°30.0000′N"""
    a = abs(v)
    d = math.floor(a)
    m = (a - d) * 60
    if round(m, dec) >= 60:
        m, d = 0.0, d + 1
    return "%d°%0*.*f′%s" % (d, dec + 3, dec, m, _hemi(v, is_lat))


def fmt_dms(lat, lon):
    return "%s %s" % (to_dms(lat, True), to_dms(norm_lon(lon), False))


def fmt_ddm(lat, lon):
    return "%s %s" % (to_ddm(lat, True), to_ddm(norm_lon(lon), False))


def utm_zone(lat, lon):
    """(zone, north, epsg) with the Norway (32V) and Svalbard exceptions."""
    lon = norm_lon(lon)
    zone = min(60, int(math.floor((lon + 180) / 6)) + 1)
    if 56 <= lat < 64 and 3 <= lon < 12:
        zone = 32
    if 72 <= lat < 84:
        if 0 <= lon < 9:
            zone = 31
        elif 9 <= lon < 21:
            zone = 33
        elif 21 <= lon < 33:
            zone = 35
        elif 33 <= lon < 42:
            zone = 37
    north = lat >= 0
    return zone, north, (32600 if north else 32700) + zone


def lat_band(lat):
    if lat < -80 or lat > 84:
        return ""
    return BANDS[min(19, int(math.floor((lat + 80) / 8)))]


def to_utm(lat, lon, zone=None):
    """dict(zone, band, hemi, easting, northing) or None outside 80°S–84°N (UPS there)."""
    if not (-80 <= lat <= 84) or not math.isfinite(lon):
        return None
    lon = norm_lon(lon)
    zone = zone or utm_zone(lat, lon)[0]
    lon0 = (zone - 1) * 6 - 180 + 3
    dl = norm_lon(lon - lon0)
    phi, lam = math.radians(lat), math.radians(dl)
    sp = math.sin(phi)
    t = math.sinh(math.atanh(sp) - _E * math.atanh(_E * sp))
    xi = math.atan2(t, math.cos(lam))
    eta = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    x, y = eta, xi
    for i, a in enumerate(_ALPHA):
        j = 2 * (i + 1)
        x += a * math.cos(j * xi) * math.sinh(j * eta)
        y += a * math.sin(j * xi) * math.cosh(j * eta)
    easting = 500000 + _K0 * _A_RECT * x
    northing = _K0 * _A_RECT * y
    if lat < 0:
        northing += 10000000
    return {"zone": zone, "band": lat_band(lat), "hemi": "S" if lat < 0 else "N",
            "easting": easting, "northing": northing}


def fmt_utm(u):
    if not u:
        return None
    return "%d%s %d E %d N" % (u["zone"], u["band"], round(u["easting"]), round(u["northing"]))


def to_mgrs(lat, lon, digits=5):
    """MGRS reference, truncated (never rounded up) to `digits` per axis (5 = 1 m)."""
    u = to_utm(lat, lon)
    if not u:
        return None
    e = math.floor(u["easting"] + 1e-6)
    n = math.floor(u["northing"] + 1e-6)
    zone = u["zone"]
    col = MGRS_COLS[zone % 3][int(e // 100000) - 1]
    row = MGRS_ROWS[(int(n // 100000) + (5 if zone % 2 == 0 else 0)) % 20]
    head = "%d%s %s%s" % (zone, u["band"], col, row)
    if not digits:
        return head
    div = 10 ** (5 - digits)
    return "%s %0*d %0*d" % (head, digits, (e % 100000) // div, digits, (n % 100000) // div)


def format_all(lat, lon):
    """[(key, label, text)] for every WGS84-based format; text is None where undefined."""
    return [
        ("dd", "Decimal degrees", fmt_dd(lat, lon)),
        ("dms", "Degrees minutes seconds", fmt_dms(lat, lon)),
        ("ddm", "Degrees decimal minutes", fmt_ddm(lat, lon)),
        ("utm", "UTM (WGS84)", fmt_utm(to_utm(lat, lon))),
        ("mgrs", "MGRS", to_mgrs(lat, lon)),
    ]
