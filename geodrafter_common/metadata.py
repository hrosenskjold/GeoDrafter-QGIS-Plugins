# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Read and check a plugin's metadata.txt (pure Python, no QGIS)."""

import configparser
import os

REQUIRED_KEYS = (
    "name", "qgisMinimumVersion", "qgisMaximumVersion", "description",
    "about", "version", "author", "email", "repository", "tracker",
    "homepage", "license",
)
AUTHOR = "Henrik Rosenskjold (GISkon)"
EMAIL = "contact@geodrafter.com"
MIN_QGIS = "3.40"
# Lowest qgisMinimumVersion a plugin may declare – only after Henrik has tested it there (CI runs QGIS 3.34)
MIN_QGIS_ALLOWED = ("3.34", "3.40")
MAX_QGIS = "4.99"


def read_metadata(plugin_dir):
    """Return the [general] section of plugin_dir/metadata.txt as a dict."""
    path = os.path.join(plugin_dir, "metadata.txt")
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # keep camelCase keys
    with open(path, encoding="utf-8") as fh:
        cp.read_file(fh)
    return dict(cp["general"]) if cp.has_section("general") else {}


def check_metadata(meta):
    """Return a list of problems (empty list = OK)."""
    problems = []
    for key in REQUIRED_KEYS:
        if not meta.get(key, "").strip():
            problems.append("missing %s" % key)
    name = meta.get("name", "")
    if name and not name.startswith("GeoDrafter "):
        problems.append("name must start with 'GeoDrafter ': %r" % name)
    if meta.get("qgisMinimumVersion") and meta["qgisMinimumVersion"] not in MIN_QGIS_ALLOWED:
        problems.append("qgisMinimumVersion should be one of %s" % ", ".join(MIN_QGIS_ALLOWED))
    if meta.get("qgisMaximumVersion") and meta["qgisMaximumVersion"] != MAX_QGIS:
        problems.append("qgisMaximumVersion should be %s" % MAX_QGIS)
    if meta.get("supportsQt6", "").strip().lower() not in ("true", "yes", "1"):
        problems.append("supportsQt6 must be True")
    if meta.get("author") and meta["author"] != AUTHOR:
        problems.append("author should be %r" % AUTHOR)
    if meta.get("homepage") and not meta["homepage"].startswith(
            "https://geodrafter.com/qgis/"):
        problems.append("homepage must be the plugin page on geodrafter.com/qgis/")
    for key in ("repository", "tracker"):
        if meta.get(key) and not meta[key].startswith("https://github.com/"):
            problems.append("%s must be a GitHub URL" % key)
    return problems
