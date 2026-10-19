#!/usr/bin/env python3
"""Fail if any Python file imports PyQt5/PyQt6/PySide directly.

Usage: python3 tools/check_qt_imports.py [paths...]   (default: repo root)
"""

import os
import re
import sys

FORBIDDEN = re.compile(
    r"^\s*(?:from|import)\s+(PyQt5|PyQt6|PySide2|PySide6|sip)\b", re.MULTILINE)
SKIP_DIRS = {".git", "__pycache__", "build", "dist", ".venv", "venv", "node_modules"}
SELF = os.path.abspath(__file__)


def iter_py_files(paths):
    for path in paths:
        if os.path.isfile(path):
            if path.endswith(".py"):
                yield path
            continue
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS
                             and not os.path.islink(os.path.join(root, d)))
            for name in sorted(files):
                if name.endswith(".py"):
                    yield os.path.join(root, name)


def find_violations(paths):
    found = []
    for path in iter_py_files(paths):
        if os.path.abspath(path) == SELF:
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for m in FORBIDDEN.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            found.append((path, line, m.group(1)))
    return found


def main(argv):
    paths = argv or [os.path.dirname(os.path.dirname(SELF))]
    found = find_violations(paths)
    for path, line, mod in found:
        print("%s:%d: imports %s directly – use 'from qgis.PyQt import …'" % (path, line, mod))
    if not found:
        print("OK: no direct PyQt5/PyQt6/PySide imports")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
