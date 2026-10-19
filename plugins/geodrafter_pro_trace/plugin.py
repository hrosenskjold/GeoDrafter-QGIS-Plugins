# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2024-2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Pro Trace – plugin wiring (toolbar, menu, map tool)."""

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon

try:  # Qt6 / QGIS 4: QAction lives in QtGui
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 / QGIS 3.40
    from qgis.PyQt.QtWidgets import QAction

from .geodrafter_common import PUBLISH_AVAILABLE, share_as_web_map, show_about
from .geodrafter_common.toolbar import add_to_menu, add_to_toolbar, remove_actions

PLUGIN_NAME = "GeoDrafter Pro Trace"
MENU = "vector"  # Vector ▸ GeoDrafter: Pro Trace is an editing tool


def tr(text):
    return QCoreApplication.translate("GeoDrafterProTrace", text)


class GeoDrafterProTracePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.actions = []
        self.trace_action = None
        self.tool = None

    def initGui(self):
        icon = QIcon(os.path.join(self.plugin_dir, "icon.svg"))
        self.trace_action = QAction(icon, tr("Pro Trace"), self.iface.mainWindow())
        self.trace_action.setCheckable(True)
        self.trace_action.setObjectName("GeoDrafterProTraceAction")
        self.trace_action.setToolTip(tr(
            "GeoDrafter Pro Trace – trace along all visible layers, no snapping setup.\n\n"
            "Click on a line, move along it, click to lock. A click off the lines adds a "
            "freehand vertex. Enter or right click saves, Backspace undoes, Esc cancels."))
        self.trace_action.triggered.connect(self.run)

        share = QAction(tr("Share as web map…"), self.iface.mainWindow())
        share.triggered.connect(lambda: share_as_web_map(self.iface, PLUGIN_NAME))
        about = QAction(tr("About GeoDrafter Pro Trace"), self.iface.mainWindow())
        about.triggered.connect(lambda: show_about(self.iface.mainWindow(), self.plugin_dir))

        add_to_toolbar(self.iface, self.trace_action)
        for action in (self.trace_action, share, about) if PUBLISH_AVAILABLE else (self.trace_action, about):
            add_to_menu(self.iface, action, MENU)
            self.actions.append(action)

    def run(self, checked=True):
        canvas = self.iface.mapCanvas()
        if self.tool is not None and canvas.mapTool() is self.tool:
            canvas.unsetMapTool(self.tool)
            return
        if self.tool is None:
            from .trace import TraceTool
            self.tool = TraceTool(self.iface)
            self.tool.setAction(self.trace_action)
        canvas.setMapTool(self.tool)

    def unload(self):
        if self.tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() is self.tool:
                canvas.unsetMapTool(self.tool)
            self.tool.cleanup()
            self.tool = None
        remove_actions(self.iface, self.actions, MENU)
        self.actions = []
