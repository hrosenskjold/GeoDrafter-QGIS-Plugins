"""Tests for GeoDrafter Coordinate Finder and Converter."""

import os

import pytest

from conftest import ROOT, needs_qgis

from geodrafter_coordinate_finder import coordfmt as c

PLUGIN_DIR = os.path.join(ROOT, "plugins", "geodrafter_coordinate_finder")

# Reference values from pyproj (EPSG:326xx/327xx), 2026-10-17
UTM_REF = [
    # lat, lon, zone, easting, northing
    (55.6761, 12.5683, 33, 347090.938, 6172711.786),
    (56.95, 8.7, 32, 481751.237, 6311860.222),
    (-33.8568, 151.2153, 56, 334900.570, 6252288.753),
    (78.2232, 15.6267, 33, 514278.715, 8683355.469),   # Svalbard exception
    (60.0, 5.0, 32, 276979.926, 6658157.202),          # Norway exception (32V)
    (-79.9, -170.0, 2, 519576.611, 1129407.483),
]


@pytest.mark.parametrize("lat,lon,zone,e,n", UTM_REF)
def test_utm_matches_pyproj(lat, lon, zone, e, n):
    u = c.to_utm(lat, lon)
    assert u["zone"] == zone
    assert abs(u["easting"] - e) < 0.002 and abs(u["northing"] - n) < 0.002


def test_formats():
    assert c.to_dms(55.6761, True) == "55°40′33.96″N"
    assert c.to_dms(-0.0001, False) == "0°00′00.36″W"
    assert c.to_dms(9.99999999, False) == "10°00′00.00″E"      # rounding carries
    assert c.to_ddm(55.5, True) == "55°30.0000′N"
    assert c.fmt_dd(55.6761, 372.5683) == "55.676100, 12.568300"
    assert c.fmt_utm(c.to_utm(56.95, 8.7)) == "32V 481751 E 6311860 N"
    assert c.to_mgrs(56.95, 8.7) == "32V MJ 81751 11860"
    assert c.to_mgrs(55.6761, 12.5683) == "33U UB 47090 72711"   # truncated, not rounded
    assert c.to_mgrs(56.95, 8.7, digits=2) == "32V MJ 81 11"
    assert c.to_utm(85, 10) is None and c.to_mgrs(-81, 0) is None
    assert c.lat_band(84) == "X" and c.lat_band(-80) == "C" and c.lat_band(0) == "N"
    keys = [k for k, _l, _t in c.format_all(1, 2)]
    assert keys == ["dd", "dms", "ddm", "utm", "mgrs"]


# -- Go to: typed coordinates ---------------------------------------------------

def test_parse_round_trips_every_dock_format():
    """Whatever the dock shows can be pasted back into Go to."""
    import random
    from geodrafter_coordinate_finder import coordparse as p

    rnd = random.Random(7)
    for _ in range(2000):
        lat, lon = rnd.uniform(-79.9, 83.9), rnd.uniform(-179.99, 179.99)
        dd = p.parse(c.fmt_dd(lat, lon))
        assert dd["kind"] == "xy" and abs(dd["a"] - lat) < 1e-6 and abs(dd["b"] - lon) < 1e-6
        for fmt in (c.fmt_dms, c.fmt_ddm):
            r = p.parse(fmt(lat, lon))
            assert abs(r["lat"] - lat) < 1e-5 and abs(r["lon"] - lon) < 1e-5
        u = c.to_utm(lat, lon)
        for text, tol in ((c.fmt_utm(u), 0.5), (c.to_mgrs(lat, lon), 1.0), (c.to_mgrs(lat, lon, 2), 501)):
            r = p.parse(text)
            assert r["kind"] == "utm" and r["zone"] == u["zone"] and r["north"] == (lat >= 0), text
            assert abs(r["easting"] - u["easting"]) < tol and abs(r["northing"] - u["northing"]) < tol, text


@pytest.mark.parametrize("text,lat,lon", [
    ("57°02′53.40″N 9°55′06.12″E", 57.048167, 9.918367),
    ("57°02'53.4\"N, 9°55'06.12\"E", 57.048167, 9.918367),
    ("N 57 02.890 E 9 55.102", 57.048167, 9.918367),
    ("57.0488N 9.9217Ø", 57.0488, 9.9217),          # Danish Ø for east
    ("9.9217E 57.0488N", 57.0488, 9.9217),          # order follows the letters
    ("S33 51.408 E151 12.918", -33.8568, 151.2153),
    ("-33.8568°, 151.2153°", -33.8568, 151.2153),
    ("57 02 53.4 9 55 6.12", 57.048167, 9.918367),
])
def test_parse_angles(text, lat, lon):
    from geodrafter_coordinate_finder import coordparse as p
    r = p.parse(text)
    assert r["kind"] == "wgs84" and abs(r["lat"] - lat) < 1e-5 and abs(r["lon"] - lon) < 1e-5


def test_parse_numbers_utm_mgrs_and_errors():
    from geodrafter_coordinate_finder import coordparse as p
    assert p.parse("57,0488 9,9217") == {"kind": "xy", "a": 57.0488, "b": 9.9217}
    assert p.parse("552000,6320000") == {"kind": "xy", "a": 552000.0, "b": 6320000.0}
    assert p.parse("552000.5; 6320000") == {"kind": "xy", "a": 552000.5, "b": 6320000.0}
    utm = {"kind": "utm", "zone": 32, "north": True, "easting": 552000.0, "northing": 6320000.0}
    assert p.parse("32V 552000 6320000") == utm
    assert p.parse("32v 552000 E 6320000 N") == utm
    assert p.parse("32VNJ5200020000") == utm
    assert p.parse("32V NJ 52 20")["easting"] == 552500     # centre of the 1 km square
    assert p.parse("56H LH 34900 52288")["north"] is False   # Sydney
    for bad in ("", "abc", "57N 9N", "32V NJ 520 20", "1 2 3", "95N 10E", "61V 1 2"):
        with pytest.raises(ValueError):
            p.parse(bad)


def test_metadata_is_own_work():
    from geodrafter_common.metadata import check_metadata, read_metadata
    meta = read_metadata(PLUGIN_DIR)
    assert check_metadata(meta) == []
    assert meta["name"] == "GeoDrafter Coordinate Finder and Converter"
    assert meta["homepage"] == "https://geodrafter.com/qgis/coordinate-finder-and-converter/"
    for name in os.listdir(PLUGIN_DIR):
        if name.endswith((".py", ".txt", ".md")) and name != "TESTING.md":
            text = open(os.path.join(PLUGIN_DIR, name), encoding="utf-8").read()
            assert "Natsis" not in text and "Coordinate Capture" not in text, name


@needs_qgis
def test_readout_rows(qapp):
    from qgis.core import QgsCoordinateReferenceSystem as Crs, QgsPointXY
    from geodrafter_coordinate_finder.readout import Readout

    r = Readout(Crs("EPSG:25832"), Crs("EPSG:3857"))
    rows = {k: t for k, _l, t in r.rows(QgsPointXY(481751.237, 6311860.222))}
    assert rows["map"] == "481751.237, 6311860.222  (EPSG:25832)"
    assert rows["chosen"].endswith("(EPSG:3857)")
    assert rows["dd"] == "56.950000, 8.700000"
    assert rows["utm"] == "32V 481751 E 6311860 N"
    assert rows["mgrs"] == "32V MJ 81751 11860"
    assert [k for k, _l in r.keys_and_labels()] == ["map", "chosen", "dd", "dms", "ddm", "utm", "mgrs"]


@needs_qgis
def test_locate(qapp):
    from qgis.core import QgsCoordinateReferenceSystem as Crs
    from geodrafter_coordinate_finder.readout import locate

    m = Crs("EPSG:25832")
    pt, how = locate("32V MJ 81751 11860", Crs("EPSG:4326"), m)
    assert abs(pt.x() - 481751.5) < 1 and abs(pt.y() - 6311860.5) < 1 and "EPSG:32632" in how
    pt, _ = locate("56.95, 8.7", Crs("EPSG:4326"), m)
    assert abs(pt.x() - 481751.237) < 0.01 and abs(pt.y() - 6311860.222) < 0.01
    pt, how = locate("481751.237 6311860.222", Crs("EPSG:25832"), m)
    assert abs(pt.x() - 481751.237) < 1e-6 and how == "EPSG:25832"
    pt, how = locate("56.95, 8.7", Crs("EPSG:25832"), m)
    assert abs(pt.x() - 481751.237) < 0.01 and "WGS84" in how
    with pytest.raises(ValueError):
        locate("95, 10", Crs("EPSG:4326"), m)


@needs_qgis
def test_panel_copy(qapp):
    from qgis.PyQt.QtGui import QGuiApplication
    from geodrafter_coordinate_finder.panel import CoordinatesPanel

    p = CoordinatesPanel([("map", "Map CRS"), ("mgrs", "MGRS")])
    p.show_rows([("map", "Map CRS", "1, 2  (EPSG:25832)"), ("mgrs", "MGRS", "32V MJ 81751 11860")])
    assert p.copy_key("mgrs") == "32V MJ 81751 11860"
    assert QGuiApplication.clipboard().text() == "32V MJ 81751 11860"
    p.table.setCurrentCell(0, 1)
    assert p.copy_selected() == "1, 2  (EPSG:25832)"
    assert p.copy_all() == "Map CRS: 1, 2  (EPSG:25832)\nMGRS: 32V MJ 81751 11860"
    got = []
    p.go_requested.connect(got.append)
    p.go_field.setText("57, 10")
    p.go_field.returnPressed.emit()
    assert got == ["57, 10"]


@needs_qgis
def test_plugin_flow(qapp):
    from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY, QgsRectangle, QgsSettings
    from qgis.gui import QgsMapCanvas
    from qgis.PyQt.QtGui import QGuiApplication
    from qgis_fakes import fake_iface
    import geodrafter_coordinate_finder as pkg

    QgsSettings().setValue("geodrafter/coordinate_finder/chosen_crs", "EPSG:4326")
    QgsSettings().setValue("geodrafter/coordinate_finder/copy_on_pick", "dd")
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    canvas.resize(400, 300)
    canvas.setExtent(QgsRectangle(400000, 6000000, 800000, 6300000))
    iface = fake_iface(canvas, None)
    plugin = pkg.classFactory(iface)
    plugin.initGui()
    assert plugin.panel_action in iface.pluginToolBar().actions()
    assert len(iface.menu) == 2                       # Coordinate Finder + About
    plugin.panel_action.trigger()                     # opens the panel
    assert plugin.panel is not None and plugin.panel_action.isChecked()

    plugin.panel.pick_button.setChecked(True)
    assert canvas.mapTool() is plugin.tool
    plugin.tool.picked.emit(QgsPointXY(481751.237, 6311860.222))
    assert plugin.panel.value("chosen") == "56.950000, 8.700000  (EPSG:4326)"
    assert QGuiApplication.clipboard().text() == "56.950000, 8.700000"   # copy on pick
    assert plugin.marker.is_shown()

    plugin.panel.crs_picker.setCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    assert plugin.panel.value("chosen").startswith("481751.237, 6311860.222")
    assert QgsSettings().value("geodrafter/coordinate_finder/chosen_crs") == "EPSG:25832"

    plugin.panel.follow_button.setChecked(True)
    plugin.tool.hovered.emit(QgsPointXY(500000, 6200000))
    assert plugin.panel.value("map").startswith("500000.000, 6200000.000")
    canvas.unsetMapTool(plugin.tool)                  # e.g. right click / Esc / another tool
    assert not plugin.panel.pick_button.isChecked() and not plugin.panel.follow_button.isChecked()

    plugin.panel.crs_picker.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    plugin.panel.go_field.setText("56.95, 8.7")
    plugin.panel.go_field.returnPressed.emit()
    c = canvas.center()
    assert abs(c.x() - 481751.237) < 0.5 and abs(c.y() - 6311860.222) < 0.5
    assert plugin.panel.value("mgrs") == "32V MJ 81751 11860"
    assert plugin.go_to("nonsense") is None
    assert abs(canvas.center().x() - 481751.237) < 0.5

    QgsSettings().setValue("geodrafter/coordinate_finder/copy_on_pick", "")
    plugin.unload()
    assert iface.menu == [] and plugin.panel is None
    assert iface.pluginToolBar().actions() == []
