# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Coordinate Finder and Converter – QGIS plugin entry point."""


def classFactory(iface):  # noqa: N802 (QGIS API name)
    from .plugin import GeoDrafterCoordinateFinderPlugin
    return GeoDrafterCoordinateFinderPlugin(iface)
