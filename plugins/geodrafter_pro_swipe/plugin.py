# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Pro Swipe – plugin wiring (toolbar, menu, map tool)."""

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsSettings

try:  # Qt6 / QGIS 4: QAction lives in QtGui
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 / QGIS 3.34–3.44
    from qgis.PyQt.QtWidgets import QAction

from .geodrafter_common import PUBLISH_AVAILABLE, share_as_web_map, show_about
from .geodrafter_common.toolbar import add_to_menu, add_to_toolbar, remove_actions

PLUGIN_NAME = "GeoDrafter Pro Swipe"
KEEP_KEY = "geodrafter/pro_swipe/keep"


def tr(text):
    return QCoreApplication.translate("GeoDrafterProSwipe", text)


class GeoDrafterProSwipePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.actions = []
        self.swipe_action = None
        self.keep_action = None
        self.tool = None

    def initGui(self):  # noqa: N802
        icon = QIcon(os.path.join(self.plugin_dir, "icon.svg"))
        self.swipe_action = QAction(icon, tr("Pro Swipe"), self.iface.mainWindow())
        self.swipe_action.setCheckable(True)
        self.swipe_action.setObjectName("GeoDrafterProSwipeAction")
        self.swipe_action.setToolTip(tr(
            "GeoDrafter Pro Swipe – peel a layer back to see what is underneath.\n\n"
            "Select the layer in the Layers panel, then drag in the map: from the top or "
            "bottom to swipe vertically, from a side to swipe horizontally."))
        self.swipe_action.triggered.connect(self.run)

        self.keep_action = QAction(tr("Pro Swipe: keep the swipe on release"), self.iface.mainWindow())
        self.keep_action.setCheckable(True)
        self.keep_action.setObjectName("GeoDrafterProSwipeKeepAction")
        self.keep_action.setChecked(QgsSettings().value(KEEP_KEY, False, type=bool))
        self.keep_action.setToolTip(tr(
            "Leave the swipe on the map when the mouse button is released. "
            "Drag its edge to move it, Esc clears it."))
        self.keep_action.toggled.connect(self.set_keep)

        share = QAction(tr("Share as web map…"), self.iface.mainWindow())
        share.triggered.connect(lambda: share_as_web_map(self.iface, PLUGIN_NAME))
        about = QAction(tr("About GeoDrafter Pro Swipe"), self.iface.mainWindow())
        about.triggered.connect(lambda: show_about(self.iface.mainWindow(), self.plugin_dir))

        add_to_toolbar(self.iface, self.swipe_action)
        entries = [self.swipe_action, self.keep_action] + ([share] if PUBLISH_AVAILABLE else []) + [about]
        for action in entries:
            add_to_menu(self.iface, action)
            self.actions.append(action)

    def run(self, checked=True):
        canvas = self.iface.mapCanvas()
        if self.tool is None:
            from .swipe import SwipeTool
            self.tool = SwipeTool(self.iface, keep=self.keep_action.isChecked())
            self.tool.setAction(self.swipe_action)
        if canvas.mapTool() is self.tool:
            canvas.unsetMapTool(self.tool)
            self.iface.actionPan().trigger()  # back to navigating, as in ArcGIS Pro's Explore
        else:
            canvas.setMapTool(self.tool)

    def set_keep(self, keep):
        QgsSettings().setValue(KEEP_KEY, bool(keep))
        if self.tool is not None:
            self.tool.set_keep(keep)

    def unload(self):
        if self.tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() is self.tool:
                canvas.unsetMapTool(self.tool)
            self.tool.cleanup()
            self.tool = None
        remove_actions(self.iface, self.actions)
        self.actions = []
