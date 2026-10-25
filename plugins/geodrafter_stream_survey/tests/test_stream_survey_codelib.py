# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Block 9b: Emlid Flow code library with attributes, and the round trip via the Profil attribute."""

import csv
import io
import os

import pytest

from geodrafter_stream_survey.core import codes
from geodrafter_stream_survey.core.geometry import group_profiles, survey_geometry
from geodrafter_stream_survey.core.readers import read_shapefile, read_survey
from geodrafter_stream_survey.core.readers.shapefile import write_point_shapefile
from geodrafter_stream_survey.gui.project import SurveyState

HERE = os.path.dirname(os.path.abspath(__file__))
EMLID = os.path.join(HERE, "data", "emlid_flow_SYNTHETIC.csv")


def _library(table):
    return list(csv.reader(io.StringIO(codes.emlid_library_csv(table))))


def test_library_header_and_attributes():
    rows = _library(codes.standard_table())
    head = rows[0]
    assert head == ["Code", "Description", "Type", "Color", "Attribute_1", "Attribute_Type_1",
                    "Attribute_2", "Attribute_Type_2", "Attribute_3", "Attribute_Type_3"]
    by = {r[0]: r for r in rows[1:]}
    assert all(len(r) == len(head) for r in rows)
    for c in ("B", "KK", "KKV", "BK", "VS", "T", "K"):           # all section codes get Profil
        assert by[c][4:6] == ["Profil", "Integer"], c
    assert by["RB"][4:] == ["Diameter_mm", "Number", "Materiale", "List (Beton; Plast; Ler; Stål; Andet)",
                            "Retning", "List (Indløb; Udløb)"]
    assert by["RT"][4:8] == by["DR"][4:8] == ["Diameter_mm", "Number", "Materiale",
                                              "List (Beton; Plast; Ler; Stål; Andet)"]
    assert by["RT"][8:] == ["", ""] and by["BRO"][4:] == [""] * 6 and by["X"][4:] == [""] * 6


def test_english_library_attributes():
    by = {r[0]: r for r in _library(codes.standard_table_en())[1:]}
    assert by["BED"][4:6] == ["Profile", "Integer"]
    assert by["INV"][8:10] == ["Direction", "List (Inlet; Outlet)"]


def test_attribute_validation():
    base = {"codes": [{"code": "A", "type": "bed", "attributes": ["Profil"]}]}
    with pytest.raises(codes.CodeTableError):          # undefined attribute
        codes.table_from_dict(base)
    with pytest.raises(codes.CodeTableError):          # unknown Emlid type
        codes.table_from_dict(dict(base, attributes={"Profil": "Whole number"}))
    with pytest.raises(codes.CodeTableError):
        codes.table_from_dict(dict(base, attributes={"Profil": "Integer"}, profile_attribute="Nr"))
    t = codes.table_from_dict(dict(base, attributes={"Profil": "Integer"}, profile_attribute="Profil"))
    assert t.entry_attributes(t.entries[0]) == [("Profil", "Integer")]   # not listed twice


def test_table_roundtrip_keeps_attributes(tmp_path):
    t = codes.standard_table()
    p = tmp_path / "kommune.yaml"
    codes.save_table(t, str(p))
    again = codes.load_table(str(p))
    assert again.to_dict() == t.to_dict()
    assert codes.emlid_library_csv(again) == codes.emlid_library_csv(t)


def _export_with_attributes(tmp_path, sep=","):
    """The synthetic survey as Emlid would export it with code attributes: plain point numbers
    (no P12-03 names), a Profil column, pipe attributes on RB."""
    with open(EMLID, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    head = rows[0] + ["Profil", "Diameter_mm", "Materiale", "Retning"]
    out = [head]
    for i, r in enumerate(rows[1:], start=1):
        name = r[0]
        prof = str(int(name[1:3])) if name.startswith("P") else ""
        extra = ["600", "Beton", "Indløb"] if name == "RB1" else ["", "", ""]
        out.append([str(100 + i)] + r[1:] + [prof] + extra)
    p = tmp_path / "export_attr.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        csv.writer(f, delimiter=sep, lineterminator="\n").writerows(out)
    return str(p)


@pytest.mark.parametrize("sep", [",", "\t"])
def test_roundtrip_groups_by_profil_attribute(tmp_path, sep):
    s = read_survey(_export_with_attributes(tmp_path, sep), code_table=codes.standard_table())
    assert s.points[0].attribute("profil") == "1" and s.points[0].extra["Profil"] == "1"
    rb = [p for p in s.points if p.code == "RB"][0]
    assert (rb.attribute("Diameter_mm"), rb.attribute("Materiale"), rb.attribute("Retning")) == \
        ("600", "Beton", "Indløb")
    g, u = group_profiles(s.points)                       # auto → attribute (names are plain numbers)
    assert sorted(g) == ["1", "2"] and len(g["1"]) == 9 and len(g["2"]) == 8
    assert {p.code for p in u} == {"RB", "DR"}
    geo = survey_geometry(s.points)
    assert [p.id for p in geo["profiles"]] == ["1", "2"]
    assert geo["profiles"][1].station - geo["profiles"][0].station == pytest.approx(100, abs=0.05)


def test_roundtrip_without_attribute_falls_back(tmp_path):
    s = read_survey(EMLID, code_table=codes.standard_table())
    g, _u = group_profiles(s.points)                      # no Profil column → names P01-xx
    assert sorted(g) == ["P01", "P02"]
    g2, _u = group_profiles(s.points, "attribute")        # forced: nothing to group
    assert g2 == {}


def test_attribute_values_normalised(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("Name,Code,Easting,Northing,Elevation,Profil\n"
                 "1,B,541200,6103400,12,3.0\n2,KK,541201,6103401,13,3\n3,VS,541202,6103402,12.5, 3 \n",
                 encoding="utf-8")
    g, _u = group_profiles(read_survey(str(p), code_table=codes.standard_table()).points, "attribute")
    assert list(g) == ["3"] and len(g["3"]) == 3


def test_shapefile_export_attributes_truncated(tmp_path):
    s = read_survey(_export_with_attributes(tmp_path), code_table=codes.standard_table())
    fields = ["Name", "Code", "Elevation", "Profil", "Diameter_m", "Materiale", "Retning"]
    pts = [(p.x, p.y, p.z, {"Name": p.name, "Code": p.code, "Elevation": "%.3f" % p.z,
                            "Profil": p.attribute("Profil"), "Diameter_m": p.attribute("Diameter_mm"),
                            "Materiale": p.attribute("Materiale"), "Retning": p.attribute("Retning")})
           for p in s.points]
    shp, shx, dbf = write_point_shapefile(pts, fields)
    for ext, data in ((".shp", shp), (".shx", shx), (".dbf", dbf)):
        (tmp_path / ("pts" + ext)).write_bytes(data)
    s2 = read_shapefile(str(tmp_path / "pts.shp"))
    s2.apply_code_table(codes.standard_table())
    rb = [p for p in s2.points if p.code == "RB"][0]
    assert rb.attribute("Diameter_mm") == "600"          # dbf name cut to 10 characters
    g, _u = group_profiles(s2.points)
    assert sorted(g) == ["1", "2"]


def test_state_uses_the_tables_profile_attribute(tmp_path):
    st = SurveyState()
    st.run_import(_export_with_attributes(tmp_path))
    assert st.profile_attributes()[0] == "Profil"
    st.run_centerline()
    st.run_profiles()
    assert [p.id for p in st.profiles] == ["1", "2"]
