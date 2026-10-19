# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2020 Stefanos Natsis (original Coordinate Capture plugin)
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Coordinate Capture – QGIS plugin entry point."""


def classFactory(iface):  # noqa: N802 (QGIS API name)
    from .plugin import GeoDrafterCoordinateCapturePlugin
    return GeoDrafterCoordinateCapturePlugin(iface)
