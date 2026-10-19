# GeoDrafter for QGIS

QGIS plugins by [GeoDrafter](https://geodrafter.com/) (Henrik Rosenskjold, GISkon),
built for QGIS 4 (Qt6) and also running on QGIS 3.40:

| Plugin | What it does | Page |
|---|---|---|
| GeoDrafter Pro Trace | ArcGIS Pro-style tracing along all visible layers, no snapping setup | https://geodrafter.com/qgis/pro-trace/ |
| GeoDrafter Measure | Geodesic distance, area and radius, saved as a layer | https://geodrafter.com/qgis/measure/ |
| GeoDrafter Coordinate Finder and Converter | Positions in any CRS, DD, DMS, DDM, UTM and MGRS; go to a typed coordinate | https://geodrafter.com/qgis/coordinate-finder-and-converter/ |

Install them from the QGIS Plugin Manager (search for "GeoDrafter").
Bugs and ideas: [issues](https://github.com/hrosenskjold/GeoDrafter-QGIS-Plugins/issues).

## Layout

- `plugins/<name>/` – one folder per plugin (`metadata.txt`, code, `tests/`)
- `geodrafter_common/` – shared About dialog, toolbar/menu helpers and metadata checks; copied into every plugin zip
  (each plugin folder has a `geodrafter_common` symlink to it)
- `tools/` – `build_zip.py` (installable zips) and `check_qt_imports.py` (only `qgis.PyQt`, never PyQt5/PyQt6 directly)

```
make check            # flake8 + Qt import check + pytest
make zip              # dist/<plugin>-<version>.zip for every plugin
make zip PLUGIN=geodrafter_pro_trace
```

Tests run without QGIS (pure logic), with PyQt6 via a `qgis.PyQt` shim (Qt6 API check),
and with python3-qgis when installed; CI also runs them in the official QGIS 4 image.

## Licence

Every plugin and `geodrafter_common` are GPL-2.0-or-later (each plugin folder carries its LICENSE);
the repository as a whole is GPL-3.0 (LICENSE).
