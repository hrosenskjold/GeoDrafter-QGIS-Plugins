"""Build every plugin zip, unpack it and load it like QGIS would (no symlinks, no tests)."""

import importlib
import os
import sys
import zipfile

import pytest

from conftest import ROOT, needs_qgis
from tools import build_zip

PLUGINS = build_zip.list_plugins(os.path.join(ROOT, "plugins"))


@pytest.mark.parametrize("name", PLUGINS)
def test_zip_contents(tmp_path, name):
    out = build_zip.build(name, os.path.join(ROOT, "plugins"),
                          os.path.join(ROOT, "geodrafter_common"), str(tmp_path),
                          os.path.join(ROOT, "LICENSE"))
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert zf.testzip() is None
        for info in zf.infolist():   # no symlinks inside the zip
            assert (info.external_attr >> 28) != 0xA, info.filename
    for required in ("__init__.py", "metadata.txt", "LICENSE", "icon.svg", "README.md",
                     "geodrafter_common/__init__.py", "geodrafter_common/share.py"):
        assert "%s/%s" % (name, required) in names
    assert not any("/tests/" in n or n.endswith(".pyc") for n in names)


@needs_qgis
@pytest.mark.parametrize("name", PLUGINS)
def test_zip_loads_in_qgis(qapp, tmp_path, name):
    from qgis.gui import QgsMapCanvas
    from qgis_fakes import fake_iface

    out = build_zip.build(name, os.path.join(ROOT, "plugins"),
                          os.path.join(ROOT, "geodrafter_common"), str(tmp_path / "dist"))
    target = tmp_path / "profile" / "python" / "plugins"
    zipfile.ZipFile(out).extractall(str(target))
    alias = "zipped_" + name
    os.rename(str(target / name), str(target / alias))   # avoid clashing with the source package
    sys.path.insert(0, str(target))
    try:
        mod = importlib.import_module(alias)
        assert os.path.realpath(mod.__file__).startswith(str(tmp_path))
        canvas = QgsMapCanvas()
        iface = fake_iface(canvas, None)
        plugin = mod.classFactory(iface)
        plugin.initGui()
        # tool + About (Share hidden: PUBLISH_AVAILABLE); Pro Trace sits in the Vector menu.
        # Pro Trace adds Split, Coordinate Finder adds "points and vertices".
        extra = {"geodrafter_pro_trace": 1, "geodrafter_coordinate_finder": 1}.get(name, 0)
        assert len(iface.menu) + len(iface.vector_menu) == 2 + extra
        # Pro Trace has two tools (trace and split); the others one
        assert len(iface.pluginToolBar().actions()) == (2 if name == "geodrafter_pro_trace" else 1)
        plugin.unload()
        assert iface.menu == [] and iface.vector_menu == []
        assert iface.pluginToolBar().actions() == []
    finally:
        sys.path.remove(str(target))
