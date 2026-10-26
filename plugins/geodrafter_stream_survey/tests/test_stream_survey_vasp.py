# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""VASP / VASPGPS codes are paired automatically (synthetic files in the three formats, written for
these tests – no code files of others)."""

import os

from geodrafter_stream_survey.core import codes, vasp
from geodrafter_stream_survey.core.codemap import (
    SURE, UNSURE, build_table, map_codes, read_code_list, suggest, unknown_codes, with_vasp_codes)
from geodrafter_stream_survey.core.model import POINT_TYPES
from geodrafter_stream_survey.core.readers import read_survey

HERE = os.path.dirname(os.path.abspath(__file__))
EMLID = os.path.join(HERE, "data", "emlid_flow_SYNTHETIC.csv")

# a VASPGPS tag file in the style of a consultant's setup: numbered field codes, ISO-8859-1
TAG_FILE = """
[NAVN]
NAVN=Rådgiver Test

[TAGS]
TAG_100=12PROFILSTART_V
TAG_101=11PROFILSTART_H
TAG_110=13PROFILPKT
TAG_111=17PROFILKANT
TAG_112=9VANDSPEJL
TAG_113=15PROFILMIDT
TAG_199=14PROFILSLUT
TAG_200=41RORTILLOB_V_BUND
TAG_221=54BUNDKOTE
TAG_235=470KRONE_V
TAG_236=480KRONE_H
TAG_300=21RORINDLOBBUND
TAG_301=25RORINDLOBTOP
TAG_305=9VANDSPEJL
TAG_992=00KILL

[SUBTAGS]
TAG_1=NORMAL
TAG_10=STYRT
"""

# the numbered list with quoted codes and explanations
TAG_LIST = 'Hovedkoder\n100\t"PROFILSTARTV"\t"første punkt\n111\t"PROFILPKTK"\t"punkt med kant\n' \
           '112\t"VANDSPEJL"\t"også vandspejl\n221\t"BUNDPUNKT"\t"bund\n301\t"RORINDTOP"\t"rør top\n' \
           'Underkoder\n1\t"NORMAL"\t"normal\n'

FXL = """<?xml version="1.0" encoding="utf-8"?>
<FeatureCodingDefinitions SchemaVersion="2.01" xmlns="http://trimble.com/schema/fxl">
  <FeatureDefinitions>
    <PointFeatureDefinition Code="13ProfilPkt" Name="13ProfilPkt" />
    <PointFeatureDefinition Code="17ProfilKant" Name="17ProfilKant" />
    <PointFeatureDefinition Code="9VandSpejl" Name="9VandSpejl" />
    <PointFeatureDefinition Code="47Terren_V" Name="47Terren_V" />
    <PointFeatureDefinition Code="51Andet-V" Name="51Andet_V" />
    <PointFeatureDefinition Code="99Foto" Name="99Foto" />
    <PointFeatureDefinition Code="Hegn" Name="Hegn" />
  </FeatureDefinitions>
</FeatureCodingDefinitions>
"""


def test_names_and_tags():
    assert vasp.norm("12PROFILSTART_V") == "PROFILSTARTV" and vasp.norm("PROFBRODÆK") == "PROFBRODAEK"
    assert vasp.tag_for_code("17ProfilKant") == 111 and vasp.tag_for_code("PROFILPKTK") == 111
    assert vasp.tag_for_code("470KRONE_V") == 235 and vasp.tag_for_code("51Andet-V") == 231
    assert vasp.tag_for_code("KK") is None and vasp.tag_for_code("13") is None
    assert all(t[0] in POINT_TYPES for t in vasp.TAGS.values())
    assert set(vasp.NAMES) <= set(vasp.TAGS)


def test_suggest_recognises_single_vasp_codes():
    s = suggest("17PROFILKANT")
    assert (s.point_type, s.confidence) == ("bank_top", SURE) and s.reason.startswith("VASP tag 111")
    assert suggest("VANDSPEJL").point_type == "water_level"
    assert suggest("BUNDPUNKT").point_type == "bed"
    assert suggest("RORINDBUND").point_type == "pipe_invert"
    s = suggest("PROFILSTARTV")
    assert (s.point_type, s.confidence, s.side) == ("terrain", UNSURE, "left")
    assert suggest("KK").reason.startswith("the code")             # ordinary codes still go the old way


def test_tag_file(tmp_path):
    p = tmp_path / "VaspGPS_test.ini"
    p.write_bytes(TAG_FILE.encode("latin-1"))
    cl = read_code_list(str(p))
    assert cl.source == "Rådgiver Test"
    got = {m.row.code: (m.point_type, m.suggestion.confidence) for m in map_codes(cl)}
    assert got["17PROFILKANT"] == ("bank_top", SURE)
    assert got["9VANDSPEJL"] == ("water_level", SURE)               # tag 112 wins over 305 (first)
    assert got["15PROFILMIDT"] == ("bed", SURE)
    assert got["470KRONE_V"] == ("bank_top", SURE) and got["480KRONE_H"] == ("bank_top", SURE)
    assert got["21RORINDLOBBUND"] == ("pipe_invert", SURE) and got["25RORINDLOBTOP"] == ("pipe_top", SURE)
    assert got["12PROFILSTART_V"] == ("terrain", UNSURE) and got["14PROFILSLUT"][1] == UNSURE
    assert "NORMAL" not in got and "STYRT" not in got               # sub-codes are not point codes
    assert any("sub-codes" in w for w in cl.warnings)
    assert all(m.suggestion.reason.startswith("VASP tag") for m in map_codes(cl))
    t = build_table("Rådgiver Test", map_codes(cl))
    assert t.lookup("17profilkant").point_type == "bank_top"       # case-insensitive
    assert t.lookup("470KRONE_V").point_type == "bank_top"


def test_numbered_list_and_fxl(tmp_path):
    p = tmp_path / "tags.txt"
    p.write_text(TAG_LIST, encoding="utf-8")
    got = {m.row.code: m.point_type for m in map_codes(read_code_list(str(p)))}
    assert got == {"PROFILSTARTV": "terrain", "PROFILPKTK": "bank_top", "VANDSPEJL": "water_level",
                   "BUNDPUNKT": "bed", "RORINDTOP": "pipe_top"}
    f = tmp_path / "lib.fxl"
    f.write_text(FXL, encoding="utf-8")
    mapped = {m.row.code: m for m in map_codes(read_code_list(str(f)))}
    assert set(mapped) == {"13ProfilPkt", "17ProfilKant", "9VandSpejl", "47Terren_V", "51Andet-V", "99Foto",
                           "Hegn"}
    assert mapped["17ProfilKant"].point_type == "bank_top" and mapped["47Terren_V"].point_type == "terrain"
    assert mapped["99Foto"].point_type == "other" and mapped["99Foto"].suggestion.confidence == SURE
    assert mapped["Hegn"].suggestion.confidence != SURE             # not a VASP code: ordinary rules


def _vasp_survey(tmp_path):
    """The synthetic Emlid survey with the codes a VASPGPS surveyor would have used."""
    swap = {"T": "47Terren_V", "KK": "17ProfilKant", "VS": "9VandSpejl", "B": "13ProfilPkt",
            "RB": "21RorIndlobBund", "DR": "41Rortillob_V_Bund"}
    lines = open(EMLID, encoding="utf-8").read().splitlines()
    out = [lines[0]]
    for ln in lines[1:]:
        cells = ln.split(",")
        cells[1] = swap.get(cells[1], cells[1])
        out.append(",".join(cells))
    p = tmp_path / "vasp_codes.csv"
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return str(p)


def test_survey_with_vasp_codes_is_paired_on_import(tmp_path):
    path = _vasp_survey(tmp_path)
    table = codes.standard_table()
    survey = read_survey(path, code_table=table)
    assert len(unknown_codes(survey, table).rows) == 6
    found = with_vasp_codes(survey, table)
    assert found is not None
    t, mapped = found
    assert t.name.endswith("+ VASP") and len(mapped) == 6
    survey = read_survey(path, code_table=t)
    types = {p.name: p.point_type for p in survey.points}
    assert types["P01-02"] == "bank_top" and types["P01-03"] == "water_level"
    assert types["P01-01"] == "terrain" and types["RB1"] == "pipe_invert" and types["DR1"] == "drain_outlet"
    assert types["P01-04"] == "knick"                                # tag 110: ordinary section point
    assert unknown_codes(survey, t).rows == []
    assert t.lookup("KK").point_type == "bank_top"                   # the standard codes still work
    # an ordinary survey is left alone
    assert with_vasp_codes(read_survey(EMLID, code_table=table), table) is None


def test_project_import_pairs_vasp_codes(tmp_path):
    from geodrafter_stream_survey.gui.project import SurveyState
    st = SurveyState()
    st.run_import(_vasp_survey(tmp_path))
    assert len(st.vasp_codes) == 6 and st.base_code_table.name != st.code_table.name
    assert {p.point_type for p in st.survey.points} >= {"bank_top", "water_level", "terrain", "knick"}
    st.run_import(_vasp_survey(tmp_path), auto_vasp=False)
    assert st.vasp_codes == [] and st.code_table is st.base_code_table
