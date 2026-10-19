#!/usr/bin/env python3
"""Build installable zips for plugins/<name>/.

Each zip contains one top-level folder <name>/ with the plugin files, a real
copy of geodrafter_common/ (the symlink in the source tree is resolved) and
LICENSE. Tests, caches and dev files are left out. Metadata is checked first.

Usage: python3 tools/build_zip.py [name ...]   (default: every plugin)
Output: dist/<name>-<version>.zip
"""

import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from geodrafter_common.metadata import check_metadata, read_metadata  # noqa: E402

EXCLUDE_DIRS = {"__pycache__", "tests", "test", ".pytest_cache", ".git", "help_src"}
EXCLUDE_EXT = (".pyc", ".pyo", ".orig", ".rej", ".swp", ".ui~")
EXCLUDE_FILES = {".DS_Store", "Thumbs.db", ".gitignore", "Makefile", "pb_tool.cfg", "TESTING.md"}


def list_plugins(plugins_dir):
    return sorted(
        d for d in os.listdir(plugins_dir)
        if not d.startswith((".", "_"))
        and os.path.isfile(os.path.join(plugins_dir, d, "metadata.txt")))


def _walk(src):
    for root, dirs, files in os.walk(src, followlinks=True):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for name in sorted(files):
            if name in EXCLUDE_FILES or name.endswith(EXCLUDE_EXT):
                continue
            yield os.path.join(root, name)


def build(name, plugins_dir, common_dir, dist_dir, license_file=None):
    src = os.path.join(plugins_dir, name)
    meta = read_metadata(src)
    problems = check_metadata(meta)
    if problems:
        raise SystemExit("%s: metadata problems:\n  %s" % (name, "\n  ".join(problems)))
    os.makedirs(dist_dir, exist_ok=True)
    out = os.path.join(dist_dir, "%s-%s.zip" % (name, meta["version"]))
    seen = set()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in _walk(src):
            arc = os.path.join(name, os.path.relpath(path, src)).replace(os.sep, "/")
            zf.write(path, arc)
            seen.add(arc)
        common_arc = name + "/geodrafter_common/"
        if not any(a.startswith(common_arc) for a in seen):
            for path in _walk(common_dir):
                arc = common_arc + os.path.relpath(path, common_dir).replace(os.sep, "/")
                zf.write(path, arc)
                seen.add(arc)
        if license_file and os.path.isfile(license_file) and name + "/LICENSE" not in seen:
            zf.write(license_file, name + "/LICENSE")
    return out


def main(argv):
    plugins_dir = os.path.join(ROOT, "plugins")
    names = argv or list_plugins(plugins_dir)
    if not names:
        print("No plugins with metadata.txt under plugins/ yet.")
        return 0
    for name in names:
        out = build(name, plugins_dir, os.path.join(ROOT, "geodrafter_common"),
                    os.path.join(ROOT, "dist"), os.path.join(ROOT, "LICENSE"))
        print("built", os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
