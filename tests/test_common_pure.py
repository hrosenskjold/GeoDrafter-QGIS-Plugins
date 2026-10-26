import datetime
import os
import zipfile

import pytest

from geodrafter_common import links
from geodrafter_common.metadata import check_metadata, read_metadata
from tools import build_zip, check_qt_imports

GOOD_META = """[general]
name=GeoDrafter Test Tool
qgisMinimumVersion=3.40
qgisMaximumVersion=4.99
supportsQt6=True
description=Test
about=A test plugin.
version=0.2.0
author=Henrik Rosenskjold (GISkon)
email=contact@geodrafter.com
repository=https://github.com/hrosenskjold/GeoDrafter-QGIS-Plugins
tracker=https://github.com/hrosenskjold/GeoDrafter-QGIS-Plugins/issues
homepage=https://geodrafter.com/qgis/test-tool/
license=GPL-2.0-or-later
"""


def test_slug_and_homepage():
    assert links.slug_from_name("GeoDrafter Pro Trace") == "pro-trace"
    assert (links.slug_from_name("GeoDrafter Coordinate Finder and Converter")
            == "coordinate-finder-and-converter")
    assert links.plugin_homepage("measure") == "https://geodrafter.com/qgis/measure/"
    with pytest.raises(ValueError):
        links.plugin_homepage("../evil")
    with pytest.raises(ValueError):
        links.slug_from_name("GeoDrafter")


def test_publish_url_override_only_http():
    assert links.publish_url() == links.PUBLISH_URL
    assert links.publish_url(" https://staging.example.org/p ") == "https://staging.example.org/p"
    assert links.publish_url("javascript:alert(1)") == links.PUBLISH_URL
    assert links.publish_url("file:///etc/passwd") == links.PUBLISH_URL
    assert "?" not in links.PUBLISH_URL  # no tracking parameters


def test_safe_filename_unique():
    from geodrafter_common.share import default_export_dir, safe_filename
    used = set()
    assert safe_filename("Vådområder 2026", used) == "Vådområder_2026.geojson"
    assert safe_filename("Vådområder 2026", used) == "Vådområder_2026_2.geojson"
    assert safe_filename("../../x", used) == "x.geojson"
    assert safe_filename("", used) == "layer.geojson"
    d = default_export_dir("/home/u", datetime.datetime(2026, 10, 17, 9, 5, 1))
    assert d == os.path.join("/home/u", "GeoDrafter", "webkort-20261017-090501")


def _make_plugin(tmp_path, meta=GOOD_META):
    plugins = tmp_path / "plugins"
    p = plugins / "geodrafter_test"
    (p / "tests").mkdir(parents=True)
    (p / "__pycache__").mkdir()
    (p / "metadata.txt").write_text(meta, encoding="utf-8")
    (p / "__init__.py").write_text("def classFactory(iface):\n    return None\n")
    (p / "tests" / "test_x.py").write_text("")
    (p / "__pycache__" / "x.pyc").write_bytes(b"")
    return plugins


def test_metadata_check(tmp_path):
    plugins = _make_plugin(tmp_path)
    meta = read_metadata(str(plugins / "geodrafter_test"))
    assert check_metadata(meta) == []
    bad = dict(meta, name="Trace", qgisMaximumVersion="3.99", supportsQt6="False",
               homepage="https://example.com/")
    problems = " ".join(check_metadata(bad))
    for word in ("GeoDrafter", "qgisMaximumVersion", "supportsQt6", "homepage"):
        assert word in problems
    assert check_metadata(dict(meta, qgisMinimumVersion="3.34")) == []      # tested there by Henrik
    no_flag = {k: v for k, v in meta.items() if k != "supportsQt6"}         # deprecated on plugins.qgis.org
    assert check_metadata(no_flag) == []
    assert "qgisMinimumVersion" in " ".join(check_metadata(dict(meta, qgisMinimumVersion="3.28")))


def test_build_zip(tmp_path):
    plugins = _make_plugin(tmp_path)
    lic = tmp_path / "LICENSE"
    lic.write_text("GPL")
    out = build_zip.build("geodrafter_test", str(plugins),
                          os.path.join(build_zip.ROOT, "geodrafter_common"),
                          str(tmp_path / "dist"), str(lic))
    assert out.endswith("geodrafter_test-0.2.0.zip")
    names = zipfile.ZipFile(out).namelist()
    assert "geodrafter_test/metadata.txt" in names
    assert "geodrafter_test/LICENSE" in names
    assert "geodrafter_test/geodrafter_common/__init__.py" in names
    assert "geodrafter_test/geodrafter_common/about.py" in names
    assert not any("/tests/" in n or "__pycache__" in n for n in names)
    assert all(n.startswith("geodrafter_test/") for n in names)


def test_build_zip_rejects_bad_metadata(tmp_path):
    plugins = _make_plugin(tmp_path, GOOD_META.replace("qgisMaximumVersion=4.99", "qgisMaximumVersion=3.99"))
    with pytest.raises(SystemExit):
        build_zip.build("geodrafter_test", str(plugins), str(tmp_path), str(tmp_path / "d"))


def test_qt_import_check(tmp_path):
    (tmp_path / "ok.py").write_text("from qgis.PyQt.QtCore import Qt\n")
    (tmp_path / "bad.py").write_text("import os\nfrom PyQt5.QtCore import Qt\n")
    (tmp_path / "bad6.py").write_text("    import PyQt6\n")
    found = check_qt_imports.find_violations([str(tmp_path)])
    assert sorted((os.path.basename(p), line, m) for p, line, m in found) == [
        ("bad.py", 2, "PyQt5"), ("bad6.py", 1, "PyQt6")]


def test_repo_has_no_direct_qt_imports():
    assert check_qt_imports.find_violations([build_zip.ROOT]) == []


def test_share_as_web_map_is_hidden_until_publish_is_online():
    # Henrik 17/10: GeoDrafter Publish is not online yet, so no plugin may offer "Share as web map".
    from pathlib import Path

    from geodrafter_common import links

    assert links.PUBLISH_AVAILABLE is False
    root = Path(__file__).resolve().parent.parent
    for plugin in ("geodrafter_pro_trace", "geodrafter_measure", "geodrafter_coordinate_finder"):
        src = (root / "plugins" / plugin / "plugin.py").read_text(encoding="utf-8")
        assert "PUBLISH_AVAILABLE" in src, plugin  # share action only added when Publish is online
    measure_src = (root / "plugins" / "geodrafter_measure" / "plugin.py").read_text()
    assert "share_button.setVisible(PUBLISH_AVAILABLE)" in measure_src
    for plugin in ("geodrafter_pro_trace", "geodrafter_measure", "geodrafter_coordinate_finder"):
        meta = (root / "plugins" / plugin / "metadata.txt").read_text(encoding="utf-8").lower()
        assert "share as web map" not in meta and "publish" not in meta, plugin
