# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Collect a plugin's translatable strings into its Qt .ts file and compile the .qm.

    python tools/update_ts.py geodrafter_stream_survey da

Strings are the literal arguments of ``tr("…")`` calls plus the string
constants in module-level ``*_TITLES``, ``READERS``, ``GROUPING`` tuples/dicts
(labels passed to ``tr`` later). Existing translations are kept; new strings
are added as unfinished. ``lrelease`` (Qt Linguist tools) compiles the .qm.
``missing(plugin, lang)`` lists strings without a translation (used by the tests).
"""

import ast
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEXT = {"geodrafter_stream_survey": "GeoDrafterStreamSurvey"}
LABEL_NAMES = ("STEP_TITLES", "READERS", "GROUPING", "LAYER_TITLES", "SOURCE_LABELS", "COLUMN_TITLES",
               "CONFIDENCE_LABELS", "TYPE_LABELS", "STRUCTURE_COLUMNS", "LONG_LABELS", "EXPORTS")


def _strings_in(node):
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def collect(plugin):
    base = os.path.join(ROOT, "plugins", plugin)
    found = []
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ("tests", "core", "__pycache__", "geodrafter_common")]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            tree = ast.parse(open(path, encoding="utf-8").read(), path)
            for n in ast.walk(tree):
                fname = getattr(n.func, "id", getattr(n.func, "attr", "")) if isinstance(n, ast.Call) else ""
                if fname == "tr" and n.args and isinstance(n.args[0], ast.Constant) \
                        and isinstance(n.args[0].value, str):
                    found.append(n.args[0].value)
                elif fname == "_run_button" and len(n.args) > 1 and isinstance(n.args[1], ast.Constant):
                    found.append(n.args[1].value)
                elif isinstance(n, ast.Assign) and any(getattr(t, "id", "") in LABEL_NAMES
                                                       for t in n.targets):
                    names = [getattr(t, "id", "") for t in n.targets]
                    vals = _strings_in(n.value)
                    if "READERS" in names or "GROUPING" in names or "EXPORTS" in names:
                        vals = vals[1::2]          # (key, label) pairs: only the labels
                    if isinstance(n.value, ast.Dict):
                        vals = [v.value for v in n.value.values if isinstance(v, ast.Constant)]
                    found.extend(vals)
    seen, out = set(), []
    for s in found:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def ts_path(plugin, lang):
    return os.path.join(ROOT, "plugins", plugin, "i18n", "%s_%s.ts" % (plugin, lang))


def read_ts(path):
    if not os.path.exists(path):
        return {}
    tree = ET.parse(path)
    out = {}
    for m in tree.iter("message"):
        src = m.findtext("source") or ""
        t = m.find("translation")
        if t is not None and t.text and t.get("type") not in ("unfinished", "obsolete", "vanished"):
            out[src] = t.text
    return out


def write_ts(plugin, lang, strings, translations):
    path = ts_path(plugin, lang)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ts = ET.Element("TS", version="2.1", language={"da": "da_DK"}.get(lang, lang))
    ctx = ET.SubElement(ts, "context")
    ET.SubElement(ctx, "name").text = CONTEXT.get(plugin, plugin)
    for s in strings:
        m = ET.SubElement(ctx, "message")
        ET.SubElement(m, "source").text = s
        t = ET.SubElement(m, "translation")
        if s in translations:
            t.text = translations[s]
        else:
            t.set("type", "unfinished")
    ET.indent(ts)
    with open(path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n')
        f.write(ET.tostring(ts, encoding="utf-8"))
        f.write(b"\n")
    return path


def missing(plugin, lang):
    have = read_ts(ts_path(plugin, lang))
    return [s for s in collect(plugin) if s not in have]


def main(argv):
    plugin, lang = argv[1], argv[2] if len(argv) > 2 else "da"
    strings = collect(plugin)
    path = write_ts(plugin, lang, strings, read_ts(ts_path(plugin, lang)))
    left = missing(plugin, lang)
    print("%s: %d strings, %d without translation" % (os.path.relpath(path, ROOT), len(strings), len(left)))
    for s in left:
        print("  - %r" % s)
    lrelease = shutil.which("lrelease") or shutil.which("lrelease-qt6") or shutil.which("lrelease-qt5")
    if lrelease:
        subprocess.check_call([lrelease, "-silent", path, "-qm", path[:-3] + ".qm"])
    else:
        print("lrelease not found – .qm not compiled")
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
