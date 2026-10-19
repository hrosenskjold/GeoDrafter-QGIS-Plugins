# GeoDrafter Coordinates

A QGIS panel that shows a map position in every common format at once – and goes to a position you type. Built for QGIS 4 (Qt6), also runs on QGIS 3.40.

- **Pick on map**: click to read a position; **Follow mouse** updates while you move. Right click or Esc stops.
- **Formats**: map CRS, a CRS you choose (remembered), WGS84 decimal degrees, DMS, DDM, UTM (automatic zone incl. the Norway/Svalbard exceptions) and MGRS (truncated to 1 m, as the standard requires).
- **Copy**: double click a row or press Ctrl+C, right click for *Copy all*, or let *On pick* copy one format with every click.
- **Go to**: type a coordinate and press Enter – the map centres on it and marks it. Accepts two numbers in the chosen CRS (lat, lon when it is geographic), DD with N/S/E/W, DMS, DDM, UTM (`32V 552000 6320000`) and MGRS (`32V NJ 52000 20000`), with decimal commas too.
- **Many coordinates?** The panel links to the free [GeoDrafter coordinate converter](https://geodrafter.com/coordinate-converter/).

The coordinate formats are a Python port of the logic behind geodrafter.com, checked against PROJ.

Licence: GPL-2.0-or-later (see LICENSE). © 2026 Henrik Rosenskjold (GISkon).
Plugin page: https://geodrafter.com/qgis/coordinates/ · Source and issues: https://github.com/hrosenskjold/GeoDrafter-QGIS-Plugins
