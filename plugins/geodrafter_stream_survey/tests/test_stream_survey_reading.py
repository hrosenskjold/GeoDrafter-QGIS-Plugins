# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Block 6: reading survey files and code tables (pure Python, no QGIS)."""

import csv
import io
import os
import zipfile

import pytest

from geodrafter_stream_survey.core import codes
from geodrafter_stream_survey.core.model import POINT_TYPES
from geodrafter_stream_survey.core.readers import (
    check_crs, read_delimited, read_dxf, read_emlid_csv, read_field_text, read_shapefile, read_survey)
from geodrafter_stream_survey.core.readers.common import parse_float
from geodrafter_stream_survey.core.readers.shapefile import write_point_shapefile

HERE = os.path.dirname(os.path.abspath(__file__))
EMLID = os.path.join(HERE, "data", "emlid_flow_SYNTHETIC.csv")
NAMES = ["P01-%02d" % i for i in range(1, 10)] + ["P02-%02d" % i for i in range(2, 10)] + ["RB1", "DR1"]


@pytest.fixture(scope="module")
def table():
    return codes.standard_table()


def _rewrite(tmp_path, name, sep, drop=(), rename=None, decimal_comma=False):
    with open(EMLID, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    keep = [i for i, h in enumerate(rows[0]) if h not in drop]
    out = []
    for n, r in enumerate(rows):
        r = [r[i] for i in keep]
        if n == 0 and rename:
            r = [rename.get(h, h) for h in r]
        if n and decimal_comma:
            r = [c.replace(".", ",") if parse_float(c) is not None and ":" not in c else c for c in r]
        out.append(r)
    p = tmp_path / name
    with open(p, "w", newline="", encoding="utf-8") as f:
        csv.writer(f, delimiter=sep, lineterminator="\n").writerows(out)
    return str(p)


# --- Emlid Flow CSV -------------------------------------------------------------

def test_emlid_csv_all_columns(table):
    s = read_survey(EMLID, code_table=table)
    assert s.reader == "emlid_csv"
    assert [p.name for p in s] == NAMES                       # survey order kept
    assert [p.seq for p in s] == list(range(len(NAMES)))
    p = s.points[0]
    assert (p.code, p.point_type, p.code_known) == ("T", "terrain", True)
    assert p.x == pytest.approx(541203.0) and p.y == pytest.approx(6103405.196)
    assert p.z == pytest.approx(13.75)
    assert p.solution_status == "FIX" and p.is_fix
    assert (p.rms_e, p.rms_n, p.rms_z, p.rms_lateral) == (0.008, 0.009, 0.014, 0.012)
    assert p.antenna_height == 1.8 and p.antenna_height_raw == "1.800 m"
    assert p.time_start == "2026-05-12 09:12:00.0 UTC+02:00" and p.time_end.endswith("09:12:05.0 UTC+02:00")
    assert p.samples == 5 and p.pdop == 1.3
    assert p.lon == pytest.approx(9.6453, abs=1e-3) and p.ellipsoidal_height == pytest.approx(52.35)
    assert p.extra["Mount point"] == "GPSNet_RTCM32" and p.extra["Correction type"] == "NTRIP"
    dr = s.points[-1]
    assert dr.point_type == "drain_outlet" and dr.solution_status == "FLOAT" and dr.rms_z == 0.187
    assert dr.description == "Drænudløb Ø110"
    assert {p.point_type for p in s} <= set(POINT_TYPES)
    assert s.warnings == []                                   # CS name is ETRS89 / UTM 32N + DVR90


@pytest.mark.parametrize("sep", ["\t", ";", "|"])
def test_emlid_csv_other_separators(tmp_path, table, sep):
    path = _rewrite(tmp_path, "tab.txt", sep)
    s = read_survey(path, code_table=table)
    assert [p.name for p in s] == NAMES
    assert s.points[3].point_type == "bed" and s.points[3].z == pytest.approx(12.52)


def test_custom_csv_reordered_missing_and_decimal_comma(tmp_path, table):
    # Custom CSV: fewer columns, other order, decimal comma with ';'
    with open(EMLID, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    order = ["Elevation", "Northing", "Code", "Name", "Easting", "Solution status"]
    idx = [rows[0].index(h) for h in order]
    p = tmp_path / "custom.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(order)
        for r in rows[1:]:
            w.writerow([r[i].replace(".", ",") if i != idx[3] else r[i] for i in idx])
    s = read_survey(str(p), code_table=table)
    assert [q.name for q in s] == NAMES
    assert s.points[1].x == pytest.approx(541201.2) and s.points[1].z == pytest.approx(13.5)
    assert s.points[1].point_type == "bank_top"
    assert s.points[0].rms_z is None


def test_emlid_headerless_penzd_and_pnezd(tmp_path):
    lines_penzd = "1,541203.000,6103405.196,13.750,T\n2,541201.200,6103402.078,13.500,KK\n"
    lines_pnezd = "1,6103405.196,541203.000,13.750,T\n2,6103402.078,541201.200,13.500,KK\n"
    for txt in (lines_penzd, lines_pnezd):
        p = tmp_path / "p.csv"
        p.write_text(txt, encoding="utf-8")
        s = read_emlid_csv(str(p))
        assert s.points[0].x == pytest.approx(541203.0) and s.points[0].y == pytest.approx(6103405.196)
        assert s.points[1].description == "KK" and s.points[1].name == "2"


def test_emlid_wrong_cs_name_warns(tmp_path):
    path = _rewrite(tmp_path, "wgs.csv", ",")
    txt = open(path, encoding="utf-8").read().replace("ETRS89 / UTM zone 32N + DVR90 height", "WGS 84")
    open(path, "w", encoding="utf-8").write(txt)
    s = read_survey(path)
    assert any("WGS 84" in w and "25832" in w for w in s.warnings)
    txt = txt.replace("WGS 84", "ETRS89 / UTM zone 32N")
    open(path, "w", encoding="utf-8").write(txt)
    s = read_survey(path)
    assert any("DVR90" in w for w in s.warnings)


def test_no_cs_name_plausibility(tmp_path):
    path = _rewrite(tmp_path, "nocs.csv", ",", drop=("CS name",))
    assert read_survey(path).warnings == []
    p = tmp_path / "geo.csv"
    p.write_text("Name,Easting,Northing,Elevation\n1,9.64,55.07,13.7\n", encoding="utf-8")
    assert any("outside Denmark" in w for w in read_survey(str(p)).warnings)


def test_unknown_codes_reported(tmp_path, table):
    p = tmp_path / "u.csv"
    p.write_text("Name,Code,Easting,Northing,Elevation\n1,KK1,541200,6103400,13\n2,ZZ,541201,6103401,12\n"
                 "3,,541202,6103402,12\n", encoding="utf-8")
    s = read_survey(str(p), code_table=table)
    assert [q.point_type for q in s] == ["bank_top", "other", "other"]
    assert [q.code_known for q in s] == [True, False, False]
    assert any("ZZ" in w for w in s.warnings)


def test_cp1252_and_bom(tmp_path, table):
    p = tmp_path / "w.csv"
    p.write_bytes("Name,Code,Easting,Northing,Elevation,Description\n1,DR,541200,6103400,13,Drænrør\n"
                  .encode("cp1252"))
    assert read_survey(str(p), code_table=table).points[0].description == "Drænrør"
    p.write_bytes(b"\xef\xbb\xbf" + "Name,Easting,Northing\nA,541200,6103400\n".encode())
    assert read_survey(str(p)).points[0].name == "A"


def test_antenna_feet():
    s = read_emlid_csv("x.csv", text="Name,Easting,Northing,Antenna height,Antenna height units\n"
                                     "1,541200,6103400,6.0,ft\n")
    assert s.points[0].antenna_height == pytest.approx(1.8288)


# --- generic CSV and field text -----------------------------------------------------

def test_generic_csv_chosen_columns(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("pkt;Ø;N;H;k\nA1;541200,10;6103400,20;13,05;B\n", encoding="utf-8")
    s = read_delimited(str(p), columns={"name": "pkt", "x": "Ø", "y": "N", "z": "H", "code": "k"})
    q = s.points[0]
    assert (q.name, q.x, q.y, q.z, q.code) == ("A1", 541200.1, 6103400.2, 13.05, "B")
    with pytest.raises(ValueError):
        read_delimited(str(p), columns={"x": "nope"})


def test_field_text_configurable_layout(tmp_path, table):
    p = tmp_path / "felt.txt"
    p.write_text("# synthetic field file\n"
                 "101  541200.000  6103400.000  13.051  KK   left bank\n"
                 "102  541201.000  6103399.000  12.420  B\n"
                 "\n* comment\n"
                 "bad line\n", encoding="utf-8")
    s = read_survey(str(p), code_table=table, layout=["name", "x", "y", "z", "code"])
    assert s.reader == "field_text"
    assert [q.name for q in s] == ["101", "102"]
    assert s.points[0].extra == {"col6": "left", "col7": "bank"}
    assert [q.point_type for q in s] == ["bank_top", "bed"]
    assert any("skipped" in w for w in s.warnings)
    # separator and skipped column
    p.write_text("101;X;541200,5;6103400,5;13,1;VS\n", encoding="utf-8")
    s = read_field_text(str(p), ["name", None, "x", "y", "z", "code"], separator=";")
    assert (s.points[0].x, s.points[0].code) == (541200.5, "VS")


# --- shapefile ---------------------------------------------------------------------

def _shape_points():
    s = read_emlid_csv(EMLID)
    return [(p.x, p.y, p.z, {"Name": p.name, "Code": p.code, "Descriptio": p.description,
                             "Solution s": p.solution_status, "Elevation": "%.3f" % p.z}) for p in s]


PRJ = ('PROJCS["ETRS_1989_UTM_Zone_32N",GEOGCS["GCS_ETRS_1989",DATUM["D_ETRS_1989",'
       'SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],'
       'UNIT["Degree",0.0174532925199433]],'
       'PROJECTION["Transverse_Mercator"],UNIT["Meter",1.0]]')


def test_shapefile_points(tmp_path, table):
    fields = ["Name", "Code", "Descriptio", "Solution s", "Elevation"]
    shp, shx, dbf = write_point_shapefile(_shape_points(), fields)
    for ext, data in ((".shp", shp), (".shx", shx), (".dbf", dbf), (".prj", PRJ.encode())):
        (tmp_path / ("points" + ext)).write_bytes(data)
    s = read_survey(str(tmp_path / "points.shp"), code_table=table)
    assert s.reader == "shapefile"
    assert [p.name for p in s] == NAMES
    assert s.points[-1].description == "Drænudløb Ø110"
    assert s.points[-1].solution_status == "FLOAT"
    assert s.points[1].point_type == "bank_top" and s.points[1].z == pytest.approx(13.5)
    assert s.points[0].cs_name == "ETRS 1989 UTM Zone 32N"
    assert any("DVR90" in w for w in s.warnings)        # prj has no vertical datum


def test_shapefile_zip_skips_lines(tmp_path):
    shp, shx, dbf = write_point_shapefile(_shape_points()[:3], ["Name", "Code"], z=True)
    line = bytearray(write_point_shapefile([(0, 0, 0, {})], ["Name"])[0])
    line[32:36] = (3).to_bytes(4, "little")                # declare as polyline shapefile
    zp = tmp_path / "export.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("Project/Lines.shp", bytes(line))
        z.writestr("Project/Points.shp", shp)
        z.writestr("Project/Points.dbf", dbf)
    s = read_shapefile(str(zp))
    assert [p.name for p in s] == NAMES[:3] and s.points[2].z == pytest.approx(12.82)


# --- DXF ---------------------------------------------------------------------------

def _dxf(entities):
    out = io.StringIO()
    out.write("0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n")
    for e in entities:
        out.write(e)
    out.write("0\nENDSEC\n0\nEOF\n")
    return out.getvalue()


def _point(x, y, z, layer):
    return "0\nPOINT\n8\n%s\n10\n%.3f\n20\n%.3f\n30\n%.3f\n" % (layer, x, y, z)


def _text(x, y, t, layer, kind="TEXT"):
    return "0\n%s\n8\n%s\n10\n%.3f\n20\n%.3f\n30\n0.0\n40\n0.2\n1\n%s\n" % (kind, layer, x, y, t)


def test_dxf_per_code_layers(tmp_path, table):
    pts = read_emlid_csv(EMLID).points
    ents = []
    for p in pts:
        ents.append(_point(p.x, p.y, p.z, "%s_points" % p.code))
        ents.append(_text(p.x + 0.3, p.y + 0.3, p.name, "%s_names" % p.code))
    f = tmp_path / "e.dxf"
    f.write_text(_dxf(ents), encoding="utf-8")
    s = read_survey(str(f), code_table=table)
    assert s.reader == "dxf"
    assert [p.name for p in s] == NAMES
    assert [p.code for p in s] == [p.code for p in pts]
    assert s.points[4].z == pytest.approx(pts[4].z) and s.points[4].point_type == "bed"


def test_dxf_generic_layer_with_labels(tmp_path, table):
    ents = [_point(541200, 6103400, 13.05, "Points"),
            _text(541200.2, 6103400.2, "P1", "Labels"),
            _text(541200.2, 6103399.9, "KK", "Labels"),
            _text(541200.2, 6103399.6, "13.05", "Labels"),
            _text(541200.2, 6103399.3, "{\\fArial;left}\\Pbank", "Labels", kind="MTEXT"),
            _point(541210, 6103400, 12.40, "Points"),
            _text(541210.2, 6103400.2, "P2", "Labels"),
            _text(541210.2, 6103399.9, "B", "Labels")]
    s = read_dxf("x.dxf", code_table=table, text=_dxf(ents))
    a, b = s.points
    assert (a.name, a.code, a.description) == ("P1", "KK", "left bank")
    assert (b.name, b.code) == ("P2", "B")


def test_dxf_insert_with_attribs():
    ent = ("0\nINSERT\n8\nSurvey\n2\nPT\n10\n541200.0\n20\n6103400.0\n30\n0.0\n66\n1\n"
           "0\nATTRIB\n8\nSurvey\n10\n0\n20\n0\n1\nP7\n2\nNAME\n"
           "0\nATTRIB\n8\nSurvey\n10\n0\n20\n0\n1\nVS\n2\nCODE\n"
           "0\nATTRIB\n8\nSurvey\n10\n0\n20\n0\n1\n12.91\n2\nELEVATION\n0\nSEQEND\n")
    s = read_dxf("x.dxf", text=_dxf([ent]))
    p = s.points[0]
    assert (p.name, p.code, p.z, p.x) == ("P7", "VS", 12.91, 541200.0)


def test_dxf_without_points_warns():
    s = read_dxf("x.dxf", text=_dxf([_text(1, 2, "only text", "0")]))
    assert not s.points and s.warnings


# --- code tables -------------------------------------------------------------------

def test_standard_table_covers_all_types(table):
    assert {e.point_type for e in table.entries} == set(POINT_TYPES)
    assert table.classify("kk")[0] == "bank_top"           # not case sensitive
    assert table.classify("KK-3")[0] == "bank_top"         # prefix match, rest not a letter
    assert table.classify("BRO")[0] == "bridge_deck"       # not B + "RO"
    assert table.classify("BX") == ("other", False)
    assert table.classify("", "VS ved bro")[0] == "water_level"


def test_table_validation_and_roundtrip(tmp_path, table):
    with pytest.raises(codes.CodeTableError):
        codes.table_from_dict({"codes": [{"code": "A", "type": "riverbed"}]})
    with pytest.raises(codes.CodeTableError):
        codes.table_from_dict({"codes": [{"code": "A", "type": "bed"}, {"code": "a", "type": "bank_top"}]})
    p = tmp_path / "kommune.yaml"
    codes.save_table(table, str(p))
    again = codes.load_table(str(p))
    assert again.to_dict() == table.to_dict()
    custom = codes.table_from_dict({"name": "Kommune X", "case_sensitive": True, "prefix_match": False,
                                    "codes": [{"code": "kr", "type": "bank_top", "aliases": "KR1, KR2"}]})
    assert custom.classify("KR1")[0] == "bank_top" and custom.classify("KR")[1] is False


def test_emlid_code_library_in_sync(table):
    with open(codes.EMLID_LIBRARY, encoding="utf-8") as f:
        shipped = f.read()
    assert shipped == codes.emlid_library_csv(table)      # regenerate after editing standard.yaml
    rows = list(csv.DictReader(io.StringIO(shipped)))
    assert list(rows[0])[:4] == ["Code", "Description", "Type", "Color"]
    assert len({r["Code"] for r in rows}) == len(rows)    # Emlid refuses duplicate codes
    assert all(r["Type"] == "Point" and r["Color"].startswith("#") for r in rows)


def test_core_has_no_qgis_import():
    root = os.path.join(os.path.dirname(HERE), "core")
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.endswith(".py"):
                src = open(os.path.join(dirpath, fn), encoding="utf-8").read()
                assert "import qgis" not in src and "from qgis" not in src, fn


def test_check_crs_returns_list(table):
    s = read_emlid_csv(EMLID)
    assert check_crs(s) == []


def test_english_table_and_emlid_library():
    en = codes.standard_table_en()
    da = codes.standard_table()
    assert sorted({e.point_type for e in en.entries}) == sorted({e.point_type for e in da.entries})
    assert en.classify("TOBL")[0] == "bank_top" and en.classify("BED-12")[0] == "bed"
    with open(codes.EMLID_LIBRARY_EN, encoding="utf-8") as f:
        shipped = f.read()
    assert shipped == codes.emlid_library_csv(en)         # regenerate after editing standard_en.yaml
    rows = list(csv.DictReader(io.StringIO(shipped)))
    assert len({r["Code"] for r in rows}) == len(rows)
