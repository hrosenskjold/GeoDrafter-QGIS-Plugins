# GeoDrafter Pro Trace

**Tracing that just works.** ArcGIS Pro-style tracing for QGIS 4 (Qt6) and QGIS 3.40: click on a line, move the mouse, and the path along the visible line and polygon layers is traced and remembered as you go.

## Why not QGIS' built-in tracing?

QGIS has built-in tracing (press T while digitizing). It works well when your snapping is set up for the right layers. Pro Trace is different in a few ways:

| | QGIS built-in tracing | GeoDrafter Pro Trace |
|---|---|---|
| Snapping setup | Needs snapping enabled, traces only snapping layers | None – uses its own snapping on the line and polygon layers **switched on in the Layers panel** |
| Long winding lines | Shortest path from the last vertex; can jump to a more direct road or boundary | Follows the cursor step by step and **remembers** the trace; moving back pulls it in |
| Freehand | A click that does not snap adds a straight segment | Click off the lines to add a freehand vertex – mix freely, with a preview of the straight part |
| Nearly overlapping lines | Graph can silently become empty | Lines are noded first (unary union, grid fallback); tells you if tracing is off |
| Many features | Turns off above a limit | Also has a limit (30,000 features in view) and tells you to zoom in |

## Use

1. Select the line or polygon layer to draw in (editing starts automatically).
2. Click **Pro Trace** on the Plugins toolbar (or Vector ▸ GeoDrafter).
3. Click on a line, move along it, click to lock. Click off the lines for a freehand vertex.
4. **Enter** or **right click** saves · **Backspace** undoes · **Esc** cancels.

The plugin collects no telemetry.

## Credits and licence

Written by Henrik Rosenskjold (GISkon) – https://geodrafter.com/qgis/pro-trace/
Licence: GPL-2.0-or-later (see LICENSE). Source and issues: https://github.com/hrosenskjold/GeoDrafter-QGIS-Plugins
