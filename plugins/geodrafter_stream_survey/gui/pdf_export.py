# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Henrik Rosenskjold (GISkon)
"""PDF profile sheets: one cross-section per page with its point table and the source of every point."""

import datetime

from qgis.PyQt.QtCore import QMarginsF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from .i18n import tr
from .profile_view import SOURCE_LABELS, LongProfileCanvas, ProfileCanvas

RES = 96   # draw in screen-like units


def write_sheets(path, sections, title="", water_of=None, transition=0.0, long_rows=None):
    """Write a PDF with one page per section (and a long profile page first when ``long_rows``).

    sections: core.export.SectionData list; water_of(pid) -> (z, left, right) or None.
    Returns the number of pages."""
    w = QPdfWriter(path)
    w.setResolution(RES)
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Landscape,
                                QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter))
    w.setTitle(title or "GeoDrafter Stream Survey")
    w.setCreator("GeoDrafter Stream Survey")
    p = QPainter(w)
    page = w.pageLayout().paintRectPixels(RES)
    width, height = page.width(), page.height()
    today = datetime.date.today().isoformat()
    pages = 0

    def header(text):
        p.setPen(QColor("#1f2933"))
        f = QFont(p.font())
        f.setPointSizeF(13)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, width, 24), Qt.AlignmentFlag.AlignLeft, text)
        f.setPointSizeF(8)
        f.setBold(False)
        p.setFont(f)
        p.drawText(QRectF(0, 0, width, 24), Qt.AlignmentFlag.AlignRight, "%s · %s" % (title, today))

    if long_rows:
        header(tr("Long profile"))
        lc = LongProfileCanvas()
        lc.set_rows(long_rows)
        lc.render_to(p, QRectF(0, 30, width, height - 40))
        pages += 1
    canvas = ProfileCanvas()
    for s in sorted(sections, key=lambda s: s.station):
        if pages:
            w.newPage()
        header(tr("Cross-section %s – station %.2f") % (s.id, s.station))
        canvas.set_data(s.points, water_of(s.id) if water_of else None, transition)
        canvas.render_to(p, QRectF(0, 30, width, height * 0.55))
        # point table
        f = QFont(p.font())
        f.setPointSizeF(7)
        p.setFont(f)
        cols = (tr("Offset"), tr("Elevation"), tr("Name"), tr("Code"), tr("Type"), tr("Source"),
                tr("Terrain model"))
        cw = [60, 60, 80, 50, 90, 90, 200]
        y = 30 + height * 0.55 + 10
        x = 0
        p.setPen(QPen(QColor("#1f2933")))
        for c, wd in zip(cols, cw):
            p.drawText(QRectF(x, y, wd, 12), Qt.AlignmentFlag.AlignLeft, c)
            x += wd
        y += 13
        # every point on the page: rows shrink when a section has many points
        line_h = min(11.0, (height - y) / max(len(s.points), 1))
        if line_h < 11:
            f.setPointSizeF(max(line_h * 0.62, 3.5))
            p.setFont(f)
        for e in s.points:
            pt = e.point
            vals = ("%.2f" % e.offset, "" if e.z is None else "%.3f" % e.z, pt.name if pt else "",
                    pt.code if pt else "", e.point_type, tr(SOURCE_LABELS.get(e.source, e.source)),
                    e.dhm_version)
            x = 0
            for v, wd in zip(vals, cw):
                p.drawText(QRectF(x, y, wd, line_h), Qt.AlignmentFlag.AlignLeft, v)
                x += wd
            y += line_h
        pages += 1
    p.end()
    return pages
