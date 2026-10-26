# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Data model for a stream survey: surveyed points in survey order.

Pure Python (no QGIS), so the same core can be used outside QGIS.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# The plugin's own point types. Survey codes of a municipality or surveyor are
# translated to these by a code table (see ``codes.py``).
POINT_TYPES = (
    "bed",            # stream bed (bund)
    "bank_top",       # top of bank (kronekant)
    "bank_toe",       # toe of bank (bundkant / brinkfod)
    "water_level",    # water surface (vandspejl)
    "terrain",        # terrain outside the bank top (terræn)
    "pipe_invert",    # pipe / culvert invert (rørbund)
    "pipe_top",       # pipe / culvert top (rørtop)
    "bridge_deck",    # bridge deck / underside (brodæk)
    "weir_crest",     # weir / drop crest (styrt, overløbskant)
    "drain_outlet",   # drain outlet (drænudløb)
    "staff_gauge",    # staff gauge (skalapæl)
    "knick",          # break point in the profile (knækpunkt)
    "other",
)

# Solution status as reported by GNSS receivers (Emlid: FIX, FLOAT, SINGLE; some
# exports also say DGPS or MANUAL). Normalised to upper case.
SOLUTION_FIX = "FIX"
SOLUTION_FLOAT = "FLOAT"
SOLUTION_SINGLE = "SINGLE"

# Target system for Danish stream surveys
TARGET_EPSG = 25832  # ETRS89 / UTM zone 32N
TARGET_VERTICAL = "DVR90"


@dataclass
class SurveyPoint:
    """One surveyed point.

    ``seq`` is the 0-based position in the file (= survey order) and is never
    re-sorted: Emlid Flow builds lines from the order, and so does profile grouping.
    """
    seq: int
    name: str
    x: float                       # Easting
    y: float                       # Northing
    z: Optional[float]             # Elevation (DVR90 when the CS says so)
    code: str = ""
    description: str = ""
    code_description: str = ""     # Emlid's "Code description" (the code library's text), if exported
    point_type: str = "other"      # one of POINT_TYPES, from the code table
    section_role: str = ""         # "section_start" / "section_end" from the code table (VASP start/end)
    code_known: bool = False       # False when the code was not in the code table
    lon: Optional[float] = None
    lat: Optional[float] = None
    ellipsoidal_height: Optional[float] = None
    solution_status: str = ""      # FIX / FLOAT / SINGLE / … ("" if unknown)
    rms_e: Optional[float] = None  # Easting RMS [m]
    rms_n: Optional[float] = None  # Northing RMS [m]
    rms_z: Optional[float] = None  # Elevation RMS [m]
    rms_lateral: Optional[float] = None
    antenna_height: Optional[float] = None   # in metres (converted from the file's unit)
    antenna_height_raw: str = ""             # as written, with unit, for the record
    time_start: str = ""           # Averaging start, as written
    time_end: str = ""             # Averaging end, as written
    samples: Optional[int] = None
    pdop: Optional[float] = None
    cs_name: str = ""
    extra: Dict[str, str] = field(default_factory=dict)  # every other column, by header

    @property
    def is_fix(self):
        return self.solution_status == SOLUTION_FIX

    def attribute(self, name):
        """A code attribute from the export (``extra``), by name: case-insensitive, and also
        matching shapefile field names cut to 10 characters. '' when missing."""
        want = name.strip().lower()
        for k, v in self.extra.items():
            key = k.strip().lower()
            if key == want or (len(key) == 10 and want.startswith(key)):
                return str(v).strip()
        return ""


@dataclass
class Survey:
    """The points of one survey file, in survey order, with reader notes."""
    points: List[SurveyPoint] = field(default_factory=list)
    source: str = ""               # file name
    reader: str = ""               # which reader produced it
    synthetic: bool = False        # True for generated test data
    warnings: List[str] = field(default_factory=list)

    def __len__(self):
        return len(self.points)

    def __iter__(self):
        return iter(self.points)

    def apply_code_table(self, table):
        """Set ``point_type``/``code_known`` on every point from a CodeTable."""
        for p in self.points:
            p.point_type, p.code_known = table.classify(p.code, p.description)
            e = table.lookup(p.code) if p.code_known else None
            p.section_role = getattr(e, "role", "") if e is not None else ""
        self.warnings = [w for w in self.warnings if not w.startswith("Codes not in code table")]
        unknown = sorted({p.code for p in self.points if not p.code_known and p.code})
        if unknown:
            self.warnings.append(
                "Codes not in code table '%s' (set to 'other'): %s" % (table.name, ", ".join(unknown)))
        return self
