# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Write the SYNTHETIC Emlid Flow CSV used by the tests (not a real survey).

    python make_synthetic.py   (needs pyproj for Longitude/Latitude)

Two cross-sections 100 m apart on a straight stream running south-east,
codes from the GeoDrafter standard table, Emlid Flow "All columns" header.
"""

import csv
import math
import os

from pyproj import Transformer

HEADER = ["Name", "Code", "Easting", "Northing", "Elevation", "Description", "Longitude", "Latitude",
          "Ellipsoidal height", "Origin", "Easting RMS", "Northing RMS", "Elevation RMS", "Lateral RMS",
          "Antenna height", "Antenna height units", "Solution status", "Correction type",
          "Averaging start", "Averaging end", "Samples", "PDOP", "GDOP", "Base easting", "Base northing",
          "Base elevation", "Base longitude", "Base latitude", "Base ellipsoidal height", "Baseline",
          "Mount point", "CS name", "GPS Satellites", "GLONASS Satellites", "Galileo Satellites",
          "BeiDou Satellites", "QZSS Satellites"]

# (offset across, positive = right looking downstream [m], elevation above bed [m], code)
SECTION = [(-6.0, 1.35, "T"), (-2.4, 1.10, "KK"), (-1.3, 0.42, "VS"), (-1.1, 0.12, "B"),
           (-0.4, 0.0, "B"), (0.3, 0.02, "B"), (1.0, 0.15, "B"), (1.2, 0.41, "VS"), (2.5, 1.18, "KK")]
START = (541200.0, 6103400.0)      # station 0, south of Aabenraa (EPSG:25832)
AZIMUTH = math.radians(120.0)      # downstream direction, clockwise from north
BED0, SLOPE = 12.40, 0.0015        # bed DVR90 at station 0 and fall per metre
GEOID = 38.6                       # DVR90 → ellipsoidal height, approximate for the test


def _clock(sec):
    return "2026-05-12 %02d:%02d:%02d.0 UTC+02:00" % (sec // 3600, sec % 3600 // 60, sec % 60)


def rows():
    to_ll = Transformer.from_crs(25832, 4326, always_xy=True)
    dx, dy = math.sin(AZIMUTH), math.cos(AZIMUTH)      # along
    rx, ry = math.cos(AZIMUTH), -math.sin(AZIMUTH)     # right of downstream
    t = 9 * 3600 + 12 * 60
    out = []
    for prof, station in ((1, 0.0), (2, 100.0)):
        cx, cy = START[0] + dx * station, START[1] + dy * station
        bed = BED0 - SLOPE * station
        for k, (off, dz, code) in enumerate(SECTION, start=1):
            if prof == 2 and code == "T":
                continue  # terrain control point only on every few sections
            x, y = cx + rx * off, cy + ry * off
            out.append(("P%02d-%02d" % (prof, k), code, x, y, bed + dz, "", "FIX", t))
            t += 25
    # culvert invert and a drain outlet between the sections
    extra = (("RB1", "RB", 55.0, 0.0, 0.05, "Rørbund indløb Ø600", "FIX"),
             ("DR1", "DR", 72.0, 2.3, 0.55, "Drænudløb Ø110", "FLOAT"))
    for name, code, st, off, dz, desc, status in extra:
        x, y = START[0] + dx * st + rx * off, START[1] + dy * st + ry * off
        out.append((name, code, x, y, BED0 - SLOPE * st + dz, desc, status, t))
        t += 40
    result = []
    for name, code, x, y, z, desc, status, sec in out:
        lon, lat = to_ll.transform(x, y)
        start, end = _clock(sec), _clock(sec + 5)
        float_ = status == "FLOAT"
        result.append([name, code, "%.3f" % x, "%.3f" % y, "%.3f" % z, desc, "%.9f" % lon, "%.9f" % lat,
                       "%.3f" % (z + GEOID), "Global", "0.008" if not float_ else "0.094",
                       "0.009" if not float_ else "0.121", "0.014" if not float_ else "0.187",
                       "0.012" if not float_ else "0.153", "1.800", "m", status, "NTRIP",
                       start, end, "5", "1.3", "1.6", "", "", "", "", "", "", "",
                       "GPSNet_RTCM32", "ETRS89 / UTM zone 32N + DVR90 height", "9", "6", "8", "7", "0"])
    return result


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "emlid_flow_SYNTHETIC.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        w.writerows(rows())


if __name__ == "__main__":
    main()
