"""Tests for GeoDrafter Coordinate Capture."""

import os

import pytest

from conftest import ROOT, needs_qgis

from geodrafter_coordinate_capture import coordfmt as c

PLUGIN_DIR = os.path.join(ROOT, "plugins", "geodrafter_coordinate_capture")

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


def test_metadata_credits_original_author():
    from geodrafter_common.metadata import check_metadata, read_metadata
    meta = read_metadata(PLUGIN_DIR)
    assert check_metadata(meta) == []
    assert "Stefanos Natsis" in meta["about"]
    assert "uclaros/qgis_coordinate_capture" in meta["about"]
    for name in ("capture.py", "plugin.py", "README.md"):
        assert "Stefanos Natsis" in open(os.path.join(PLUGIN_DIR, name), encoding="utf-8").read()


@needs_qgis
def test_computer_and_dock(qapp):
    from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY
    from geodrafter_coordinate_capture.capture import CaptureDock, CoordinateComputer

    comp = CoordinateComputer()
    comp.map_crs = QgsCoordinateReferenceSystem("EPSG:25832")
    comp.user_crs = QgsCoordinateReferenceSystem("EPSG:3857")
    out = comp.compute(QgsPointXY(481751.237, 6311860.222))
    assert out["map"] == "481751.237, 6311860.222  (EPSG:25832)"
    assert out["user"].endswith("(EPSG:3857)")
    assert out["dd"] == "56.950000, 8.700000"
    assert out["mgrs"] == "32V MJ 81751 11860"

    dock = CaptureDock()
    dock.set_values(out)
    assert dock.text_of("utm") == "32V 481751 E 6311860 N"
    assert dock.copy("mgrs") == "32V MJ 81751 11860"
    from qgis.PyQt.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == "32V MJ 81751 11860"
    assert "MGRS: 32V MJ 81751 11860" in dock.copy_all()


@needs_qgis
def test_plugin_flow(qapp):
    from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY, QgsSettings
    from qgis.gui import QgsMapCanvas
    from qgis_fakes import fake_iface
    import geodrafter_coordinate_capture as pkg

    QgsSettings().setValue("geodrafter/coordinate_capture/crs", "EPSG:4326")
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    iface = fake_iface(canvas, None)
    plugin = pkg.classFactory(iface)
    plugin.initGui()
    plugin.action.trigger()                       # opens the dock
    assert plugin.dock is not None
    plugin.dock.capture_button.setChecked(True)   # starts the map tool
    assert canvas.mapTool() is plugin.tool
    idx = plugin.dock.copy_on_click.findData("dd")
    plugin.dock.copy_on_click.setCurrentIndex(idx)
    plugin.on_click(QgsPointXY(481751.237, 6311860.222))
    assert plugin.dock.text_of("user") == "56.950000, 8.700000  (EPSG:4326)"
    from qgis.PyQt.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == "56.950000, 8.700000"
    plugin.dock.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    assert plugin.dock.text_of("user").startswith("481751.237, 6311860.222")
    assert QgsSettings().value("geodrafter/coordinate_capture/crs") == "EPSG:25832"
    plugin.dock.capture_button.setChecked(False)
    assert canvas.mapTool() is None
    plugin.unload()
    assert iface.menu == [] and plugin.dock is None


# -- Go to: typed coordinates ---------------------------------------------------

def test_parse_round_trips_every_dock_format():
    """Whatever the dock shows can be pasted back into Go to."""
    import random
    from geodrafter_coordinate_capture import coordparse as p

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
    from geodrafter_coordinate_capture import coordparse as p
    r = p.parse(text)
    assert r["kind"] == "wgs84" and abs(r["lat"] - lat) < 1e-5 and abs(r["lon"] - lon) < 1e-5


def test_parse_numbers_utm_mgrs_and_errors():
    from geodrafter_coordinate_capture import coordparse as p
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


@needs_qgis
def test_resolve_typed(qapp):
    from qgis.core import QgsCoordinateReferenceSystem as Crs
    from geodrafter_coordinate_capture.capture import resolve_typed

    m = Crs("EPSG:25832")
    pt, how = resolve_typed("32V MJ 81751 11860", Crs("EPSG:4326"), m)
    assert abs(pt.x() - 481751.5) < 1 and abs(pt.y() - 6311860.5) < 1 and "EPSG:32632" in how
    pt, how = resolve_typed("56.95, 8.7", Crs("EPSG:4326"), m)          # lat, lon
    assert abs(pt.x() - 481751.237) < 0.01 and abs(pt.y() - 6311860.222) < 0.01
    pt, how = resolve_typed("481751.237 6311860.222", Crs("EPSG:25832"), m)
    assert abs(pt.x() - 481751.237) < 1e-6 and how == "EPSG:25832"
    pt, how = resolve_typed("56.95, 8.7", Crs("EPSG:25832"), m)         # small numbers -> lat, lon
    assert abs(pt.x() - 481751.237) < 0.01 and "WGS84" in how
    pt, _ = resolve_typed("56°57′00″N 8°42′00″E", Crs("EPSG:3857"), m)
    assert abs(pt.x() - 481751.237) < 0.01
    with pytest.raises(ValueError):
        resolve_typed("95, 10", Crs("EPSG:4326"), m)


@needs_qgis
def test_plugin_go_to(qapp):
    from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle, QgsSettings
    from qgis.gui import QgsMapCanvas
    from qgis_fakes import fake_iface
    import geodrafter_coordinate_capture as pkg

    QgsSettings().setValue("geodrafter/coordinate_capture/crs", "EPSG:4326")
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    canvas.resize(400, 300)
    canvas.setExtent(QgsRectangle(400000, 6000000, 800000, 6300000))
    iface = fake_iface(canvas, None)
    plugin = pkg.classFactory(iface)
    plugin.initGui()
    assert plugin.action in iface.pluginToolBar().actions()      # on QGIS' Plugins toolbar
    plugin.action.trigger()
    plugin.dock.goto_edit.setText("56.95, 8.7")
    plugin.dock.goto_edit.returnPressed.emit()                    # Enter = Go
    c_ = canvas.center()
    assert abs(c_.x() - 481751.237) < 0.5 and abs(c_.y() - 6311860.222) < 0.5
    assert plugin.dock.text_of("mgrs") == "32V MJ 81751 11860"
    assert plugin.tool.marker.isVisible()
    plugin.dock.goto_edit.setText("nonsense")
    assert plugin.go_to() is None                                 # warning, no move
    assert abs(canvas.center().x() - 481751.237) < 0.5
    plugin.unload()
    assert iface.pluginToolBar().actions() == []
