# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""GeoDrafter Stream Survey – QGIS plugin entry point.

The calculations live in ``core`` (pure Python, no QGIS import) so they can be
tested and reused outside QGIS; the QGIS user interface lives in ``gui``.
"""


def classFactory(iface):  # noqa: N802 (QGIS API name)
    from .gui.plugin import GeoDrafterStreamSurveyPlugin
    return GeoDrafterStreamSurveyPlugin(iface)
