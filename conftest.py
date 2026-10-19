"""Test setup.

Three levels, each skipped when unavailable:
1. Pure logic – always.
2. Qt widgets – real QGIS (qgis.PyQt), or, without QGIS, a small shim that maps
   ``qgis.PyQt`` to PyQt6 so Qt6 enum/API use is checked even off-QGIS.
3. QGIS core (export, layer tree) – only with python3-qgis.
"""

import importlib
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "plugins"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import qgis.core  # noqa: F401
    HAVE_QGIS = True
except Exception:  # ImportError, or a broken PyQt/sip install
    HAVE_QGIS = False
    for k in [k for k in sys.modules if k == "qgis" or k.startswith("qgis.")]:
        del sys.modules[k]


def _install_pyqt6_shim():
    try:
        importlib.import_module("PyQt6.QtWidgets")
    except Exception:
        return False
    qgis_pkg = types.ModuleType("qgis")
    qgis_pkg.__path__ = []
    pyqt = types.ModuleType("qgis.PyQt")
    pyqt.__path__ = []
    sys.modules["qgis"] = qgis_pkg
    sys.modules["qgis.PyQt"] = pyqt
    qgis_pkg.PyQt = pyqt
    for sub in ("QtCore", "QtGui", "QtWidgets"):
        mod = importlib.import_module("PyQt6." + sub)
        sys.modules["qgis.PyQt." + sub] = mod
        setattr(pyqt, sub, mod)
    return True


HAVE_QT = HAVE_QGIS or _install_pyqt6_shim()
QT_FLAVOUR = "qgis" if HAVE_QGIS else ("pyqt6-shim" if HAVE_QT else None)

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="no Qt (install python3-qgis or PyQt6)")
needs_qgis = pytest.mark.skipif(not HAVE_QGIS, reason="python3-qgis not installed")


@pytest.fixture(scope="session")
def qapp():
    if not HAVE_QT:
        pytest.skip("no Qt")
    if HAVE_QGIS:
        from qgis.core import QgsApplication
        app = QgsApplication.instance() or QgsApplication([], False)
        app.initQgis()
        return app
    from qgis.PyQt.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def pytest_report_header(config):
    return "GeoDrafter Qt backend: %s" % (QT_FLAVOUR or "none")


_EXIT = {"status": 0}


def pytest_sessionfinish(session, exitstatus):
    _EXIT["status"] = int(exitstatus)


def pytest_unconfigure(config):
    # QGIS' C++ teardown can segfault at interpreter exit (well-known with
    # python3-qgis in headless tests); leave right away with pytest's status.
    if HAVE_QGIS:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_EXIT["status"])
