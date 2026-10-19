# plugins/

One folder per plugin, e.g. `plugins/geodrafter_pro_trace/`:

- `metadata.txt` – checked by `geodrafter_common/metadata.py`
- `__init__.py` with `classFactory(iface)`
- `geodrafter_common` – symlink to `../../geodrafter_common`; `tools/build_zip.py` puts a real copy in the zip.
  Import it relatively: `from .geodrafter_common import show_about`
- `LICENSE` when the plugin's licence differs from the repository's
- `tests/` – pytest (not included in the zip)

Build: `make zip PLUGIN=<folder>` → `dist/<folder>-<version>.zip`.
