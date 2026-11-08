"""Hatch patterns for the symbol and instrument columns.

Patterns are drawing categories used by the original generator. They are not
a soil classification, and they do not assert compliance with any standard.
An explicit soil_type overrides a guess from the description.
"""
from __future__ import annotations

import math

from reportlab.lib.units import mm

def fill_pattern(c, x, y, w, h, kind):
    if w <= 0 or h <= 0:
        return
    c.saveState()
    p = c.beginPath()
    p.moveTo(x, y); p.lineTo(x+w, y); p.lineTo(x+w, y+h); p.lineTo(x, y+h); p.close()
    c.clipPath(p, stroke=0, fill=0)
    c.setLineWidth(0.3)
    c.setStrokeColorRGB(0, 0, 0)
    if kind == 'clay':
        step_y = 1.5 * mm
        seg = 2.0 * mm
        gap = 2.0 * mm
        i = 0
        while i * step_y <= h + step_y:
            yy = y + i * step_y
            xoff = (seg + gap) / 2 if i % 2 else 0
            j = 0
            while x + xoff + j * (seg + gap) <= x + w:
                xx = x + xoff + j * (seg + gap)
                c.line(xx, yy, xx + seg, yy)
                j += 1
            i += 1
    elif kind == 'sand':
        step = 1.0 * mm
        c.setFillColorRGB(0, 0, 0)
        i = 0
        while i * step <= h:
            j = 0
            while j * step <= w:
                xoff = step/2 if i % 2 else 0
                c.circle(x + j*step + xoff, y + i*step, 0.15*mm, stroke=0, fill=1)
                j += 1
            i += 1
    elif kind == 'gravel':
        step = 2.2 * mm
        r = 0.55 * mm
        i = 0
        while i * step <= h + step:
            j = 0
            while j * step <= w + step:
                xoff = step/2 if i % 2 else 0
                c.circle(x + j*step + xoff, y + i*step, r, stroke=1, fill=0)
                j += 1
            i += 1
    elif kind == 'asphalt':
        c.setFillColorRGB(0, 0, 0)
        c.rect(x, y, w, h, stroke=0, fill=1)
    elif kind == 'backfill':
        cell = 2.5 * mm
        line_step = 0.6 * mm
        cols = int(math.ceil(w / cell))
        rows = int(math.ceil(h / cell))
        for i in range(rows):
            for j in range(cols):
                cx = x + j*cell
                cy = y + i*cell
                cw = min(cell, x + w - cx)
                ch = min(cell, y + h - cy)
                c.saveState()
                pp = c.beginPath()
                pp.moveTo(cx, cy); pp.lineTo(cx+cw, cy); pp.lineTo(cx+cw, cy+ch); pp.lineTo(cx, cy+ch); pp.close()
                c.clipPath(pp, stroke=0, fill=0)
                pos = (i + j) % 2 == 0
                n = int(cell / line_step) + 2
                for k in range(-n, n+1):
                    off = k * line_step
                    if pos:
                        c.line(cx + off,        cy,        cx + off + cell, cy + cell)
                    else:
                        c.line(cx + off,        cy + cell, cx + off + cell, cy)
                c.restoreState()
    c.restoreState()
    c.setLineWidth(0.5)
    c.rect(x, y, w, h, stroke=1, fill=0)

SOIL_PATTERNS = [
    ('Clay',     'clay'),
    ('Sand',     'sand'),
    ('Gravel',   'gravel'),
    ('Asphalt',  'asphalt'),
    ('Backfill', 'backfill'),
]

SOIL_TYPE_TO_PATTERN = {
    'ASPHALT':  'asphalt',
    'CLAY':     'clay',
    'GRAVEL':   'gravel',
    'SAND':     'sand',
    'BACKFILL': 'backfill',
}


def hatch_for_layer(soil_type, desc):
    """Explicit soil_type wins. Otherwise guess from the description text."""
    return soil_type_to_pattern(soil_type) or desc_to_pattern(desc)


def soil_type_to_pattern(soil_type):
    if not soil_type:
        return None
    return SOIL_TYPE_TO_PATTERN.get(str(soil_type).upper().strip())


def desc_to_pattern(desc):
    d = (desc or '').upper()
    if 'ASPHALT' in d: return 'asphalt'
    if 'CLAY'    in d: return 'clay'
    if 'GRAVEL'  in d: return 'gravel'
    if 'SAND'    in d: return 'sand'
    return None

