# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""URLs shared by the GeoDrafter QGIS plugins.

Pure Python (no QGIS imports) so it can be unit tested anywhere.
Links carry no tracking or user data.
"""

import re

GEODRAFTER_URL = "https://geodrafter.com/"
FILERESHAPE_URL = "https://filereshape.com/"
GITHUB_URL = "https://github.com/hrosenskjold/GeoDrafter-QGIS-Plugins"
TRACKER_URL = GITHUB_URL + "/issues"
QGIS_PAGES_URL = GEODRAFTER_URL + "qgis/"

# GeoDrafter Publish (cloud). Default entry point; can be overridden in
# QGIS settings under SETTINGS_PUBLISH_URL_KEY (e.g. for a staging server).
PUBLISH_URL = GEODRAFTER_URL + "publish/"
# GeoDrafter Publish is not online yet. While False, the plugins show no
# "Share as web map" action or button (Henrik 17/10). Set True once it is live.
PUBLISH_AVAILABLE = False
SETTINGS_PUBLISH_URL_KEY = "geodrafter/publish_url"

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slug_from_name(name):
    """'GeoDrafter Pro Trace' -> 'pro-trace' (the GeoDrafter prefix is dropped)."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    if words and words[0].lower() == "geodrafter":
        words = words[1:]
    slug = "-".join(w.lower() for w in words)
    if not slug:
        raise ValueError("cannot make a slug from %r" % (name,))
    return slug


def plugin_homepage(slug):
    """The plugin's page on geodrafter.com, used as `homepage` in metadata."""
    if not _SLUG_RE.match(slug or ""):
        raise ValueError("invalid plugin slug: %r" % (slug,))
    return QGIS_PAGES_URL + slug + "/"


def is_safe_http_url(url):
    """Only http(s) URLs may be opened from settings (no file:, javascript: ...)."""
    return isinstance(url, str) and re.match(r"^https?://[^\s/]+", url) is not None


def publish_url(override=None):
    """GeoDrafter Publish URL; a valid http(s) override wins over the default."""
    if override and is_safe_http_url(override.strip()):
        return override.strip()
    return PUBLISH_URL
