# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""Translations: English source strings, Danish in i18n/geodrafter_stream_survey_da.qm."""

import os

from qgis.PyQt.QtCore import QCoreApplication, QLocale, QSettings, QTranslator

CONTEXT = "GeoDrafterStreamSurvey"
_translator = None


def tr(text):
    return QCoreApplication.translate(CONTEXT, text)


def user_locale():
    loc = QSettings().value("locale/userLocale", "") or QLocale.system().name()
    return str(loc)[:2].lower()


def install(plugin_dir, locale=None):
    """Load the translation for QGIS' language (if there is one). Returns the language code or None."""
    global _translator
    lang = (locale or user_locale())[:2].lower()
    path = os.path.join(plugin_dir, "i18n", "geodrafter_stream_survey_%s.qm" % lang)
    if not os.path.exists(path):
        return None
    t = QTranslator()
    if not t.load(path):
        return None
    remove()
    QCoreApplication.installTranslator(t)
    _translator = t
    return lang


def remove():
    global _translator
    if _translator is not None:
        QCoreApplication.removeTranslator(_translator)
        _translator = None
