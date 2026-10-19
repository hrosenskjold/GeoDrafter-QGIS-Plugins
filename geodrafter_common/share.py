# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""'Share as web map' (Del som webkort).

A real function, not an advert: the visible vector layers are exported locally
as GeoJSON (EPSG:4326), the folder is opened, and GeoDrafter Publish opens in
the browser so the user can upload the files there. Nothing is uploaded by the
plugin itself, and the user confirms before anything happens.
"""

import datetime
import os
import re

from .links import SETTINGS_PUBLISH_URL_KEY, publish_url

_UNSAFE = re.compile(r"[^A-Za-z0-9æøåÆØÅ_.-]+")


def safe_filename(name, used=None, ext=".geojson"):
    """Layer name -> unique, filesystem-safe file name."""
    base = _UNSAFE.sub("_", name or "").strip("._") or "layer"
    base = base[:60]
    candidate, n = base + ext, 2
    used = used if used is not None else set()
    while candidate.lower() in used:
        candidate = "%s_%d%s" % (base, n, ext)
        n += 1
    used.add(candidate.lower())
    return candidate


def _enum_int(value):
    """Enum or int -> int (scoped enums in Qt6/QGIS 4 are not ints)."""
    value = getattr(value, "value", value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def default_export_dir(home=None, now=None):
    now = now or datetime.datetime.now()
    home = home or os.path.expanduser("~")
    return os.path.join(home, "GeoDrafter", "webkort-" + now.strftime("%Y%m%d-%H%M%S"))


def visible_vector_layers(project):
    """Vector layers that are checked (visible) in the layer tree, top to bottom."""
    from qgis.core import Qgis

    root = project.layerTreeRoot()
    result = []
    for node in root.findLayers():
        layer = node.layer()
        if layer is None or not node.isVisible():
            continue
        if layer.type() == Qgis.LayerType.Vector and layer.isSpatial():
            result.append(layer)
    return result


def export_layers(layers, out_dir, transform_context):
    """Write each layer to GeoJSON in EPSG:4326. Returns (written_paths, errors)."""
    from qgis.core import (
        QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsVectorFileWriter,
    )

    os.makedirs(out_dir, exist_ok=True)
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    used, written, errors = set(), [], []
    for layer in layers:
        path = os.path.join(out_dir, safe_filename(layer.name(), used))
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GeoJSON"
        opts.fileEncoding = "UTF-8"
        opts.ct = QgsCoordinateTransform(layer.crs(), wgs84, transform_context)
        opts.layerOptions = ["RFC7946=YES", "COORDINATE_PRECISION=7"]
        res = QgsVectorFileWriter.writeAsVectorFormatV3(layer, path, transform_context, opts)
        err = res[0] if isinstance(res, tuple) else res
        if _enum_int(err) == 0:  # NoError (enum moved between QGIS versions)
            written.append(path)
        else:
            msg = res[1] if isinstance(res, tuple) and len(res) > 1 else str(err)
            errors.append("%s: %s" % (layer.name(), msg))
    return written, errors


def share_as_web_map(iface, plugin_name=""):
    """Interactive flow used by the plugins' 'Share as web map' button."""
    from qgis.core import QgsProject, QgsSettings
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices
    from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

    parent = iface.mainWindow()
    project = QgsProject.instance()
    layers = visible_vector_layers(project)
    title = "Share as web map"
    if not layers:
        QMessageBox.information(parent, title, "There are no visible vector layers to share.")
        return None
    url = publish_url(QgsSettings().value(SETTINGS_PUBLISH_URL_KEY, "", type=str))
    names = "\n".join("• " + lyr.name() for lyr in layers[:15])
    if len(layers) > 15:
        names += "\n• … (%d more)" % (len(layers) - 15)
    answer = QMessageBox.question(
        parent, title,
        "These visible layers will be saved on your computer as GeoJSON (WGS84):\n\n"
        "%s\n\nThen GeoDrafter Publish opens in your browser (%s), where you can "
        "upload the files to make a web map. Nothing is uploaded automatically.\n\n"
        "Continue?" % (names, url))
    if answer != QMessageBox.StandardButton.Yes:
        return None
    out_dir = QFileDialog.getExistingDirectory(
        parent, "Folder for the web map files", os.path.dirname(default_export_dir()))
    if not out_dir:
        return None
    out_dir = os.path.join(out_dir, os.path.basename(default_export_dir()))
    written, errors = export_layers(layers, out_dir, project.transformContext())
    if errors:
        QMessageBox.warning(parent, title, "Some layers could not be saved:\n\n" + "\n".join(errors))
    if written:
        QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))
        QDesktopServices.openUrl(QUrl(url))
        iface.messageBar().pushSuccess(
            plugin_name or "GeoDrafter",
            "%d layer(s) saved in %s – upload them in GeoDrafter Publish." % (len(written), out_dir))
    return written
