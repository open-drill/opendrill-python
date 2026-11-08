"""Depth windows, ticks, and which page a depth belongs on.

No PDF library is imported here. Depths are metres. A page owns the half-open
interval ``(page_start, page_end]``: a point that lands on a shared boundary
is drawn on the page that ends there, so it is not drawn twice. The ground
surface, 0 m, is kept on the first page.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# 1 micrometre. Used so binary floats do not create false overlaps or an
# extra page when a depth is an exact multiple of the sheet length.
DEPTH_TOL_M = 1e-6

# Safety stop. A tiny depth_per_sheet_m must not allocate tens of thousands
# of pages. The error tells the caller to increase the sheet length.
MAX_PAGES = 200

# Safety stop for drawing work inside one page. Depth-axis ticks, grid lines,
# and piezometer screen lines are each kept at or below this count, so a huge
# sheet length or a tiny line spacing cannot request millions of strokes.
MAX_PAGE_LINES = 1000


def contains_point(depth: float, page_start: float, page_end: float) -> bool:
    """Return whether ``depth`` (metres) belongs to this page window.

    Page edges are computed as ``i * depth_per_sheet_m`` and are not exact
    in binary floating point (3 * 0.3 is 0.8999999999999999). A depth within
    :data:`DEPTH_TOL_M` of an edge is treated as lying on it, so it belongs
    to the page that ends there and to no other page.
    """
    if page_start + DEPTH_TOL_M < depth <= page_end + DEPTH_TOL_M:
        return True
    # Keep 0 m on the first page. Every later window starts above 0.
    if page_start == 0 and abs(depth) <= DEPTH_TOL_M:
        return True
    return False


def overlaps_interval(
    start: float,
    end: float,
    page_start: float,
    page_end: float,
) -> bool:
    """Return whether a depth interval meets this page.

    Zero-thickness intervals are points and follow :func:`contains_point`.
    A positive interval that only touches ``page_end`` at its start belongs
    to the next page.
    """
    if end < start - DEPTH_TOL_M:
        return False
    if abs(end - start) <= DEPTH_TOL_M:
        return contains_point(start, page_start, page_end)
    return start < page_end - DEPTH_TOL_M and end > page_start + DEPTH_TOL_M


def clip_interval(
    start: float,
    end: float,
    page_start: float,
    page_end: float,
) -> tuple[float, float] | None:
    """Clip ``[start, end]`` to the page, or return None if it misses."""
    if not overlaps_interval(start, end, page_start, page_end):
        return None
    if abs(end - start) <= DEPTH_TOL_M:
        return (start, start)
    top = max(start, page_start)
    bot = min(end, page_end)
    if bot < top:
        return None
    return (top, bot)


def depth_marks(start_m: float, end_m: float, step_m: float) -> list[float]:
    """Depths ``start + k * step`` inside the window, then ``end`` itself.

    Marks sit at real depth increments, so a sheet whose length is not a
    whole number of steps does not stretch them away from their labels. The
    page end is always the last mark. The count is capped by
    :data:`MAX_PAGE_LINES`.
    """
    span = end_m - start_m
    if not math.isfinite(span) or span <= 0 or not math.isfinite(step_m) or step_m <= 0:
        raise ValueError("depth span and step must be finite and positive")
    if span / step_m > MAX_PAGE_LINES:
        raise ValueError("too many depth marks for one page")
    marks: list[float] = []
    k = 0
    while True:
        depth = start_m + k * step_m
        if depth >= end_m - DEPTH_TOL_M:
            break
        marks.append(depth)
        k += 1
    marks.append(end_m)
    return marks


def format_depth(value: float) -> str:
    """Format a depth in metres without a trailing ``.0``."""
    if abs(value - round(value)) <= DEPTH_TOL_M:
        return str(int(round(value)))
    text = f"{value:.6g}"
    return text


def _nice_step(span: float, target_divisions: int) -> float:
    """Pick a 1-2-5 step so ``span`` has about ``target_divisions`` gaps."""
    if span <= 0 or not math.isfinite(span):
        raise ValueError("span must be finite and positive")
    raw = span / max(target_divisions, 1)
    if raw <= 0 or not math.isfinite(raw):
        raise ValueError("span is too small to divide into ticks")
    exp = math.floor(math.log10(raw))
    base = 10.0 ** exp
    frac = raw / base
    if frac <= 1:
        nice = 1
    elif frac <= 2:
        nice = 2
    elif frac <= 5:
        nice = 5
    else:
        nice = 10
    return nice * base


@dataclass(frozen=True)
class DepthAxis:
    """Tick specification for one page's depth column. All values are metres."""

    start_m: float
    end_m: float
    major_step_m: float
    minor_divisions: int
    label_depths_m: tuple[float, ...]

    @property
    def minor_step_m(self) -> float:
        return self.major_step_m / self.minor_divisions

    def ticks(self) -> list[tuple[float, bool]]:
        """``(depth_m, is_major)`` for every tick, at real depth increments.

        The page end gets a major tick even when it is not a whole number of
        minor steps from the page start.
        """
        marks = depth_marks(self.start_m, self.end_m, self.minor_step_m)
        last = len(marks) - 1
        return [
            (depth, index % self.minor_divisions == 0 or index == last)
            for index, depth in enumerate(marks)
        ]

    @property
    def minor_count(self) -> int:
        span = self.end_m - self.start_m
        step = self.minor_step_m
        if step <= 0:
            return 1
        return max(1, int(round(span / step)))


def depth_axis(start_m: float, end_m: float) -> DepthAxis:
    """Ticks for a page window.

    Sheets of 2 m or more keep the original 1 m major ticks and 10 minor
    ticks per metre. Shorter sheets use a 1-2-5 step so the span is not
    rounded to an integer (which dropped the real page end and, below
    0.5 m, divided by zero). The page-end depth is always a label. The
    page-start depth is not labelled, matching the original column.
    """
    span = end_m - start_m
    if not math.isfinite(span) or span <= 0:
        raise ValueError("depth span must be finite and positive")
    if span + DEPTH_TOL_M >= 2 and span <= MAX_PAGE_LINES / 10:
        major = 1.0
        divisions = 10
    elif span > MAX_PAGE_LINES / 10:
        # Very long sheets: keep the 1-2-5 major step and 5 minor ticks per
        # major, so the tick count stays bounded.
        major = _nice_step(span, 10)
        divisions = 5
    else:
        major = _nice_step(span, 8)
        divisions = 5
        if major <= 0 or major > span:
            major = span
            divisions = 2
    labels = depth_marks(start_m, end_m, major)[1:]
    return DepthAxis(start_m, end_m, major, divisions, tuple(labels))


def grid_depth_step_m(span_m: float) -> float:
    """Horizontal grid spacing in the Su/SPT plot, in metres.

    A 20 m sheet keeps a 1 m grid and a 10 m sheet keeps 0.5 m, as in the
    original. Any other span uses 0.5 m when that still produces a line,
    and a smaller 1-2-5 step otherwise. The result is always in ``(0, span]``.
    """
    if not math.isfinite(span_m) or span_m <= 0:
        raise ValueError("depth span must be finite and positive")
    if abs(span_m - 20) <= DEPTH_TOL_M:
        step = 1.0
    elif abs(span_m - 10) <= DEPTH_TOL_M:
        step = 0.5
    else:
        step = 0.5
    if step <= 0 or span_m / step < 0.5:
        step = _nice_step(span_m, 8)
    elif span_m / step > MAX_PAGE_LINES:
        step = _nice_step(span_m, 40)
    if not math.isfinite(step) or step <= 0 or step > span_m:
        step = span_m
    return step


def grid_line_count(span_m: float) -> int:
    """Number of grid intervals. Always at least 1, so the painter never divides by zero."""
    step = grid_depth_step_m(span_m)
    return max(1, int(round(span_m / step)))


def sheet_count(extent_m: float, depth_per_sheet_m: float) -> int:
    """How many full depth windows cover ``extent_m``.

    An extent that lands on a window boundary does not open an extra page.
    The terminal depth stays on the page that ends there.
    """
    if depth_per_sheet_m <= 0 or not math.isfinite(depth_per_sheet_m):
        raise ValueError("depth_per_sheet_m must be finite and positive")
    if extent_m <= DEPTH_TOL_M:
        return 1
    # Same tolerance as contains_point: a depth up to DEPTH_TOL_M past a
    # sheet end belongs to that sheet, so it must not open another one, and
    # anything deeper must.
    ratio = (extent_m - DEPTH_TOL_M) / depth_per_sheet_m
    if not math.isfinite(ratio) or ratio > 10 * MAX_PAGES:
        # Callers compare against MAX_PAGES. Report "too many" without
        # rounding an infinite or astronomically large ratio.
        return 10 * MAX_PAGES + 1
    return max(1, math.ceil(ratio - 1e-9))


def data_page_windows(
    extent_m: float,
    depth_per_sheet_m: float,
) -> list[tuple[float, float]]:
    """``(start_m, end_m)`` for each depth sheet. Does not include notes-only sheets."""
    count = sheet_count(extent_m, depth_per_sheet_m)
    return [
        (i * depth_per_sheet_m, (i + 1) * depth_per_sheet_m)
        for i in range(count)
    ]


def log_extent_m(payload: dict) -> float:
    """Deepest depth the log must reach, in metres.

    Layer bottoms are not enough. Sample intervals, the water level, the
    piezometer/backfill/screen, and an explicit termination depth are all
    included. 0 m does not by itself add a page.
    """
    depths: list[float] = []

    def add(value: object) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        if math.isfinite(number) and number > 0:
            depths.append(number)

    for layer in payload.get("layers") or []:
        if isinstance(layer, dict):
            add(layer.get("depth_start_m"))
            add(layer.get("depth_end_m"))
    for test in payload.get("tests") or []:
        if isinstance(test, dict):
            add(test.get("depth_top_m"))
            add(test.get("depth_bot_m"))
    info = payload.get("info") or {}
    if isinstance(info, dict):
        add(info.get("WATER LEVEL (M)"))
    add(payload.get("termination_depth_m"))
    piezo = payload.get("piezo") or {}
    if isinstance(piezo, dict):
        for key in (
            "bottom_depth_m",
            "bottom_piezo_m",
            "top_screen_m",
            "bottom_screen_m",
        ):
            add(piezo.get(key))
    return max(depths) if depths else 0.0
