# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Toolbar and menu for the GeoDrafter plugin family.

Every plugin puts its main button on QGIS' own Plugins toolbar
(``iface.addToolBarIcon``), so the buttons sit with the user's other plugins,
and its menu entries under a "GeoDrafter" submenu – in the Plugins menu by
default, or in the Vector menu (``menu="vector"``) for editing tools, as the
plugins.qgis.org guidelines ask.
"""

MENU_NAME = "&GeoDrafter"


def add_to_toolbar(iface, action):
    """Put ``action`` on QGIS' Plugins toolbar."""
    iface.addToolBarIcon(action)


def add_to_menu(iface, action, menu="plugins"):
    """Put ``action`` under GeoDrafter in the Plugins (default) or Vector menu."""
    if menu == "vector":
        iface.addPluginToVectorMenu(MENU_NAME, action)
    else:
        iface.addPluginToMenu(MENU_NAME, action)


def remove_actions(iface, actions, menu="plugins"):
    """Remove a plugin's actions from the Plugins toolbar and the GeoDrafter menu."""
    for action in actions:
        if menu == "vector":
            iface.removePluginVectorMenu(MENU_NAME, action)
        else:
            iface.removePluginMenu(MENU_NAME, action)
        iface.removeToolBarIcon(action)
