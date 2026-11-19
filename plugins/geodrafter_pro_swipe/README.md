# GeoDrafter Pro Swipe

**Peel a layer back to see what is underneath.** ArcGIS Pro-style swipe for QGIS 4 (Qt6) and QGIS 3.34 or newer: select a layer, drag in the map, and the layer is pulled back from the edge of the map to the cursor.

## Use

1. Select the layer to swipe in the Layers panel. Several layers or a whole group work too.
2. Click **Pro Swipe** on the Plugins toolbar (or Plugins ▸ GeoDrafter).
3. Press the left mouse button and drag in the map:
   - start near the **top or bottom** of the map to swipe vertically,
   - start near the **left or right** side to swipe horizontally.

   The cursor arrow shows which way the layer will be pulled.
4. Release the mouse and the layer is back.

Mouse wheel, middle button and space bar zoom and pan as usual while the tool is active. Click the button again to go back to the Pan tool.

### Keep the swipe on the map

Switch on **Plugins ▸ GeoDrafter ▸ Pro Swipe: keep the swipe on release** to leave the swipe in place when the mouse button is released – handy for screenshots or for panning around with half of the layer peeled back. Drag the swipe edge to move it, start a new drag elsewhere to swipe from another side, **Esc** clears it.

## Good to know

- What shows in the swiped part is the map rendered without the selected layers, so transparency, blend modes and labels look exactly as if the layers were switched off there.
- Any layer type can be swiped: raster, vector, WMS/WMTS/XYZ, vector tiles, mesh, point clouds.
- The layer must be switched on. A layer that is selected but not drawn in the map cannot be swiped; the tool tells you.
- The plugin changes nothing in the project – no layer, style or visibility is touched.

The plugin collects no telemetry.

## Credits and licence

Written by Henrik Rosenskjold (GISkon) – https://geodrafter.com/qgis/pro-swipe/
Licence: GPL-2.0-or-later (see LICENSE). Source and issues: https://github.com/hrosenskjold/GeoDrafter-QGIS-Plugins
