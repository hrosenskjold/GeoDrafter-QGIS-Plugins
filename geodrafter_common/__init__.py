# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Shared code for the GeoDrafter QGIS plugin family.

This package is copied into every plugin zip (see tools/build_zip.py), so each
plugin imports it relatively: ``from .geodrafter_common import show_about``.
In the source tree, ``plugins/<name>/geodrafter_common`` is a symlink to here.

Only ``qgis.PyQt`` is used for Qt (never PyQt5/PyQt6 directly), so the code
runs on QGIS 3.40 (Qt5) and QGIS 4.x (Qt6).
"""

__version__ = "0.1.0"

from .links import (  # noqa: F401
    FILERESHAPE_URL,
    GEODRAFTER_URL,
    GITHUB_URL,
    PUBLISH_AVAILABLE,
    PUBLISH_URL,
    plugin_homepage,
    publish_url,
    slug_from_name,
)


def show_about(parent, plugin_dir):
    """Open the About dialog for the plugin in ``plugin_dir`` (lazy Qt import)."""
    from .about import AboutDialog

    dlg = AboutDialog(plugin_dir, parent)
    dlg.exec()
    return dlg


def share_as_web_map(iface, plugin_name=""):
    """'Del som webkort' / 'Share as web map' (lazy QGIS import)."""
    from .share import share_as_web_map as _share

    return _share(iface, plugin_name)
