# GeoDrafter Coordinate Capture

Capture map coordinates in QGIS 4 (Qt6) and QGIS 3.40 – in the map CRS, a CRS of your choice, and WGS84 as decimal degrees, DMS, DDM, UTM and MGRS.

- **Start capture**, then click on the map. **Track mouse** updates while you move.
- **Go to**: type a coordinate and press Enter – the map centres on it and marks it. Accepts two numbers in the selected CRS (lat, lon if geographic), DD with N/S/E/W, DMS, DDM, UTM (`32V 552000 6320000`) and MGRS (`32V NJ 52000 20000`), so anything the dock shows can be pasted back.
- Every field has a copy button; **Copy all** copies every format.
- **Copy on click** puts the chosen format on the clipboard with each click.
- UTM picks the zone automatically, including the Norway (32V) and Svalbard exceptions. MGRS is truncated to 1 m, as the standard requires.
- **Coordinate converter…** opens the free [GeoDrafter coordinate converter](https://geodrafter.com/coordinate-converter/) (batch conversion, more formats).

The coordinate formats are a Python port of the logic behind geodrafter.com, checked against PROJ.

## Credits and licence

Based on **Coordinate Capture** by **Stefanos Natsis** – https://github.com/uclaros/qgis_coordinate_capture (GPL) – which is a Python port of the former QGIS core plugin. Thank you! A QGIS 4 port of the original plugin has been offered upstream (`upstream/` in this repository).

GeoDrafter additions © 2026 Henrik Rosenskjold (GISkon). Licence: GPL-3.0-or-later (see LICENSE).
Plugin page: https://geodrafter.com/qgis/coordinate-capture/ · Source and issues: https://github.com/hrosenskjold/GeoDrafter-QGIS-Plugins
