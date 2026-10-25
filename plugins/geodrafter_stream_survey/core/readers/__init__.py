# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Readers for survey files. ``read_survey`` picks one from the file."""

import os

from .common import check_crs
from .dxf import read_dxf
from .shapefile import read_shapefile
from .tabular import LAYOUTS, read_delimited, read_emlid_csv, read_field_text

__all__ = ["read_survey", "read_emlid_csv", "read_delimited", "read_field_text", "read_shapefile",
           "read_dxf", "check_crs", "LAYOUTS"]


def read_survey(path, code_table=None, kind=None, **options):
    """Read a survey file and classify its codes.

    kind: "emlid_csv", "csv", "field_text", "shapefile", "dxf" or None (from the
    extension: .shp/.zip → shapefile, .dxf → dxf, otherwise delimited text with
    a header → emlid_csv, without → field_text when ``layout`` is given).
    options go to the reader (columns, separator, layout, label_radius …).
    """
    ext = os.path.splitext(path)[1].lower()
    if kind is None:
        if ext in (".shp", ".zip"):
            kind = "shapefile"
        elif ext == ".dxf":
            kind = "dxf"
        elif options.get("layout") is not None and options.get("has_header") is not True:
            kind = "field_text"
        else:
            kind = "emlid_csv"
    if kind == "shapefile":
        survey = read_shapefile(path, columns=options.get("columns"))
    elif kind == "dxf":
        survey = read_dxf(path, code_table=code_table, label_radius=options.get("label_radius", 1.5))
    elif kind == "field_text":
        survey = read_field_text(path, options["layout"], separator=options.get("separator"))
    elif kind == "csv":
        survey = read_delimited(path, **options)
    elif kind == "emlid_csv":
        survey = read_emlid_csv(path, columns=options.get("columns"))
    else:
        raise ValueError("Unknown reader '%s'" % kind)
    if code_table is not None:
        survey.apply_code_table(code_table)
    check_crs(survey)
    return survey
