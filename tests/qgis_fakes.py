"""Minimal QgisInterface stand-in for plugin tests (needs python3-qgis)."""


def fake_iface(canvas, active_layer):
    from qgis.gui import QgsAdvancedDigitizingDockWidget, QgsMessageBar
    from qgis.PyQt.QtWidgets import QMainWindow
    from qgis.core import QgsFeature

    class Tools:
        def addFeature(self, layer, attrs, geom):  # noqa: N802
            f = QgsFeature(layer.fields())
            f.setGeometry(geom)
            return layer.addFeature(f), f

    class Iface:
        def __init__(self):
            self.window = QMainWindow()
            self.bar = QgsMessageBar()
            self.cad = QgsAdvancedDigitizingDockWidget(canvas)
            self.tools = Tools()
            self.layer = active_layer
            self.menu = []
            self.vector_menu = []
            self.plugin_toolbar = None

        def mapCanvas(self): return canvas  # noqa: E704,N802
        def cadDockWidget(self): return self.cad  # noqa: E704,N802
        def messageBar(self): return self.bar  # noqa: E704,N802
        def activeLayer(self): return self.layer  # noqa: E704,N802
        def vectorLayerTools(self): return self.tools  # noqa: E704,N802
        def mainWindow(self): return self.window  # noqa: E704,N802
        def addToolBar(self, name): return self.window.addToolBar(name)  # noqa: E704,N802

        def pluginToolBar(self):  # noqa: N802
            if self.plugin_toolbar is None:
                self.plugin_toolbar = self.window.addToolBar("Plugins")
            return self.plugin_toolbar

        def addToolBarIcon(self, action): self.pluginToolBar().addAction(action)  # noqa: E704,N802
        def removeToolBarIcon(self, action): self.pluginToolBar().removeAction(action)  # noqa: E704,N802
        def addPluginToMenu(self, menu, action): self.menu.append(action)  # noqa: E704,N802

        def removePluginMenu(self, menu, action):  # noqa: N802
            self.menu.remove(action)

        def addPluginToVectorMenu(self, menu, action):  # noqa: N802
            self.vector_menu.append(action)

        def removePluginVectorMenu(self, menu, action):  # noqa: N802
            self.vector_menu.remove(action)

        def addDockWidget(self, area, dock):  # noqa: N802
            self.window.addDockWidget(area, dock)

        def removeDockWidget(self, dock):  # noqa: N802
            self.window.removeDockWidget(dock)

    return Iface()
