import os

from conftest import needs_qgis, needs_qt
from test_common_pure import GOOD_META


@needs_qt
def test_about_dialog(qapp, tmp_path):
    from geodrafter_common.about import AboutDialog, about_html
    (tmp_path / "metadata.txt").write_text(
        GOOD_META.replace("about=A test plugin.", "about=<b>x</b> & y"), encoding="utf-8")
    dlg = AboutDialog(str(tmp_path))
    assert dlg.windowTitle() == "About GeoDrafter Test Tool"
    text = dlg.browser.toPlainText()
    assert "GeoDrafter Test Tool" in text and "0.2.0" in text
    assert "FileReshape" in text and "<b>x</b> & y" in text  # escaped, shown literally
    html = about_html({"name": "GeoDrafter X"})
    assert "https://filereshape.com/" in html and "https://geodrafter.com/" in html
    dlg.close()


@needs_qgis
def test_export_visible_layers(qapp, tmp_path):
    import json
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer
    from geodrafter_common.share import export_layers, visible_vector_layers

    project = QgsProject()
    shown = QgsVectorLayer("Point?crs=EPSG:25832", "Punkter / test", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500000, 6200000)))
    shown.dataProvider().addFeatures([f])
    hidden = QgsVectorLayer("Point?crs=EPSG:4326", "skjult", "memory")
    project.addMapLayers([shown, hidden])
    project.layerTreeRoot().findLayer(hidden.id()).setItemVisibilityChecked(False)

    layers = visible_vector_layers(project)
    assert [lyr.name() for lyr in layers] == ["Punkter / test"]
    written, errors = export_layers(layers, str(tmp_path / "out"), project.transformContext())
    assert errors == []
    assert [os.path.basename(p) for p in written] == ["Punkter_test.geojson"]
    with open(written[0], encoding="utf-8") as fh:
        lon, lat = json.load(fh)["features"][0]["geometry"]["coordinates"]
    assert 8.9 < lon < 9.1 and 55.9 < lat < 56.0  # UTM32 500000/6200000 -> ~9.0E 55.95N
