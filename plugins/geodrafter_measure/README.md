# GeoDrafter Measure

Geodesic distance, area and radius measurement for QGIS 4 (Qt6) and QGIS 3.40 – the same results as GeoDrafter's web tools ([distance calculator](https://geodrafter.com/distance-calculator/), [area calculator](https://geodrafter.com/area-calculator/), [radius map](https://geodrafter.com/radius-map/)).

- **Distance** – click points; total and segment lengths.
- **Area** – click a polygon; area and perimeter.
- **Radius** – click the centre and drag, or type a radius ("5 km", "3 mi", "2 NM") and place the circle with one click. The circle is a true geodesic circle.
- Right click, double click or Enter finishes · Backspace removes the last point · Esc clears.
- Always measured on the ellipsoid (the project's, or WGS84), whatever the map projection.
- Metric/imperial auto units or a fixed unit; **Copy** puts the result on the clipboard.
- **Keep on map** adds finished measurements to the layers *GeoDrafter distances* and *GeoDrafter areas* with the values as attributes; **Export…** saves them to a GeoPackage.

© 2026 Henrik Rosenskjold (GISkon). Licence: GPL-2.0-or-later (see LICENSE).
Plugin page: https://geodrafter.com/qgis/measure/ · Source and issues: https://github.com/hrosenskjold/GeoDrafter-QGIS-Plugins
