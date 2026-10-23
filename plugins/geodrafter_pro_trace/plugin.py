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
        self.split_action = None
        self.tool = None
        self.split_tool = None

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

        split_icon = QIcon(os.path.join(self.plugin_dir, "icon_split.svg"))
        self.split_action = QAction(split_icon, tr("Pro Trace Split"), self.iface.mainWindow())
        self.split_action.setCheckable(True)
        self.split_action.setObjectName("GeoDrafterProTraceSplitAction")
        self.split_action.setToolTip(tr(
            "GeoDrafter Pro Trace Split – cut features of the active layer along a traced line.\n\n"
            "Trace (or click freehand) across the features, then Enter or right click splits them. "
            "With a selection, only the selected features are split. Ctrl+Z undoes."))
        self.split_action.triggered.connect(self.run_split)

        share = QAction(tr("Share as web map…"), self.iface.mainWindow())
        share.triggered.connect(lambda: share_as_web_map(self.iface, PLUGIN_NAME))
        about = QAction(tr("About GeoDrafter Pro Trace"), self.iface.mainWindow())
        about.triggered.connect(lambda: show_about(self.iface.mainWindow(), self.plugin_dir))

        add_to_toolbar(self.iface, self.trace_action)
        add_to_toolbar(self.iface, self.split_action)
        entries = [self.trace_action, self.split_action] + ([share] if PUBLISH_AVAILABLE else []) + [about]
        for action in entries:
            add_to_menu(self.iface, action, MENU)
            self.actions.append(action)

    def run(self, checked=True):
        if self.tool is None:
            from .trace import TraceTool
            self.tool = TraceTool(self.iface)
            self.tool.setAction(self.trace_action)
        self._toggle(self.tool)

    def run_split(self, checked=True):
        if self.split_tool is None:
            from .trace import TraceTool
            self.split_tool = TraceTool(self.iface, mode="split")
            self.split_tool.setAction(self.split_action)
        self._toggle(self.split_tool)

    def _toggle(self, tool):
        canvas = self.iface.mapCanvas()
        if canvas.mapTool() is tool:
            canvas.unsetMapTool(tool)
        else:
            canvas.setMapTool(tool)

    def unload(self):
        canvas = self.iface.mapCanvas()
        for tool in (self.tool, self.split_tool):
            if tool is not None:
                if canvas.mapTool() is tool:
                    canvas.unsetMapTool(tool)
                tool.cleanup()
        self.tool = None
        self.split_tool = None
        remove_actions(self.iface, self.actions, MENU)
        self.actions = []
