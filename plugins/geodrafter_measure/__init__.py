# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Measure – QGIS plugin entry point."""


def classFactory(iface):  # noqa: N802 (QGIS API name)
    from .plugin import GeoDrafterMeasurePlugin
    return GeoDrafterMeasurePlugin(iface)
