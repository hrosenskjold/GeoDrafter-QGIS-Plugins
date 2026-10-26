# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Block 10b: code translator – any code list → code table (synthetic lists, not copied from anyone)."""

import pytest

from geodrafter_stream_survey.core import codes
from geodrafter_stream_survey.core.codemap import (
    SURE, UNKNOWN, UNSURE, build_table, extend_table, map_codes, parse_text, read_code_list, slug, suggest,
    unknown_codes)
from geodrafter_stream_survey.core.readers import read_survey

# A municipality-style appendix (invented): semicolon, Danish headers, V/H variants, æøå
DANISH = """Kode;Beskrivelse
VB;Vandløbsbund
KV;Kronekant venstre
KH;Kronekant højre
BFV;Brinkfod venstre
BFH;Brinkfod højre
VSP;Vandspejl
TER;Terræn uden for kronekant
RUK;Rørunderkant (bundløb)
RO;Rørtop / isse
BRU;Underkant bro
OL;Overløbskant styrt
DRU;Drænudløb
SKP;Skalapæl
KN;Knækpunkt
HEG;Hegn
"""

EXPECT_DA = {"VB": "bed", "KV": "bank_top", "KH": "bank_top", "BFV": "bank_toe", "BFH": "bank_toe",
             "VSP": "water_level", "TER": "terrain", "RUK": "pipe_invert", "RO": "pipe_top",
             "BRU": "bridge_deck", "OL": "weir_crest", "DRU": "drain_outlet", "SKP": "staff_gauge",
             "KN": "knick"}

ENGLISH = "code\tdescription\nBED\tChannel bed\nTOBL\tTop of bank left\nTOBR\tTop of bank right\n" \
          "WS\tWater surface\nGND\tNatural ground\nINV\tCulvert invert\nPTOP\tPipe crown\n" \
          "WEIR\tWeir crest\nDRN\tDrain outfall\nFENCE\tFence post\n"


def test_danish_list_sure_suggestions_are_right():
    cl = parse_text(DANISH, "kommune.csv")
    assert [r.code for r in cl.rows][:3] == ["VB", "KV", "KH"] and len(cl.rows) == 15
    mapped = {m.row.code: m for m in map_codes(cl)}
    for code, t in EXPECT_DA.items():
        m = mapped[code]
        assert m.suggestion.confidence == SURE, (code, m.suggestion)
        assert m.point_type == t, (code, m.suggestion)
    assert mapped["KV"].suggestion.side == "left" and mapped["KH"].suggestion.side == "right"
    assert mapped["HEG"].suggestion.confidence == UNKNOWN and mapped["HEG"].point_type == "other"
    assert "kronekant" in mapped["KV"].suggestion.reason


def test_english_tab_list():
    mapped = {m.row.code: m for m in map_codes(parse_text(ENGLISH))}
    exp = {"BED": "bed", "TOBL": "bank_top", "TOBR": "bank_top", "WS": "water_level", "GND": "terrain",
           "INV": "pipe_invert", "PTOP": "pipe_top", "WEIR": "weir_crest", "DRN": "drain_outlet"}
    for code, t in exp.items():
        assert mapped[code].point_type == t and mapped[code].suggestion.confidence == SURE, code
    assert mapped["TOBL"].suggestion.base_code == "TOB" and mapped["TOBL"].suggestion.side == "left"
    assert mapped["FENCE"].suggestion.confidence == UNKNOWN


def test_uncertain_cases_are_marked():
    assert suggest("B").confidence == UNSURE                 # one letter, no description
    assert suggest("DU", "Udløb af dræn").confidence == UNSURE
    s = suggest("KK", "Bund")                                 # code and description disagree
    assert s.confidence == UNSURE and s.point_type == "bed" and "KK" in s.reason
    assert suggest("ZZ", "").confidence == UNKNOWN
    assert suggest("T", "Terræn 10 m fra kronekant").point_type == "terrain"


def test_emlid_library_and_yaml_and_paste(tmp_path):
    lib = tmp_path / "lib.csv"
    lib.write_text(codes.emlid_library_csv(codes.standard_table()), encoding="utf-8")
    mapped = {m.row.code: m for m in map_codes(read_code_list(str(lib)))}
    assert mapped["KK"].point_type == "bank_top" and mapped["RB"].point_type == "pipe_invert"
    assert mapped["VS"].point_type == "water_level" and mapped["DR"].point_type == "drain_outlet"
    yaml_list = read_code_list(codes.STANDARD_TABLE)
    m = {x.row.code: x for x in map_codes(yaml_list)}
    assert m["K"].point_type == "knick" and m["K"].suggestion.reason == "the type is given in the list"
    pasted = parse_text("KK\tKronekant\nB\tBund\n")           # two pasted columns, no header
    assert [r.code for r in pasted.rows] == ["KK", "B"] and pasted.rows[1].description == "Bund"
    spaced = parse_text("KK  Kronekant\nVS  Vandspejl\n")
    assert [(r.code, r.description) for r in spaced.rows] == [("KK", "Kronekant"), ("VS", "Vandspejl")]


def test_cp1252_semicolon_file(tmp_path):
    p = tmp_path / "liste.csv"
    p.write_bytes(DANISH.encode("cp1252"))
    rows = read_code_list(str(p)).rows
    assert rows[2].description == "Kronekant højre"


def test_duplicates_warned():
    cl = parse_text("Kode;Beskrivelse\nB;Bund\nb;Bund igen\n")
    assert len(cl.rows) == 1 and cl.warnings


def test_build_table_aliases_attributes_and_roundtrip(tmp_path):
    mapped = map_codes(parse_text(ENGLISH))
    t = build_table("Test list", mapped)
    tob = next(e for e in t.entries if e.code == "TOBL")
    assert tob.point_type == "bank_top"
    # TOBL/TOBR have no plain TOB in the list → separate codes, both classify
    assert t.classify("TOBR")[0] == "bank_top" and t.classify("fence")[0] == "other"
    mapped2 = map_codes(parse_text(
        "code;description\nKK;Kronekant\nKKV;Kronekant venstre\nKKH;Kronekant højre\n"))
    t2 = build_table("Med aliasser", mapped2)
    assert [e.code for e in t2.entries] == ["KK"] and t2.entries[0].aliases == ["KKV", "KKH"]
    # attributes from the standard table follow the point type (Profil on section codes)
    assert ("Profil", "Integer") in t2.entry_attributes(t2.entries[0])
    p = tmp_path / ("%s.yaml" % slug("Aabenraa Kommune 2026"))
    codes.save_table(t2, str(p))
    assert p.name == "aabenraa_kommune_2026.yaml"
    again = codes.load_table(str(p))
    assert again.to_dict() == t2.to_dict()
    assert "Profil,Integer" in codes.emlid_library_csv(again)


def test_user_choice_overrides_suggestion():
    mapped = map_codes(parse_text("Kode;Beskrivelse\nQ1;Særligt punkt\n"))
    mapped[0].point_type = "weir_crest"
    t = build_table("x", mapped)
    assert t.classify("Q1")[0] == "weir_crest"


def test_unknown_codes_from_survey_and_extend(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("Name,Code,Easting,Northing,Elevation,Description\n1,KK,541200,6103400,13,\n"
                 "2,VSP,541201,6103401,12,vandspejl\n3,VSP,541202,6103402,12,\n4,ZZ,541203,6103403,12,\n",
                 encoding="utf-8")
    table = codes.standard_table()
    s = read_survey(str(p), code_table=table)
    unk = unknown_codes(s, table)
    assert [r.code for r in unk.rows] == ["VSP", "ZZ"] and unk.rows[0].description == "vandspejl"
    mapped = map_codes(unk)
    assert mapped[0].point_type == "water_level"
    t2 = extend_table(table, mapped)
    assert t2.classify("VSP")[0] == "water_level" and t2.classify("KK")[0] == "bank_top"
    assert len(t2.entries) == len(table.entries) + 2
    assert ("Profil", "Integer") in t2.entry_attributes(next(e for e in t2.entries if e.code == "VSP"))


def test_excel_without_openpyxl_is_explained(tmp_path):
    p = tmp_path / "l.xlsx"
    p.write_bytes(b"PK\x03\x04")
    try:
        import openpyxl  # noqa: F401
        pytest.skip("openpyxl installed")
    except ImportError:
        with pytest.raises(ValueError, match="CSV"):
            read_code_list(str(p))


# --- dialog (QGIS) ----------------------------------------------------------------------

from conftest import needs_qgis  # noqa: E402


@needs_qgis
def test_codemap_dialog_review_and_save(qapp, tmp_path, monkeypatch):
    from geodrafter_stream_survey.gui import codemap_dialog as cd
    monkeypatch.setattr(cd, "user_table_dir", lambda: str(tmp_path))
    dlg = cd.CodeMapDialog()
    dlg.set_list(parse_text(DANISH, "Aabenraa koder.csv"))
    assert dlg.table.rowCount() == 15 and dlg.name_edit.text() == "Aabenraa koder"
    assert "15 codes" in dlg.summary.text()
    dlg.only_unsure.setChecked(True)
    hidden = sum(dlg.table.isRowHidden(r) for r in range(15))
    assert hidden == sum(1 for m in dlg.mapped if m.suggestion.confidence == "sure") and hidden < 15
    # the user corrects HEG (unknown) to "other" explicitly and KN to weir crest
    r = [m.row.code for m in dlg.mapped].index("KN")
    combo = dlg.table.cellWidget(r, dlg.TYPE_COL)
    combo.setCurrentIndex(combo.findData("weir_crest"))
    assert dlg.mapped[r].point_type == "weir_crest"
    dlg.save()
    assert dlg.saved_path == str(tmp_path / "aabenraa_koder.yaml")
    t = codes.load_table(dlg.saved_path)
    assert t.name == "Aabenraa koder" and t.classify(
        "KN")[0] == "weir_crest" and t.classify("KV")[0] == "bank_top"
    assert cd.saved_tables() == [("Aabenraa koder", dlg.saved_path)]


@needs_qgis
def test_unknown_codes_extend_mode(qapp, tmp_path, monkeypatch):
    from geodrafter_stream_survey.gui import codemap_dialog as cd
    monkeypatch.setattr(cd, "user_table_dir", lambda: str(tmp_path))
    base = codes.standard_table()
    rows = parse_text("Kode;Beskrivelse\nVSP;Vandspejl\n")
    dlg = cd.CodeMapDialog(mapped=map_codes(rows), name="GeoDrafter standard (+)",
                           base_table=base, extend=True)
    dlg.save()
    t = codes.load_table(dlg.saved_path)
    assert t.name == "GeoDrafter standard (+)" and t.classify("VSP")[0] == "water_level"
    assert t.classify("KK")[0] == "bank_top"
