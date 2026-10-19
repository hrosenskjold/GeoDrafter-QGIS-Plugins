# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""About dialog shared by the GeoDrafter plugins."""

import html

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QTextBrowser, QVBoxLayout,
)

from . import links
from .metadata import read_metadata


def about_html(meta):
    """Build the dialog body from plugin metadata (escaped, links only to known sites)."""
    e = html.escape
    homepage = meta.get("homepage") or links.QGIS_PAGES_URL
    parts = [
        "<h2>%s <small>%s</small></h2>" % (e(meta.get("name", "GeoDrafter")),
                                           e(meta.get("version", ""))),
        "<p>%s</p>" % e(meta.get("about") or meta.get("description", "")),
        "<p>%s · %s</p>" % (e(meta.get("author", "")), e(meta.get("license", ""))),
        "<ul>",
        '<li><a href="%s">%s</a></li>' % (e(homepage), "Plugin page on geodrafter.com"),
        '<li><a href="%s">GeoDrafter</a> – free map and coordinate tools</li>'
        % links.GEODRAFTER_URL,
        '<li><a href="%s">FileReshape</a> – convert GIS and CAD files in the browser</li>'
        % links.FILERESHAPE_URL,
        '<li><a href="%s">Source code</a> · <a href="%s">Report a problem</a></li>'
        % (e(meta.get("repository") or links.GITHUB_URL),
           e(meta.get("tracker") or links.TRACKER_URL)),
        "</ul>",
    ]
    return "\n".join(parts)


class AboutDialog(QDialog):
    def __init__(self, plugin_dir, parent=None):
        super().__init__(parent)
        meta = read_metadata(plugin_dir)
        self.setWindowTitle("About %s" % meta.get("name", "GeoDrafter"))
        layout = QVBoxLayout(self)
        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(about_html(meta))
        layout.addWidget(self.browser)
        note = QLabel("No data is sent anywhere unless you choose to.", self)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(460, 360)
