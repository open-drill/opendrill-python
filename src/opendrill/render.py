"""Draw a soil log PDF from a normalised payload.

The page frame is the original DXF template. Depth windows are half-open on
the left, ``(page_start, page_end]``, so a point on a shared boundary is
drawn once, on the page that ends there. 0 m stays on the first page.

The horizontal plot uses two scales on the same line, as the template did:
Su is 0–200 kPa, while SPT N and the percent series (moisture, plastic
limit, liquid limit, fines) use 0–100. SPT N is ``spt2 + spt3`` and is not
N60. ``su_kPa`` is drawn as given. See ``opendrill.validate`` for when Su is
derived as half of ``uc_kPa`` or ``ppen_kPa``.

Values outside an axis are drawn on the edge and named in ``RenderResult.warnings``.
They are not dropped. Description and note lines that would cross the footer
continue on later sheets. Those extra sheets do not invent deeper metre labels.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from opendrill.errors import PayloadError
from opendrill.geometry import (
    BBOX,
    DEPTH_LINES,
    HELPER_DEPTH_EL,
    HELPER_MATERIAL,
    HELPER_TITLE,
    HELPER_TYPE_TEST_RANGES,
    LINES,
    POLYS,
    SU_LINES,
    TEXT_ITEMS,
    WATER_LEVEL_TEMPLATE,
    WP_LINES,
)
from opendrill.layout import (
    MAX_PAGE_LINES,
    MAX_PAGES,
    contains_point,
    clip_interval,
    data_page_windows,
    depth_axis,
    depth_marks,
    format_depth,
    grid_depth_step_m,
    log_extent_m,
    overlaps_interval,
)
from opendrill.patterns import fill_pattern, hatch_for_layer
from opendrill.series import plotted_series, spt_blow_label, spt_n_value
from opendrill.validate import validate_log

TEXT_SCALE = 1.4
DEFAULT_DEPTH_PER_SHEET = 20.0

SU_MIN = 0.0
SU_MAX = 200.0
SU_LABEL_OFFSET = 20
SU_STEP = 40
SU_MINOR_STEP = 20
PERCENT_MIN = 0.0
PERCENT_MAX = 100.0
SPT_MIN = 0.0
SPT_MAX = 100.0

TICK_MAJOR_MM = 3.0
TICK_MINOR_MM = 1.5
LABEL_FONT_PT = 7
LABEL_GAP_MM = 1.0
TICK_MAJOR_MM_SU = 1.0
TICK_MINOR_MM_SU = 1.0
SU_LABEL_FONT_PT = 7
SU_LABEL_GAP_MM = 1.0
GRID_LINE_WIDTH = 0.2

COL_RECOVERY_X = 485.34
COL_TEST_L, COL_TEST_R = HELPER_TYPE_TEST_RANGES[0]
COL_TEST_X = (COL_TEST_L + COL_TEST_R) / 2.0
COL_SAMPLE_L = 501.13
COL_SAMPLE_R = 511.70
SAMPLE_TEXT_H = 2.5
COL_INST_L = 601.08
COL_INST_R = 611.60
COL_PIEZO_L = 604.76
COL_PIEZO_R = 607.77
COL_SYMBOL_L = 511.70
COL_SYMBOL_R = 522.16
WL_TEMPLATE_APEX_Y = 440.69

FIELD_SYMBOL_FILLED = "diamond_f"
FIELD_SYMBOL_EMPTY = "diamond_e"
LAB_SYMBOL_FILLED = "square_f"
LAB_SYMBOL_EMPTY = "square_e"
UC_SYMBOL = "tri_f"
PPEN_SYMBOL = "tri_e"

SU_KIND_GLYPH = {
    "field_peak": FIELD_SYMBOL_FILLED,
    "field_remold": FIELD_SYMBOL_EMPTY,
    "lab_peak": LAB_SYMBOL_FILLED,
    "lab_remold": LAB_SYMBOL_EMPTY,
    "uc": UC_SYMBOL,
    "ppen": PPEN_SYMBOL,
}

_XMIN, _YMIN, _XMAX, _YMAX = BBOX
_W = _XMAX - _XMIN
_H = _YMAX - _YMIN
_MARGIN = 10 * mm
_SCALE = min((210 * mm - 2 * _MARGIN) / _W, (297 * mm - 2 * _MARGIN) / _H)
_PAGE_W = _W * _SCALE + 2 * _MARGIN
_PAGE_H = _H * _SCALE + 2 * _MARGIN

_DESC_FS = 7
_LINE_H = _DESC_FS * 1.15
_PAD_X = 1.5
_PAD_Y = 1.5


@dataclass(frozen=True)
class RenderResult:
    """PDF bytes, warnings, and the number of pages including notes-only sheets."""

    pdf_bytes: bytes
    warnings: tuple[str, ...]
    page_count: int


@dataclass
class PageText:
    texts: list[tuple] = field(default_factory=list)
    lines: list[tuple] = field(default_factory=list)
    overflow: list[tuple[str, str]] = field(default_factory=list)
    notes_remaining: list[str] = field(default_factory=list)
    notes_drawn: int = 0
    warnings: list[str] = field(default_factory=list)


def build_pdf(payload: dict, text_scale: float | None = None) -> bytes:
    """Render ``payload`` to PDF bytes. Raises :class:`PayloadError` when it is invalid."""
    return render_log(payload, text_scale=text_scale).pdf_bytes


def render_log(payload: dict, text_scale: float | None = None) -> RenderResult:
    """Validate, draw, and return the PDF together with overflow and data warnings."""
    validation = validate_log(payload)
    payload = validation.payload
    warnings = list(validation.warnings)
    if text_scale is None:
        text_scale = TEXT_SCALE
    else:
        try:
            text_scale = float(text_scale)
        except (TypeError, ValueError) as exc:
            raise PayloadError([(("text_scale",), "must be a finite number > 0", text_scale)]) from exc
        if not math.isfinite(text_scale) or text_scale <= 0:
            raise PayloadError([(("text_scale",), "must be a finite number > 0", text_scale)])

    frame = _frame()
    dps = float(payload["depth_per_sheet_m"])
    windows = data_page_windows(log_extent_m(payload), dps)
    note_lines = _wrap_paragraphs(payload.get("notes") or "", frame.col_w - 2 * _PAD_X)
    start = _note_start_index(payload, windows)
    pages: list[PageText] = []
    remaining = note_lines
    for index, window in enumerate(windows):
        if remaining and index == start:
            mode = "start"
        elif remaining and index > start:
            mode = "continue"
        else:
            mode = "off"
        laid = _layout_page_text(payload, window, frame, mode, remaining)
        if mode != "off":
            remaining = laid.notes_remaining
        warnings.extend(laid.warnings)
        pages.append(laid)
    stream = _continuation_items(
        [item for page in pages for item in page.overflow],
        remaining,
        notes_started=any(page.notes_drawn for page in pages),
    )
    capacity = _column_capacity(frame)
    if stream and capacity < 1:
        raise PayloadError([((), "the materials column has no room for continued text", None)])
    continued: list[list[tuple[str, str]]] = []
    rest = stream
    while rest:
        if len(windows) + len(continued) + 1 > MAX_PAGES:
            raise PayloadError([(
                (),
                f"notes and descriptions need more than {MAX_PAGES} pages; shorten the text",
                None,
            )])
        continued.append(rest[:capacity])
        rest = rest[capacity:]
    if continued:
        desc_n = sum(len(page.overflow) for page in pages)
        if desc_n:
            warnings.append(
                f"description text continued on a later sheet ({desc_n} lines) "
                "so it would not cover the footer"
            )
        if remaining:
            warnings.append(
                f"notes continued on a later sheet ({len(remaining)} lines)"
            )

    total = len(windows) + len(continued)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(_PAGE_W, _PAGE_H))
    title = _display(payload.get("info", {}).get("LOG TITLE")) or "TEST HOLE LOG"
    pdf.setCreator("opendrill")
    pdf.setAuthor("opendrill")
    pdf.setTitle(title)
    for index, (window, laid) in enumerate(zip(windows, pages)):
        _draw_page(
            pdf, payload, frame, window, laid, index, total, text_scale, warnings,
        )
        pdf.showPage()
    for offset, items in enumerate(continued):
        _draw_continuation(
            pdf, payload, frame, items, len(windows) + offset, total, text_scale, warnings,
        )
        pdf.showPage()
    pdf.save()
    unique: list[str] = []
    for warning in warnings:
        if warning not in unique:
            unique.append(warning)
    return RenderResult(buffer.getvalue(), tuple(unique), total)


@dataclass(frozen=True)
class Frame:
    gy_top: float
    gy_bot: float
    mx_l: float
    mx_r: float
    col_w: float
    del_x_r: float
    gx_l: float
    gx_r: float
    depth_x_l: float
    depth_x_r: float
    dxf_top: float
    dxf_bot: float


def _tx(x: float) -> float:
    return _MARGIN + (x - _XMIN) * _SCALE


def _ty(y: float) -> float:
    return _MARGIN + (y - _YMIN) * _SCALE


def _frame() -> Frame:
    (dx1, dy1), (dx2, dy2) = DEPTH_LINES[0][0], DEPTH_LINES[0][-1]
    if dy1 < dy2:
        (dx1, dy1), (dx2, dy2) = (dx2, dy2), (dx1, dy1)
    gy_top = _ty(dy1)
    gy_bot = _ty(dy2)
    (sx1, _sy1), (sx2, _sy2) = SU_LINES[0][0], SU_LINES[0][-1]
    if sx1 > sx2:
        sx1, sx2 = sx2, sx1
    mx_l, mx_r = _tx(HELPER_MATERIAL[0]), _tx(HELPER_MATERIAL[1])
    return Frame(
        gy_top=gy_top,
        gy_bot=gy_bot,
        mx_l=mx_l,
        mx_r=mx_r,
        col_w=mx_r - mx_l,
        del_x_r=_tx(HELPER_DEPTH_EL[1]),
        gx_l=_tx(sx1),
        gx_r=_tx(sx2),
        depth_x_l=_tx(HELPER_DEPTH_EL[0]),
        depth_x_r=_tx(HELPER_DEPTH_EL[1]),
        dxf_top=dy1,
        dxf_bot=dy2,
    )


def _display(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return ""
        if number.is_integer():
            return str(int(round(number)))
        return f"{number:g}"
    return str(value).strip()


def _filled(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _format_coordinates(info: dict) -> str:
    north = info.get("COORDINATES (M) N", "")
    east = info.get("COORDINATES (M) E", "")
    parts: list[str] = []
    if _filled(north) or _filled(east):
        parts.append(f"N {_display(north)}    E {_display(east)}".strip())
    crs = str(info.get("CRS") or "").strip()
    horizontal = str(info.get("HORIZONTAL DATUM") or "").strip()
    vertical = str(info.get("VERTICAL DATUM") or "").strip()
    if crs:
        parts.append(crs)
    # Compact, because this row is a single template cell. Empty fields are skipped.
    datums = [item for item in (horizontal, vertical) if item]
    if datums:
        parts.append("/".join(datums))
    return "  ".join(parts)


def _wrap_text(text: str, max_w: float, font: str = "Helvetica", size: float = _DESC_FS) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in _split_long_words(words, max_w, font, size):
        trial = word if not current else f"{current} {word}"
        if pdfmetrics.stringWidth(trial, font, size) <= max_w:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _split_long_words(words: list[str], max_w: float, font: str, size: float) -> list[str]:
    """Break any word wider than ``max_w`` into pieces that fit, character by character."""
    out: list[str] = []
    for word in words:
        if pdfmetrics.stringWidth(word, font, size) <= max_w:
            out.append(word)
            continue
        piece = ""
        for char in word:
            if piece and pdfmetrics.stringWidth(piece + char, font, size) > max_w:
                out.append(piece)
                piece = char
            else:
                piece += char
        if piece:
            out.append(piece)
    return out


def _wrap_paragraphs(text: str, max_w: float) -> list[str]:
    lines: list[str] = []
    for para in str(text).split("\n"):
        lines.extend(_wrap_text(para.strip(), max_w))
    return lines


def _note_start_index(payload: dict, windows: list[tuple[float, float]]) -> int:
    """Page where notes start: under the last layer, or under a deeper supplied termination."""
    ends = [
        layer["depth_end_m"]
        for layer in payload.get("layers") or []
        if layer.get("depth_end_m") is not None
    ]
    termination = payload.get("termination_depth_m")
    if termination is not None:
        ends.append(float(termination))
    if not ends:
        return 0
    last = max(ends)
    for index, (start, end) in enumerate(windows):
        if contains_point(last, start, end):
            return index
    return max(0, len(windows) - 1)


def _y_of(depth: float, window: tuple[float, float], frame: Frame) -> float:
    start, end = window
    span = end - start
    return frame.gy_top - (depth - start) / span * (frame.gy_top - frame.gy_bot)


def _layout_page_text(payload, window, frame: Frame, notes_mode: str, note_lines: list[str]) -> PageText:
    page = PageText()
    start, end = window
    max_w = frame.col_w - 2 * _PAD_X
    visible = []
    for layer in payload.get("layers") or []:
        if layer.get("depth_start_m") is None or layer.get("depth_end_m") is None:
            continue
        if overlaps_interval(layer["depth_start_m"], layer["depth_end_m"], start, end):
            visible.append(layer)
    last_bot = None
    for layer in visible:
        clipped = clip_interval(layer["depth_start_m"], layer["depth_end_m"], start, end)
        if clipped is None:
            continue
        y = _y_of(clipped[1], window, frame)
        if last_bot is None or y < last_bot:
            last_bot = y
    last_baseline = None
    rendered = []
    for layer in sorted(visible, key=lambda row: row["depth_start_m"]):
        desc = (layer.get("desc") or "").strip()
        if not desc:
            continue
        clipped = clip_interval(layer["depth_start_m"], layer["depth_end_m"], start, end)
        if clipped is None:
            continue
        y_top = _y_of(clipped[0], window, frame)
        y_bot = _y_of(clipped[1], window, frame)
        nominal = y_top - _PAD_Y - _DESC_FS
        gap = 3.0
        first = nominal if last_baseline is None else min(nominal, last_baseline - _LINE_H - gap)
        lines = _wrap_text(desc, max_w)
        y = first
        kept: list[float] = []
        heading = f"{layer['depth_start_m']:g}–{layer['depth_end_m']:g} m"
        ends_here = contains_point(layer["depth_end_m"], start, end)
        skipped = 0
        for line in lines:
            if y < frame.gy_bot:
                skipped += 1
                if ends_here:
                    page.overflow.append((heading, line))
            else:
                page.texts.append((frame.mx_l + _PAD_X, y, line, "Helvetica", _DESC_FS))
                kept.append(y)
            y -= _LINE_H
        if skipped and not ends_here:
            page.warnings.append(
                f"description for layer {heading} was clipped at the footer on this sheet; "
                "the layer continues on the next sheet, where the description starts again, "
                "and the overflow was not drawn over the footer"
            )
        if kept:
            last_baseline = kept[-1]
            rendered.append({
                "first": kept[0],
                "last": kept[-1],
                "y_bot": y_bot,
            })
            text_top = kept[0] + _DESC_FS
            if text_top < y_bot - 0.5:
                page.lines.append((frame.mx_r, y_bot, frame.mx_l, text_top, 0.3))
    for index in range(len(rendered) - 1):
        above = rendered[index]
        below = rendered[index + 1]
        physical = above["y_bot"]
        if above["last"] - _DESC_FS * 0.3 < physical:
            line_y = (above["last"] + below["first"] + _DESC_FS) / 2.0
        else:
            line_y = physical
        if line_y >= frame.gy_bot:
            page.lines.append((frame.mx_l, line_y, frame.mx_r, line_y, 0.4))
        if abs(physical - line_y) > 0.5 and line_y >= frame.gy_bot and physical >= frame.gy_bot:
            page.lines.append((frame.del_x_r, physical, frame.mx_l, line_y, 0.4))
    closing = last_bot
    if closing is None and rendered:
        closing = rendered[-1]["y_bot"]
    if closing is not None and closing >= frame.gy_bot:
        page.lines.append((frame.mx_l, closing, frame.mx_r, closing, 0.4))

    # Text placed after the layers (termination caption, notes) must start
    # below the layer boundary and below the last description line drawn on
    # this page, which can run past a thin layer's physical bottom.
    notes_anchor = closing
    if last_baseline is not None:
        text_floor = last_baseline - _DESC_FS * 0.3
        notes_anchor = text_floor if notes_anchor is None else min(notes_anchor, text_floor)
    termination = payload.get("termination_depth_m")
    if termination is not None and contains_point(float(termination), start, end):
        term_y = _y_of(float(termination), window, frame)
        layer_ends = [layer["depth_end_m"] for layer in visible]
        already = any(abs(depth - float(termination)) <= 1e-6 for depth in layer_ends)
        if not already:
            caption = f"Termination depth (supplied) {format_depth(float(termination))} m"
            baseline = term_y - _PAD_Y - _DESC_FS
            if last_baseline is not None:
                baseline = min(baseline, last_baseline - _LINE_H)
            if baseline >= frame.gy_bot:
                page.texts.append((frame.mx_l + _PAD_X, baseline, caption, "Helvetica-Oblique", _DESC_FS))
                notes_anchor = baseline
            else:
                page.overflow.append(("termination", caption))
                notes_anchor = frame.gy_bot
    if notes_mode == "off" or not note_lines:
        return page
    if notes_mode == "start":
        y = (notes_anchor if notes_anchor is not None else frame.gy_top) - _PAD_Y - _DESC_FS
        sequence = [("Helvetica-Bold", "Notes:")] + [("Helvetica", line) for line in note_lines]
    else:
        y = frame.gy_top - _PAD_Y - _DESC_FS
        sequence = [("Helvetica-Bold", "Notes (continued):")] + [("Helvetica", line) for line in note_lines]
    overflowed = False
    body_started = False
    for font, line in sequence:
        if y < frame.gy_bot:
            overflowed = True
        if overflowed:
            if font != "Helvetica-Bold":
                page.notes_remaining.append(line)
                body_started = True
            elif body_started:
                page.notes_remaining.append(line)
        else:
            page.texts.append((frame.mx_l + _PAD_X, y, line, font, _DESC_FS))
            page.notes_drawn += 1
        y -= _LINE_H
    return page


def _continuation_items(overflow: list[tuple[str, str]], notes: list[str], notes_started: bool) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if overflow:
        items.append(("Helvetica-Bold", "Descriptions continued"))
        last = None
        for heading, line in overflow:
            if heading != last:
                items.append(("Helvetica-Bold", heading))
                last = heading
            items.append(("Helvetica", line))
    if notes:
        items.append(("Helvetica-Bold", "Notes (continued):" if notes_started else "Notes:"))
        items.extend(("Helvetica", line) for line in notes)
    return items


def _column_capacity(frame: Frame) -> int:
    y = frame.gy_top - _PAD_Y - _DESC_FS
    count = 0
    while y >= frame.gy_bot:
        count += 1
        y -= _LINE_H
    return count


def _fit(text: str, font: str, size: float, max_width: float) -> tuple[str, float, bool]:
    if max_width <= 1:
        return "", size, True
    if pdfmetrics.stringWidth(text, font, size) <= max_width:
        return text, size, False
    for scale in (0.9, 0.8, 0.7):
        shrunk = size * scale
        if pdfmetrics.stringWidth(text, font, shrunk) <= max_width:
            return text, shrunk, False
    shrunk = size * 0.7
    kept = text
    while kept and pdfmetrics.stringWidth(kept + "…", font, shrunk) > max_width:
        kept = kept[:-1]
    if not kept:
        return "", shrunk, True
    return kept + "…", shrunk, True


def _value_rows(info: dict) -> list[tuple]:
    return [
        (524.7, 492.6, "STARTED:", _display(info.get("STARTED", "")), 2.0, 560.0, "STARTED"),
        (563.1, 492.6, "FINISHED:", _display(info.get("FINISHED", "")), 2.0, 600.0, "FINISHED"),
        (524.6, 487.3, "DRILL METHOD:", _display(info.get("DRILL METHOD", "")), 2.0, 600.0, "DRILL METHOD"),
        (524.5, 482.3, "GROUND ELEV. (m):", _display(info.get("GROUND ELEV. (M)", "")), 2.0, 600.0, "GROUND ELEV. (M)"),
        (524.4, 477.1, "COORDINATES (m):", _format_coordinates(info), 2.0, 600.0, "COORDINATES"),
        (571.5, 255.6, "PROJECT NO.:", _display(info.get("PROJECT NO", "")), 2.5, 662.0, "PROJECT NO"),
        (571.5, 249.4, "PROJECT:", _display(info.get("PROJECT", "")), 2.5, 662.0, "PROJECT"),
        (571.5, 243.0, "LOCATION:", _display(info.get("LOCATION", "")), 2.5, 662.0, "LOCATION"),
        (571.5, 236.8, "LOGGED BY:", _display(info.get("LOGGED BY", "")), 2.5, 612.0, "LOGGED BY"),
        (614.9, 236.6, "CHECKED BY:", _display(info.get("CHECKED BY", "")), 2.5, 662.0, "CHECKED BY"),
        (614.7, 230.6, "HOLE NO.:", _display(info.get("HOLE NO", "")), 2.5, 662.0, "HOLE NO"),
    ]


# Footer anchors from the DXF template. HOLE NO starts at the right of this row.
_SHEET_LABEL_X = 571.4521834622282
_SHEET_LABEL_Y = 230.4971206403984
_OF_LABEL_X = 588.5801078202355
_OF_LABEL_Y = 230.5492246479097
_HOLE_NO_X = 614.7347929347716


@dataclass(frozen=True)
class PlacedText:
    """One footer token in page points."""

    text: str
    x: float
    y: float
    font: str
    size: float


def sheet_line_layout(sheet_num: int, sheet_total: int, text_scale: float = TEXT_SCALE) -> list[PlacedText]:
    """Place ``SHEET n OF total`` so both numbers stay visible.

    The template gap after SHEET only fits a single digit. Two- and three-digit
    sheet numbers (10 through the 200-page limit) shift ``OF`` right, and the
    run still ends before the HOLE NO label. One-digit numbers keep the
    template's OF position.
    """
    full = 2.5 * _SCALE * text_scale
    gap = 3.0
    x_sheet = _tx(_SHEET_LABEL_X)
    y_sheet = _ty(_SHEET_LABEL_Y)
    y_of = _ty(_OF_LABEL_Y)
    of_template = _tx(_OF_LABEL_X)
    limit = _tx(_HOLE_NO_X) - 2.0
    number = str(int(sheet_num))
    total = str(int(sheet_total))

    def place(size: float) -> tuple[float, list[PlacedText]]:
        sheet_w = pdfmetrics.stringWidth("SHEET", "Helvetica-Bold", size)
        num_w = pdfmetrics.stringWidth(number, "Helvetica", size)
        of_w = pdfmetrics.stringWidth("OF", "Helvetica-Bold", size)
        tot_w = pdfmetrics.stringWidth(total, "Helvetica", size)
        num_x = x_sheet + sheet_w + gap
        if num_x + num_w + gap > of_template:
            of_x = num_x + num_w + gap
        else:
            of_x = of_template
        tot_x = of_x + of_w + gap
        end = tot_x + tot_w
        tokens = [
            PlacedText("SHEET", x_sheet, y_sheet, "Helvetica-Bold", size),
            PlacedText(number, num_x, y_sheet, "Helvetica", size),
            PlacedText("OF", of_x, y_of, "Helvetica-Bold", size),
            PlacedText(total, tot_x, y_sheet, "Helvetica", size),
        ]
        return end, tokens

    size = full
    end, tokens = place(size)
    while end > limit and size > 4.0:
        size *= 0.9
        end, tokens = place(size)
    return tokens


def spt_label_origin(
    marker_x: float,
    label_width: float,
    plot_left: float,
    plot_right: float,
    radius: float = 1.5,
    gap: float = 1.5,
    edge_pad: float = 6.0,
) -> float:
    """Left edge of an SPT blow-count label, kept inside the plot.

    The label prefers the left of the marker. A low N such as 4/6/8 sits on
    the instrument-column side of the axis, so the label moves to the right
    of the marker instead of crossing or crowding that column.
    """
    left_try = marker_x - radius - gap - label_width
    if left_try >= plot_left + edge_pad:
        return left_try
    right_try = marker_x + radius + gap
    if right_try + label_width <= plot_right:
        return right_try
    return max(plot_left, plot_right - label_width)


def _draw_glyph(pdf, cx: float, cy: float, kind: str, size_pt: float = 4) -> None:
    radius = size_pt / 2.0
    pdf.setLineWidth(0.6)
    if kind == "circle_f":
        pdf.circle(cx, cy, radius, stroke=1, fill=1)
    elif kind == "circle_e":
        pdf.circle(cx, cy, radius, stroke=1, fill=0)
    elif kind in ("tri_f", "triangle_f"):
        path = pdf.beginPath()
        path.moveTo(cx, cy + radius)
        path.lineTo(cx - radius, cy - radius)
        path.lineTo(cx + radius, cy - radius)
        path.close()
        pdf.drawPath(path, stroke=1, fill=1)
    elif kind in ("tri_e", "triangle_e"):
        path = pdf.beginPath()
        path.moveTo(cx, cy + radius)
        path.lineTo(cx - radius, cy - radius)
        path.lineTo(cx + radius, cy - radius)
        path.close()
        pdf.drawPath(path, stroke=1, fill=0)
    elif kind == "diamond_f":
        path = pdf.beginPath()
        path.moveTo(cx, cy + radius)
        path.lineTo(cx + radius, cy)
        path.lineTo(cx, cy - radius)
        path.lineTo(cx - radius, cy)
        path.close()
        pdf.drawPath(path, stroke=1, fill=1)
    elif kind == "diamond_e":
        path = pdf.beginPath()
        path.moveTo(cx, cy + radius)
        path.lineTo(cx + radius, cy)
        path.lineTo(cx, cy - radius)
        path.lineTo(cx - radius, cy)
        path.close()
        pdf.drawPath(path, stroke=1, fill=0)
    elif kind == "square_f":
        pdf.rect(cx - radius, cy - radius, 2 * radius, 2 * radius, stroke=1, fill=1)
    elif kind == "square_e":
        pdf.rect(cx - radius, cy - radius, 2 * radius, 2 * radius, stroke=1, fill=0)
    elif kind == "x":
        pdf.line(cx - radius, cy - radius, cx + radius, cy + radius)
        pdf.line(cx - radius, cy + radius, cx + radius, cy - radius)
    elif kind == "star":
        points = []
        for step in range(10):
            angle = math.pi / 2 + step * math.pi / 5
            arm = radius if step % 2 == 0 else radius * 0.45
            points.append((cx + arm * math.cos(angle), cy + arm * math.sin(angle)))
        path = pdf.beginPath()
        path.moveTo(*points[0])
        for px, py in points[1:]:
            path.lineTo(px, py)
        path.close()
        pdf.drawPath(path, stroke=1, fill=1)


def _draw_runs(pdf, x_pt, y_pt, runs, font, font_size) -> None:
    text = pdf.beginText(x_pt, y_pt)
    rise = 0
    size = font_size
    for chunk, style in runs:
        if style == "sub":
            new_rise, new_size = -font_size * 0.25, font_size * 0.7
        elif style == "sup":
            new_rise, new_size = font_size * 0.4, font_size * 0.7
        else:
            new_rise, new_size = 0, font_size
        if new_rise != rise:
            text.setRise(new_rise)
            rise = new_rise
        if new_size != size:
            text.setFont(font, new_size)
            size = new_size
        text.textOut(chunk)
    if rise != 0:
        text.setRise(0)
    pdf.drawText(text)


def _draw_template_text(pdf, info: dict, text_scale: float, warnings: list[str]) -> None:
    log_title = _display(info.get("LOG TITLE"))
    for item in TEXT_ITEMS:
        font_size = item["h"] * _SCALE * text_scale
        pdf.setFont(item["font"], font_size)
        x_pt, y_pt = _tx(item["x"]), _ty(item["y"])
        joined = "".join(text for text, _style in item["runs"]).strip().upper()
        # SHEET and OF are redrawn with their numbers so sheet 10+ is not clipped.
        if joined in {"SHEET", "OF"}:
            continue
        if joined in ("VANE", "PEAK", "REMOLD"):
            y_pt += 0.15
        runs = item["runs"]
        if joined == "TEST HOLE LOG" and log_title:
            cell_cx = (_tx(HELPER_TITLE[0]) + _tx(HELPER_TITLE[1])) / 2.0
            cell_w = _tx(HELPER_TITLE[1]) - _tx(HELPER_TITLE[0])
            shown, size, truncated = _fit(log_title, item["font"], font_size, cell_w - 4)
            if truncated:
                warnings.append(f"LOG TITLE was truncated to fit the title band: {log_title}")
            new_w = pdf.stringWidth(shown, item["font"], size)
            x_pt = cell_cx - new_w / 2.0
            runs = [(shown, "normal")]
            font_size = size
        if item["rot"]:
            pdf.saveState()
            pdf.translate(x_pt, y_pt)
            pdf.rotate(item["rot"])
            _draw_runs(pdf, 0, 0, runs, item["font"], font_size)
            pdf.restoreState()
        else:
            _draw_runs(pdf, x_pt, y_pt, runs, item["font"], font_size)


def _draw_legend(pdf, text_scale: float) -> None:
    def marker(dxf_x, dxf_y, kind, size_pt=4):
        _draw_glyph(pdf, _tx(dxf_x), _ty(dxf_y), kind, size_pt)

    gap = 1.5

    def left_of(text_x, size_pt):
        return text_x - (size_pt / 2.0 + gap) / _SCALE

    def center_below(text_x, label, font, height_units):
        size = height_units * _SCALE * text_scale
        return text_x + (pdf.stringWidth(label, font, size) / _SCALE) / 2

    field_cx = center_below(627.57, "FIELD", "Helvetica", 2.0)
    lab_cx = center_below(638.87, "LAB", "Helvetica", 2.0)
    marker(field_cx, 491.5, FIELD_SYMBOL_FILLED, 3.5)
    marker(field_cx, 489.0, FIELD_SYMBOL_EMPTY, 3.5)
    marker(lab_cx, 491.6, LAB_SYMBOL_FILLED, 3.5)
    marker(lab_cx, 488.4, LAB_SYMBOL_EMPTY, 3.5)
    shift = text_scale * 0.5
    marker(left_of(651.91, 3.5), 491.6 + shift, UC_SYMBOL, 3.5)
    marker(left_of(651.76, 3.5), 488.4 + shift, PPEN_SYMBOL, 3.5)
    marker(left_of(624.36, 3.5), 484.7 + shift, "star", 3.5)
    marker(left_of(646.84, 3.0), 484.9 + shift, "circle_f", 3.0)
    pdf.setLineWidth(0.4)
    pdf.setDash(2, 2)
    for pts in WP_LINES:
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            pdf.line(_tx(x1), _ty(y1), _tx(x2), _ty(y2))
    pdf.setDash()
    for pts in WP_LINES:
        (x1, y1), (x2, y2) = pts[0], pts[-1]
        marker(x1, y1, "x", 3.5)
        marker(x2, y2, "x", 3.5)
        marker((x1 + x2) / 2, (y1 + y2) / 2, "circle_e", 3.5)


def _draw_chrome(pdf, payload, sheet_index: int, sheet_total: int, text_scale: float, warnings: list[str]) -> None:
    info = payload.get("info", {})
    pdf.setLineWidth(0.5)
    for pts, closed in POLYS:
        path = pdf.beginPath()
        path.moveTo(_tx(pts[0][0]), _ty(pts[0][1]))
        for x, y in pts[1:]:
            path.lineTo(_tx(x), _ty(y))
        if closed:
            path.close()
        pdf.drawPath(path, stroke=1, fill=0)
    for (x1, y1), (x2, y2) in LINES:
        pdf.line(_tx(x1), _ty(y1), _tx(x2), _ty(y2))
    _draw_template_text(pdf, info, text_scale, warnings)
    gap = 3.0
    for x, y, label, text, h_units, max_x, field_name in _value_rows(info):
        if not text:
            continue
        size = h_units * _SCALE * text_scale
        label_w = pdf.stringWidth(label, "Helvetica-Bold", size)
        value_x = _tx(x) + label_w + gap
        max_width = _tx(max_x) - value_x
        shown, used, truncated = _fit(text, "Helvetica", size, max_width)
        if truncated:
            warnings.append(f"{field_name} was truncated to fit the page: {text}")
        pdf.setFont("Helvetica", used)
        pdf.drawString(value_x, _ty(y), shown)
    for token in sheet_line_layout(sheet_index + 1, sheet_total, text_scale):
        pdf.setFont(token.font, token.size)
        pdf.drawString(token.x, token.y, token.text)
    _draw_su_axis(pdf)
    _draw_legend(pdf, text_scale)


def _draw_su_axis(pdf) -> None:
    (x1, y1), (x2, y2) = SU_LINES[0][0], SU_LINES[0][-1]
    if x1 > x2:
        (x1, y1), (x2, y2) = (x2, y2), (x1, y1)
    px_l, py_l = _tx(x1), _ty(y1)
    px_r, py_r = _tx(x2), _ty(y2)
    spine_y = (py_l + py_r) / 2.0
    pdf.setLineWidth(0.4)
    pdf.line(px_l, spine_y, px_r, spine_y)
    span_data = SU_MAX - SU_MIN
    span_pts = px_r - px_l
    label_vals = list(range(int(SU_MIN + SU_LABEL_OFFSET), int(SU_MAX), SU_STEP))
    n_minor = int(span_data // SU_MINOR_STEP)
    pdf.setLineWidth(0.25)
    for step in range(n_minor + 1):
        value = SU_MIN + step * SU_MINOR_STEP
        frac = (value - SU_MIN) / span_data
        x = px_l + frac * span_pts
        tick = (TICK_MAJOR_MM_SU if value in label_vals else TICK_MINOR_MM_SU) * mm
        pdf.line(x, spine_y, x, spine_y - tick)
    pdf.setFont("Helvetica", SU_LABEL_FONT_PT)
    label_y = spine_y - TICK_MAJOR_MM_SU * mm - SU_LABEL_GAP_MM * mm - SU_LABEL_FONT_PT
    for value in label_vals:
        frac = (value - SU_MIN) / span_data
        x = px_l + frac * span_pts
        text = str(value)
        width = pdf.stringWidth(text, "Helvetica", SU_LABEL_FONT_PT)
        pdf.drawString(x - width / 2.0, label_y, text)


def _draw_depth_axis(pdf, frame: Frame, window: tuple[float, float]) -> None:
    start, end = window
    axis = depth_axis(start, end)
    py_top = frame.gy_top
    py_bot = frame.gy_bot
    spine_x = (_tx(DEPTH_LINES[0][0][0]) + _tx(DEPTH_LINES[0][-1][0])) / 2.0
    pdf.setLineWidth(0.4)
    pdf.line(spine_x, py_top, spine_x, py_bot)
    span_pts = py_top - py_bot
    pdf.setLineWidth(0.25)
    for depth, major in axis.ticks():
        frac = (depth - start) / (end - start)
        y = py_top - frac * span_pts
        tick = (TICK_MAJOR_MM if major else TICK_MINOR_MM) * mm
        pdf.line(spine_x, y, spine_x + tick, y)
    pdf.setFont("Helvetica", LABEL_FONT_PT)
    for depth in axis.label_depths_m:
        frac = (depth - start) / (end - start)
        y = py_top - frac * span_pts
        y_text = y - LABEL_FONT_PT * 0.3
        if abs(depth - end) <= 1e-6:
            y_text = y + LABEL_FONT_PT * 0.2
        pdf.drawString(
            spine_x + TICK_MAJOR_MM * mm + LABEL_GAP_MM * mm,
            y_text,
            format_depth(depth),
        )


def _axis_x(value: float, low: float, high: float, x_l: float, x_r: float) -> tuple[float, str]:
    if value < low:
        return x_l, "low"
    if value > high:
        return x_r, "high"
    return x_l + (value - low) / (high - low) * (x_r - x_l), "in"


def _sample_label(test: dict) -> str:
    number = test.get("no")
    if number is None:
        return "sample"
    return f"sample {number}"


def _warn_overflow(warnings: list[str], test: dict, field: str, value: float, unit: str, low: float, high: float) -> None:
    warnings.append(
        f"{_sample_label(test)} {field} {value:g} {unit} is outside the plot axis "
        f"{low:g}–{high:g}; marked at the axis edge"
    )


def _mark_edge(pdf, x: float, y: float, side: str) -> None:
    if side == "in":
        return
    pdf.setFont("Helvetica", 5)
    pdf.drawString(x + (1.2 if side == "high" else -6), y + 1.2, ">" if side == "high" else "<")


def _draw_grid_and_series(pdf, payload, frame: Frame, window, warnings: list[str]) -> None:
    start, end = window
    span = end - start
    grid_depths = depth_marks(start, end, grid_depth_step_m(span))
    pdf.saveState()
    pdf.setStrokeColorRGB(0, 0, 0)
    pdf.setLineWidth(GRID_LINE_WIDTH)
    n_v = int((SU_MAX - SU_MIN) // SU_MINOR_STEP)
    for step in range(n_v + 1):
        x = frame.gx_l + step / n_v * (frame.gx_r - frame.gx_l)
        pdf.line(x, frame.gy_top, x, frame.gy_bot)
    for depth in grid_depths:
        y = frame.gy_top - (depth - start) / span * (frame.gy_top - frame.gy_bot)
        pdf.line(frame.gx_l, y, frame.gx_r, y)
    pdf.restoreState()

    def depth_y(depth: float) -> float | None:
        if not contains_point(depth, start, end):
            return None
        return frame.gy_top - (depth - start) / span * (frame.gy_top - frame.gy_bot)

    for test in payload.get("tests") or []:
        top = test.get("depth_top_m")
        bot = test.get("depth_bot_m")
        if top is None or bot is None:
            continue
        series = plotted_series(test)
        mid = (top + bot) / 2.0
        y = depth_y(mid)
        if y is None:
            continue
        if series["su"]:
            su = float(test["su_kPa"])
            x, side = _axis_x(su, SU_MIN, SU_MAX, frame.gx_l, frame.gx_r)
            if side != "in":
                _warn_overflow(warnings, test, "su_kPa", su, "kPa", SU_MIN, SU_MAX)
            glyph = SU_KIND_GLYPH.get(test.get("su_kind"), "circle_e")
            _draw_glyph(pdf, x, y, glyph, 3.5)
            _mark_edge(pdf, x, y, side)
        if series["spt_n"]:
            n_value = spt_n_value(test)
            if n_value is not None:
                x, side = _axis_x(n_value, SPT_MIN, SPT_MAX, frame.gx_l, frame.gx_r)
                if side != "in":
                    warnings.append(
                        f"{_sample_label(test)} SPT N {n_value:g} (spt2+spt3, not N60) "
                        f"is outside the plot axis {SPT_MIN:g}–{SPT_MAX:g}; marked at the axis edge"
                    )
                radius = 1.5
                pdf.setLineWidth(0.6)
                pdf.circle(x, y, radius, stroke=1, fill=1)
                _mark_edge(pdf, x, y, side)
                pdf.setFont("Helvetica", 6)
                blow_label = spt_blow_label(test)
                label_w = pdf.stringWidth(blow_label, "Helvetica", 6)
                label_x = spt_label_origin(x, label_w, frame.gx_l, frame.gx_r, radius=radius)
                pdf.drawString(label_x, y + 1, blow_label)
        if series["wp"] or series["wl"] or series["w"]:
            radius = 1.75
            pdf.setLineWidth(0.6)
            positions = {}
            for field in ("wp_pct", "wl_pct", "w_pct"):
                if not series[{"wp_pct": "wp", "wl_pct": "wl", "w_pct": "w"}[field]]:
                    continue
                value = float(test[field])
                x, side = _axis_x(value, PERCENT_MIN, PERCENT_MAX, frame.gx_l, frame.gx_r)
                if side != "in":
                    _warn_overflow(warnings, test, field, value, "percent", PERCENT_MIN, PERCENT_MAX)
                positions[field] = (x, side)
            if "wp_pct" in positions and "wl_pct" in positions:
                left = positions["wp_pct"][0]
                right = positions["wl_pct"][0]
                pdf.saveState()
                pdf.setDash(2, 2)
                if right >= left:
                    pdf.line(left + radius, y, right - radius, y)
                else:
                    pdf.line(right + radius, y, left - radius, y)
                pdf.restoreState()
            for field in ("wp_pct", "wl_pct"):
                if field in positions:
                    x, side = positions[field]
                    _draw_glyph(pdf, x, y, "x", 3.5)
                    _mark_edge(pdf, x, y, side)
            if "w_pct" in positions:
                x, side = positions["w_pct"]
                _draw_glyph(pdf, x, y, "circle_e", 3.5)
                _mark_edge(pdf, x, y, side)
        if series["fines"]:
            value = float(test["fines_pct"])
            x, side = _axis_x(value, PERCENT_MIN, PERCENT_MAX, frame.gx_l, frame.gx_r)
            if side != "in":
                _warn_overflow(warnings, test, "fines_pct", value, "percent", PERCENT_MIN, PERCENT_MAX)
            _draw_glyph(pdf, x, y, "star", 3.5)
            _mark_edge(pdf, x, y, side)


def _draw_boundaries(pdf, payload, frame: Frame, window) -> None:
    start, end = window
    ground_raw = payload.get("info", {}).get("GROUND ELEV. (M)", "")
    ground = None
    if _filled(ground_raw) and not isinstance(ground_raw, bool):
        try:
            ground = float(ground_raw)
        except (TypeError, ValueError):
            ground = None
    depths = set()
    for layer in payload.get("layers") or []:
        for value in (layer.get("depth_start_m"), layer.get("depth_end_m")):
            if value is not None and contains_point(float(value), start, end):
                depths.add(float(value))
    termination = payload.get("termination_depth_m")
    if termination is not None and contains_point(float(termination), start, end):
        depths.add(float(termination))
    if not depths:
        return
    ordered = sorted(depths)
    span = end - start
    pt_per_m = (frame.gy_top - frame.gy_bot) / span
    pdf.setLineWidth(0.4)
    pdf.setFont("Helvetica", 6)
    pad = 1.0
    x_mid = (frame.depth_x_l + frame.depth_x_r) / 2.0
    for index, depth in enumerate(ordered):
        y = frame.gy_top - (depth - start) * pt_per_m
        if abs(y - frame.gy_top) > 0.6 and abs(y - frame.gy_bot) > 0.6:
            pdf.line(frame.depth_x_l, y, frame.depth_x_r, y)
        previous = ordered[index - 1] if index else start
        nxt = ordered[index + 1] if index + 1 < len(ordered) else end
        room_above = (depth - previous) * pt_per_m
        room_below = (nxt - depth) * pt_per_m
        label = format_depth(depth)
        if room_above >= 6 + pad:
            width = pdf.stringWidth(label, "Helvetica", 6)
            pdf.drawString(x_mid - width / 2.0, y + pad, label)
        if ground is not None and room_below >= 6 + pad:
            elev = format_depth(ground - depth)
            width = pdf.stringWidth(elev, "Helvetica", 6)
            pdf.drawString(x_mid - width / 2.0, y - 6 - pad + 1, elev)


def _dxf_depth_y(depth: float, window: tuple[float, float], frame: Frame) -> float:
    start, end = window
    return frame.dxf_top - (depth - start) / (end - start) * (frame.dxf_top - frame.dxf_bot)


def _draw_samples(pdf, payload, frame: Frame, window, text_scale: float) -> None:
    start, end = window
    rows = []
    for test in payload.get("tests") or []:
        top = test.get("depth_top_m")
        bot = test.get("depth_bot_m")
        if top is None or bot is None:
            continue
        clipped = clip_interval(float(top), float(bot), start, end)
        if clipped is None:
            continue
        y_top = _ty(_dxf_depth_y(clipped[0], window, frame))
        y_bot = _ty(_dxf_depth_y(clipped[1], window, frame))
        rows.append((test, y_top, y_bot))
    if not rows:
        return
    size = SAMPLE_TEXT_H * _SCALE * text_scale
    pdf.setFont("Helvetica", size)
    pad = size * 0.15
    bands = [(bot, top) for _test, top, bot in rows]

    def collides(y_lo, y_hi, skip):
        for index, (lo, hi) in enumerate(bands):
            if index == skip:
                continue
            if y_hi >= lo and y_lo <= hi:
                return True
        return False

    bx_l = _tx(COL_SAMPLE_L)
    bx_r = _tx(COL_SAMPLE_R)
    for index, (test, y_top, y_bot) in enumerate(rows):
        y_mid = (y_top + y_bot) / 2.0
        y_text = y_mid - size * 0.3
        recovery = test.get("recovery")
        kind = test.get("test")
        number = test.get("no")
        if recovery is not None and recovery != "":
            label = f"{int(round(float(recovery)))} %"
            width = pdf.stringWidth(label, "Helvetica", size)
            pdf.drawString(_tx(COL_RECOVERY_X) - width / 2.0, y_text, label)
        if kind:
            col_w = _tx(COL_TEST_R) - _tx(COL_TEST_L) - 1.0
            shown, used, _truncated = _fit(str(kind), "Helvetica", size, col_w)
            pdf.setFont("Helvetica", used)
            width = pdf.stringWidth(shown, "Helvetica", used)
            pdf.drawString(_tx(COL_TEST_X) - width / 2.0, y_text, shown)
            pdf.setFont("Helvetica", size)
        pdf.setLineWidth(0.5)
        height = y_top - y_bot
        if height > 0.2:
            pdf.rect(bx_l, y_bot, bx_r - bx_l, height, stroke=1, fill=0)
        if number is None or number == "":
            continue
        label = str(int(number) if isinstance(number, float) and float(number).is_integer() else number)
        width = pdf.stringWidth(label, "Helvetica", size)
        x_text = (bx_l + bx_r) / 2.0 - width / 2.0
        if height >= size * 1.1:
            pdf.drawString(x_text, y_text, label)
            continue
        y_above = y_top + pad
        y_below = y_bot - pad - size
        if not collides(y_above - size * 0.2, y_above + size * 0.8, index):
            pdf.drawString(x_text, y_above, label)
        elif not collides(y_below - size * 0.2, y_below + size * 0.8, index):
            pdf.drawString(x_text, y_below, label)
        else:
            pdf.drawString(x_text, y_text, label)


def _draw_piezo(pdf, payload, frame: Frame, window) -> None:
    piezo = payload.get("piezo") or {}
    start, end = window
    bottom = piezo.get("bottom_depth_m")
    if bottom is not None and overlaps_interval(0.0, float(bottom), start, end):
        clipped = clip_interval(0.0, float(bottom), start, end)
        if clipped and clipped[1] > clipped[0]:
            y_top = _ty(_dxf_depth_y(clipped[0], window, frame))
            y_bot = _ty(_dxf_depth_y(clipped[1], window, frame))
            fill_pattern(pdf, _tx(COL_INST_L), y_bot, _tx(COL_INST_R) - _tx(COL_INST_L), y_top - y_bot, "backfill")
    casing = piezo.get("bottom_piezo_m")
    if casing is not None and overlaps_interval(0.0, float(casing), start, end):
        clipped = clip_interval(0.0, float(casing), start, end)
        if clipped and clipped[1] > clipped[0]:
            y_top = _ty(_dxf_depth_y(clipped[0], window, frame))
            y_bot = _ty(_dxf_depth_y(clipped[1], window, frame))
            pdf.saveState()
            pdf.setFillColorRGB(1, 1, 1)
            pdf.setLineWidth(0.4)
            pdf.rect(_tx(COL_PIEZO_L), y_bot, _tx(COL_PIEZO_R) - _tx(COL_PIEZO_L), y_top - y_bot, stroke=1, fill=1)
            pdf.restoreState()
    top = piezo.get("top_screen_m")
    screen_bottom = piezo.get("bottom_screen_m")
    if top is not None and screen_bottom is not None and float(screen_bottom) > float(top):
        clipped = clip_interval(float(top), float(screen_bottom), start, end)
        if clipped and clipped[1] > clipped[0]:
            y_top = _ty(_dxf_depth_y(clipped[0], window, frame))
            y_bot = _ty(_dxf_depth_y(clipped[1], window, frame))
            spacing = piezo.get("screen_line_spacing_m") or 0.1
            n_lines = max(1, int(round((clipped[1] - clipped[0]) / spacing)))
            # Validation rejects spacings that need more lines than this; the
            # cap keeps a payload that skipped validation bounded too.
            n_lines = min(n_lines, MAX_PAGE_LINES)
            pdf.saveState()
            pdf.setLineWidth(0.3)
            for step in range(1, n_lines):
                frac = step / n_lines
                y = y_top - frac * (y_top - y_bot)
                pdf.line(_tx(COL_PIEZO_L), y, _tx(COL_PIEZO_R), y)
            pdf.restoreState()


def _draw_hatches(pdf, payload, frame: Frame, window) -> None:
    start, end = window
    for layer in payload.get("layers") or []:
        top = layer.get("depth_start_m")
        bottom = layer.get("depth_end_m")
        if top is None or bottom is None:
            continue
        clipped = clip_interval(float(top), float(bottom), start, end)
        if clipped is None or clipped[1] <= clipped[0]:
            continue
        kind = hatch_for_layer(layer.get("soil_type"), layer.get("desc"))
        if not kind:
            continue
        y_top = _ty(_dxf_depth_y(clipped[0], window, frame))
        y_bot = _ty(_dxf_depth_y(clipped[1], window, frame))
        fill_pattern(
            pdf,
            _tx(COL_SYMBOL_L),
            y_bot,
            _tx(COL_SYMBOL_R) - _tx(COL_SYMBOL_L),
            y_top - y_bot,
            kind,
        )


def _draw_water(pdf, payload, frame: Frame, window, text_scale: float) -> None:
    raw = payload.get("info", {}).get("WATER LEVEL (M)", "")
    if not _filled(raw) or isinstance(raw, str):
        return
    depth = float(raw)
    start, end = window
    if not contains_point(depth, start, end):
        return
    shift = _dxf_depth_y(depth, window, frame) - WL_TEMPLATE_APEX_Y
    pdf.setLineWidth(0.4)
    pdf.setStrokeColorRGB(0, 0, 0)
    xs: list[float] = []
    ys: list[float] = []
    for polyline in WATER_LEVEL_TEMPLATE:
        for (x1, y1), (x2, y2) in zip(polyline, polyline[1:]):
            pdf.line(_tx(x1), _ty(y1 + shift), _tx(x2), _ty(y2 + shift))
        for x, y in polyline:
            xs.append(x)
            ys.append(y)
    label = "Water Level"
    font = "Helvetica-Oblique"
    size = 2.0 * _SCALE * text_scale
    pdf.setFont(font, size)
    width = pdf.stringWidth(label, font, size)
    gap = 1.0 * mm
    y_center = _ty((min(ys) + max(ys)) / 2.0 + shift)
    pdf.drawString(_tx(min(xs)) - gap - width, y_center - size * 0.35, label)


def _draw_page_text(pdf, laid: PageText) -> None:
    for x1, y1, x2, y2, width in laid.lines:
        pdf.setLineWidth(width)
        pdf.line(x1, y1, x2, y2)
    for x, y, text, font, size in laid.texts:
        pdf.setFont(font, size)
        pdf.drawString(x, y, text)


def _draw_page(pdf, payload, frame, window, laid, index, total, text_scale, warnings) -> None:
    _draw_chrome(pdf, payload, index, total, text_scale, warnings)
    _draw_depth_axis(pdf, frame, window)
    _draw_grid_and_series(pdf, payload, frame, window, warnings)
    _draw_boundaries(pdf, payload, frame, window)
    _draw_hatches(pdf, payload, frame, window)
    _draw_samples(pdf, payload, frame, window, text_scale)
    _draw_piezo(pdf, payload, frame, window)
    _draw_water(pdf, payload, frame, window, text_scale)
    _draw_page_text(pdf, laid)


def _draw_continuation(pdf, payload, frame, items, index, total, text_scale, warnings) -> None:
    _draw_chrome(pdf, payload, index, total, text_scale, warnings)
    pdf.setFont("Helvetica-Oblique", 6)
    pdf.drawString(frame.depth_x_l + 1, frame.gy_top - 10, "notes")
    y = frame.gy_top - _PAD_Y - _DESC_FS
    for font, text in items:
        pdf.setFont(font, _DESC_FS)
        pdf.drawString(frame.mx_l + _PAD_X, y, text)
        y -= _LINE_H
