"""Read and write the Excel workbook used by the original script.

Sheet names are matched case-insensitively. Aliases from the original are
kept (for example ``samples`` and ``tests`` both map to the sample table).

Formula cells are not evaluated here. If Excel has saved a cached result it
is used and a warning is recorded, because that cache can be stale. If there
is no cached result the read fails instead of silently dropping the value.
Duplicate keys in a KEY/VALUE sheet are an error; the last value does not win.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from opendrill.errors import InputError, PayloadError
from opendrill.validate import SOIL_TYPES, SU_KINDS, TEST_TYPES

_COMMENT_AUTHOR = "opendrill"

# Input limits. A real borehole log workbook is tens of kilobytes with a few
# hundred rows. The limits stop a small file from expanding into a huge
# in-memory sheet: the archive is checked before openpyxl parses it, the
# number of cells stored in each sheet is capped, and rows are read only as
# far as the last cell that holds a value. Cells that carry formatting but
# no value (Excel writes these when formatting is copied down a column) do
# not count toward the row and column limits.
MAX_WORKBOOK_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_WORKBOOK_ENTRIES = 2000
MAX_SHEET_CELLS = 200_000
MAX_SHEET_ROWS = 5000
MAX_SHEET_COLUMNS = 64

SHEET_ALIASES = {
    "info": ("Project", "project info", "info"),
    "layer": ("Layers", "layer", "layers"),
    "test": ("Samples", "test", "tests", "samples"),
    "piezo": ("Piezo", "piezo", "piezometer"),
    "notes": ("Notes", "notes"),
    "meta": ("Settings", "meta", "settings"),
}

_HEADER_CANONICAL = {
    "su_kpa": "su_kPa",
    "uc_kpa": "uc_kPa",
    "ppen_kpa": "ppen_kPa",
}

INFO_FIELDS = [
    ("LOG TITLE", "SYNTHETIC TEST HOLE LOG", "Title shown at the top of the PDF"),
    ("PROJECT", "Synthetic example — not a field record", ""),
    ("PROJECT NO", "SYN-001", ""),
    ("HOLE NO", "SYN-BH-01", "Borehole identifier printed in the footer"),
    ("DRILL METHOD", "Synthetic method", ""),
    None,
    ("STARTED", "2000-01-01", "Free-text date"),
    ("FINISHED", "2000-01-02", ""),
    None,
    ("LOCATION", "Synthetic location", ""),
    ("COORDINATES (m) N", 0, "Northing in metres. No coordinate system is assumed."),
    ("COORDINATES (m) E", 0, "Easting in metres. No coordinate system is assumed."),
    ("CRS", "", "Optional label. Printed only if you supply it. No CRS is assumed."),
    ("HORIZONTAL DATUM", "", "Optional label. Printed only if you supply it."),
    ("VERTICAL DATUM", "", "Optional label. Printed only if you supply it."),
    ("GROUND ELEV. (m)", 100, "Ground elevation in metres. May be negative."),
    ("WATER LEVEL (m)", "", "Depth to water in metres. Optional."),
    None,
    ("LOGGED BY", "synthetic", ""),
    ("CHECKED BY", "synthetic", ""),
]

LAYER_COLS = [
    ("depth_start_m", "Top depth of the layer in metres. Required, >= 0."),
    ("depth_end_m", "Bottom depth in metres. Required, >= depth_start_m. Zero thickness is allowed. Gaps are allowed; overlaps are not."),
    ("soil_type", f"One of: {', '.join(SOIL_TYPES)}. Selects the hatch. If blank, a category may be guessed from desc."),
    ("desc", "Description text in the materials column."),
]

TEST_COLS = [
    ("no", "Sample number (integer)."),
    ("test", f"Printed as entered. Dropdown suggestions: {', '.join(TEST_TYPES)}. SPT N is plotted only when this is SPT."),
    ("depth_top_m", "Sample top depth in metres. Required when the row has any measurement."),
    ("depth_bot_m", "Sample bottom depth in metres. Required with depth_top_m. Must be >= top."),
    ("recovery", "Recovery in percent, 0 to 100."),
    ("spt1", "SPT blow count, first 6-inch increment. Not a depth and not N60."),
    ("spt2", "SPT blow count, second 6-inch increment. N = spt2 + spt3."),
    ("spt3", "SPT blow count, third 6-inch increment. N = spt2 + spt3, not N60."),
    ("wp_pct", "Plastic limit in percent. Must be <= wl_pct when both are set. May exceed 100 only if the liquid limit is higher."),
    ("w_pct", "Moisture content in percent. May exceed 100. Plotted on its own; plastic and liquid limits are not required."),
    ("wl_pct", "Liquid limit in percent. May exceed 100."),
    ("fines_pct", "Fines content in percent, 0 to 100. Plotted for any test type, not only SPT."),
    ("su_kPa", "Undrained shear strength in kPa, plotted as entered. Never halved."),
    ("su_kind", f"One of: {', '.join(SU_KINDS)}. Selects the Su symbol."),
    ("uc_kPa", "Measured unconfined compressive strength in kPa. If su_kPa is omitted and su_kind is uc, plotted Su = uc_kPa / 2."),
    ("ppen_kPa", "Pocket-penetrometer reading in kPa as you enter it (no unit conversion). If su_kPa is omitted and su_kind is ppen, plotted Su = ppen_kPa / 2."),
]

PIEZO_FIELDS = [
    ("bottom_depth_m", "Backfill / hole bottom depth in metres"),
    ("bottom_piezo_m", "Piezometer or casing bottom depth in metres"),
    ("top_screen_m", "Top of the screen interval in metres"),
    ("bottom_screen_m", "Bottom of the screen interval in metres. Must be below the top and should not pass bottom_piezo_m."),
    ("screen_line_spacing_m", "Spacing of screen ticks in metres. Must be > 0. Default drawn spacing is 0.1 when omitted."),
]

META_FIELDS = [
    ("depth_per_sheet_m", 20, "Metres of depth per PDF page. Must be a finite number > 0. Default 20."),
    ("termination_depth_m", None, "Optional end-of-hole depth in metres. Pagination includes it. No value is invented if this is blank."),
]


HEADER_FILL_COLOR = "D9EAF7"
HEADER_TEXT_COLOR = "1F2937"
BODY_FONT_SIZE = 12
HEADER_FONT = Font(bold=True, color=HEADER_TEXT_COLOR, size=BODY_FONT_SIZE)
HEADER_FILL = PatternFill("solid", fgColor=HEADER_FILL_COLOR)
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
DATA_FONT = Font(size=BODY_FONT_SIZE)
BORDER = Border(
    left=Side(style="thin", color="DDDDDD"),
    right=Side(style="thin", color="DDDDDD"),
    top=Side(style="thin", color="DDDDDD"),
    bottom=Side(style="thin", color="DDDDDD"),
)


def _style_header(cell, comment_text: str = "") -> None:
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = HEADER_ALIGN
    cell.border = BORDER
    if comment_text:
        cell.comment = Comment(comment_text, _COMMENT_AUTHOR)


def _style_data(cell) -> None:
    cell.font = DATA_FONT


def _add_dropdown(ws, col_idx: int, choices, last_row: int = 100) -> None:
    formula = '"' + ",".join(choices) + '"'
    validation = DataValidation(type="list", formula1=formula, allow_blank=True)
    validation.error = f"Must be one of: {', '.join(choices)}"
    validation.errorTitle = "Invalid value"
    ws.add_data_validation(validation)
    column = get_column_letter(col_idx)
    validation.add(f"{column}2:{column}{last_row}")


def _info_sheet(wb, info: dict | None, filled: bool) -> None:
    ws = wb.create_sheet("Project")
    ws.cell(row=1, column=1, value="KEY")
    ws.cell(row=1, column=2, value="VALUE")
    _style_header(ws.cell(row=1, column=1), "Field name (do not change)")
    _style_header(ws.cell(row=1, column=2), "Project value")
    info = info or {}
    info_ci = {str(key).strip().upper(): value for key, value in info.items()}
    canonical = set()
    for entry in INFO_FIELDS:
        if entry is None:
            continue
        key, _example, _tip = entry
        canonical.add(key.strip().upper())
    row_index = 2
    for entry in INFO_FIELDS:
        if entry is None:
            row_index += 1
            continue
        key, example, tip = entry
        cell_key = ws.cell(row=row_index, column=1, value=key)
        _style_data(cell_key)
        if tip:
            cell_key.comment = Comment(tip, _COMMENT_AUTHOR)
        if info:
            value = info_ci.get(key.strip().upper())
        else:
            value = example if filled else None
        cell_value = ws.cell(row=row_index, column=2, value=None if value == "" else value)
        _style_data(cell_value)
        row_index += 1
    for key in info:
        if str(key).strip().upper() in canonical:
            continue
        cell_key = ws.cell(row=row_index, column=1, value=key)
        _style_data(cell_key)
        raw = info.get(key)
        cell_value = ws.cell(row=row_index, column=2, value=None if raw == "" else raw)
        _style_data(cell_value)
        row_index += 1
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 56
    ws.freeze_panes = "A2"


def _meta_sheet(wb, payload: dict, filled: bool) -> None:
    ws = wb.create_sheet("Settings")
    ws.cell(row=1, column=1, value="KEY")
    ws.cell(row=1, column=2, value="VALUE")
    _style_header(ws.cell(row=1, column=1))
    _style_header(ws.cell(row=1, column=2))
    for index, (key, default, tip) in enumerate(META_FIELDS, 2):
        cell_key = ws.cell(row=index, column=1, value=key)
        _style_data(cell_key)
        cell_key.comment = Comment(tip, _COMMENT_AUTHOR)
        if payload:
            value = payload.get(key)
        else:
            value = default if filled else None
        cell_value = ws.cell(row=index, column=2, value=value)
        _style_data(cell_value)
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 18
    ws.freeze_panes = "A2"


def _table_sheet(wb, name: str, cols, rows, dropdowns) -> None:
    ws = wb.create_sheet(name)
    for column, (key, tip) in enumerate(cols, 1):
        cell = ws.cell(row=1, column=column, value=key)
        _style_header(cell, tip)
        ws.column_dimensions[get_column_letter(column)].width = max(14, min(36, len(key) + 6))
    for row_index, row in enumerate(rows or [], 2):
        for column, (key, _tip) in enumerate(cols, 1):
            value = row.get(key) if isinstance(row, dict) else None
            cell = ws.cell(row=row_index, column=column, value=value)
            _style_data(cell)
    for col_idx, choices in dropdowns.items():
        _add_dropdown(ws, col_idx, choices)
    ws.freeze_panes = "A2"


def _piezo_sheet(wb, piezo: dict | None) -> None:
    ws = wb.create_sheet("Piezo")
    ws.cell(row=1, column=1, value="KEY")
    ws.cell(row=1, column=2, value="VALUE")
    _style_header(ws.cell(row=1, column=1))
    _style_header(ws.cell(row=1, column=2))
    piezo = piezo or {}
    canonical = []
    for index, (key, tip) in enumerate(PIEZO_FIELDS, 2):
        canonical.append(key)
        cell_key = ws.cell(row=index, column=1, value=key)
        _style_data(cell_key)
        cell_key.comment = Comment(tip, _COMMENT_AUTHOR)
        cell_value = ws.cell(row=index, column=2, value=piezo.get(key))
        _style_data(cell_value)
    next_row = 2 + len(PIEZO_FIELDS)
    for key in piezo:
        if key in canonical:
            continue
        cell_key = ws.cell(row=next_row, column=1, value=key)
        _style_data(cell_key)
        cell_value = ws.cell(row=next_row, column=2, value=piezo.get(key))
        _style_data(cell_value)
        next_row += 1
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 16
    ws.freeze_panes = "A2"


def _notes_sheet(wb, text: str | None) -> None:
    ws = wb.create_sheet("Notes")
    if text:
        for index, line in enumerate(str(text).split("\n"), 1):
            cell = ws.cell(row=index, column=1, value=line)
            _style_data(cell)
    ws.column_dimensions["A"].width = 100


def build_workbook(payload: dict | None, *, filled: bool = True) -> Workbook:
    """Build a workbook. ``payload=None`` and ``filled=False`` is the blank template."""
    wb = Workbook()
    default = wb.active
    if default is not None:
        wb.remove(default)
    wb.properties.creator = _COMMENT_AUTHOR
    wb.properties.lastModifiedBy = _COMMENT_AUTHOR
    wb.properties.title = "opendrill"
    payload = payload or {}
    _info_sheet(wb, payload.get("info"), filled and not payload)
    layer_rows = payload.get("layers") if payload else None
    if not layer_rows and not payload:
        layer_rows = [{
            "depth_start_m": 0,
            "depth_end_m": 1.0,
            "soil_type": "SAND",
            "desc": "<- delete this example row",
        }] if not filled else []
    _table_sheet(wb, "Layers", LAYER_COLS, layer_rows or [], dropdowns={3: list(SOIL_TYPES)})
    # The blank template has no example sample row and no example note. Either
    # would be drawn on the PDF as if it were data. Column comments and the
    # dropdowns carry the guidance instead.
    test_rows = payload.get("tests") if payload else None
    _table_sheet(
        wb,
        "Samples",
        TEST_COLS,
        test_rows or [],
        dropdowns={2: list(TEST_TYPES), 14: list(SU_KINDS)},
    )
    piezo = payload.get("piezo") if payload else None
    if not piezo and not payload:
        piezo = {"screen_line_spacing_m": 0.1} if not filled else None
    _piezo_sheet(wb, piezo)
    notes = payload.get("notes") if payload else None
    _notes_sheet(wb, notes)
    _meta_sheet(wb, payload, filled and not payload)
    return wb


def _find_sheet(wb, canonical_key: str) -> str | None:
    """The one sheet matching ``canonical_key``'s aliases. Two matches are an error."""
    candidates = {name.lower() for name in SHEET_ALIASES.get(canonical_key, ())}
    matches = [name for name in wb.sheetnames if name.lower() in candidates]
    if len(matches) > 1:
        raise InputError(
            f"sheets {', '.join(repr(name) for name in matches)} are aliases of the same sheet; "
            "keep one and delete or rename the others, so no rows are silently ignored"
        )
    return matches[0] if matches else None


def _normalize_value(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _is_header_kv(key, value) -> bool:
    return (
        isinstance(key, str)
        and isinstance(value, str)
        and key.strip().upper() == "KEY"
        and value.strip().upper() == "VALUE"
    )


def _is_formula(cell) -> bool:
    value = cell.value
    return cell.data_type == "f" or (isinstance(value, str) and value.startswith("="))


class WorkbookData:
    """Payload read from a workbook, with sheet locations for error messages."""

    def __init__(self) -> None:
        self.payload: dict = {}
        self.warnings: list[str] = []
        self.sheet_names: dict[str, str] = {}
        self.table_rows: dict[str, list[int]] = {"layers": [], "tests": []}
        self.key_rows: dict[str, dict[str, int]] = {"info": {}, "piezo": {}, "meta": {}}


def _cached_value(formula_cell, data_cell, sheet: str, coordinate: str, warnings: list[str]):
    """Use Excel's cached formula result, or fail when the cache is empty."""
    if not _is_formula(formula_cell):
        return data_cell.value
    cached = data_cell.value
    if cached is None:
        raise InputError(
            f"{sheet} sheet cell {coordinate}: formula {formula_cell.value!r} has no cached "
            "result. Open and save the workbook in Excel, or replace the formula with a literal. "
            "This package does not evaluate formulas, so an empty cache would silently drop the value."
        )
    warnings.append(
        f"{sheet} sheet cell {coordinate}: using cached formula result {cached!r} "
        f"for {formula_cell.value!r}. Recalculate in Excel if that cache is stale."
    )
    return cached


def _check_archive(path: Path) -> None:
    """Reject a workbook whose ZIP contents would expand past the input limits."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise InputError(f"cannot open {path.name} as an Excel workbook: {exc}") from exc
    if len(entries) > MAX_WORKBOOK_ENTRIES:
        raise InputError(
            f"{path.name} has {len(entries)} parts inside the workbook file; "
            f"the limit is {MAX_WORKBOOK_ENTRIES}"
        )
    total = sum(entry.file_size for entry in entries)
    if total > MAX_WORKBOOK_UNCOMPRESSED_BYTES:
        raise InputError(
            f"{path.name} expands to {total:,} bytes; the limit is "
            f"{MAX_WORKBOOK_UNCOMPRESSED_BYTES:,} bytes"
        )


def _value_extent(ws, name: str) -> tuple[int, int]:
    """Last row and column holding a value, after checking the sheet's size.

    Uses the cells openpyxl actually stored, so the cost follows the file's
    contents, not the rectangle Excel reports as the used range.
    """
    cells = getattr(ws, "_cells", None)
    if cells is None:  # pragma: no cover - other openpyxl internals
        return ws.max_row, ws.max_column
    if len(cells) > MAX_SHEET_CELLS:
        raise InputError(
            f"{name} sheet stores {len(cells):,} cells; the limit is {MAX_SHEET_CELLS:,}"
        )
    rows = cols = 0
    for (row, col), cell in cells.items():
        if cell.value is not None:
            rows = max(rows, row)
            cols = max(cols, col)
    if rows > MAX_SHEET_ROWS or cols > MAX_SHEET_COLUMNS:
        raise InputError(
            f"{name} sheet has values as far as row {rows} and column {cols}; "
            f"the limit is {MAX_SHEET_ROWS} rows and {MAX_SHEET_COLUMNS} columns. "
            "Delete stray values far below or to the right of the data."
        )
    return rows, cols


def read_workbook(path: Path) -> WorkbookData:
    """Read an ``.xlsx`` or ``.xlsm`` log into a payload."""
    path = Path(path)
    _check_archive(path)
    try:
        formulas = load_workbook(path, data_only=False)
        cached = load_workbook(path, data_only=True)
    except Exception as exc:
        raise InputError(f"cannot open {path.name} as an Excel workbook: {exc}") from exc

    out = WorkbookData()
    for key in SHEET_ALIASES:
        name = _find_sheet(formulas, key)
        if name is not None:
            out.sheet_names[key] = name
    if not out.sheet_names:
        raise InputError(
            f"{path.name} has none of the expected sheets. Found: {', '.join(formulas.sheetnames)}. "
            "Expected some of: Project, Layers, Samples, Piezo, Notes, Settings."
        )
    # Rows and columns to read per sheet. At least 1 x 1: openpyxl treats a
    # bound of 0 as "no bound" and would fall back to the full used range.
    extent: dict[str, tuple[int, int]] = {}
    for sheet_name in out.sheet_names.values():
        rows_f, cols_f = _value_extent(formulas[sheet_name], sheet_name)
        rows_d, cols_d = _value_extent(cached[sheet_name], sheet_name)
        extent[sheet_name] = (max(rows_f, rows_d, 1), max(cols_f, cols_d, 1))

    def kv_items(canonical: str):
        sheet_name = out.sheet_names[canonical]
        ws_f = formulas[sheet_name]
        ws_d = cached[sheet_name]
        seen: dict[str, int] = {}
        for row_no, (_f_row, d_row) in enumerate(
            zip(
                ws_f.iter_rows(min_col=1, max_col=2, max_row=extent[sheet_name][0]),
                ws_d.iter_rows(min_col=1, max_col=2, max_row=extent[sheet_name][0]),
            ),
            1,
        ):
            key_cell, value_cell = _f_row[0], _f_row[1]
            data_key, data_value = d_row[0], d_row[1]
            key = _cached_value(key_cell, data_key, sheet_name, key_cell.coordinate, out.warnings)
            if key is None:
                continue
            value = _cached_value(value_cell, data_value, sheet_name, value_cell.coordinate, out.warnings)
            if _is_header_kv(key, value):
                continue
            token = str(key).strip()
            prior = seen.get(token.upper() if canonical == "info" else token)
            if prior is not None:
                raise InputError(
                    f"{sheet_name} sheet: duplicate key {token!r} on rows {prior} and {row_no}"
                )
            seen[token.upper() if canonical == "info" else token] = row_no
            yield row_no, token, _normalize_value(value)

    info: dict = {}
    if "info" in out.sheet_names:
        for row_no, key, value in kv_items("info"):
            stored_key = key.upper()
            if value is None:
                info[stored_key] = ""
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                info[stored_key] = value
            else:
                info[stored_key] = str(value)
            out.key_rows["info"][stored_key] = row_no

    def table(canonical_key: str, payload_key: str) -> list[dict]:
        name = out.sheet_names.get(canonical_key)
        if name is None:
            return []
        ws_f = formulas[name]
        ws_d = cached[name]
        max_row, max_col = extent[name]
        pairs = zip(
            ws_f.iter_rows(max_row=max_row, max_col=max_col),
            ws_d.iter_rows(max_row=max_row, max_col=max_col),
        )
        first = next(pairs, None)
        if first is None:
            return []
        header_f, header_d = first
        headers = []
        seen_headers: dict[str, int] = {}
        for column, cell in enumerate(header_f, 1):
            data_cell = header_d[column - 1]
            raw = _cached_value(cell, data_cell, name, cell.coordinate, out.warnings)
            if not raw:
                headers.append("")
                continue
            key = str(raw).strip().lower()
            key = _HEADER_CANONICAL.get(key, key)
            if key in seen_headers:
                raise InputError(
                    f"{name} sheet: duplicate column {key!r} "
                    f"(columns {seen_headers[key]} and {column})"
                )
            seen_headers[key] = column
            headers.append(key)
        result = []
        for row_no, (f_row, d_row) in enumerate(pairs, 2):
            values = []
            any_value = False
            for f_cell, d_cell in zip(f_row, d_row):
                value = _cached_value(f_cell, d_cell, name, f_cell.coordinate, out.warnings)
                if value is not None:
                    any_value = True
                values.append(_normalize_value(value))
            if not any_value:
                continue
            result.append({
                header: value
                for header, value in zip(headers, values)
                if header
            })
            out.table_rows[payload_key].append(row_no)
        return result

    layers = table("layer", "layers")
    tests = table("test", "tests")

    piezo: dict = {}
    if "piezo" in out.sheet_names:
        known = {key for key, _tip in PIEZO_FIELDS}
        for row_no, key, value in kv_items("piezo"):
            if value is None:
                continue
            piezo[key] = value
            out.key_rows["piezo"][key] = row_no
            if key not in known:
                out.warnings.append(
                    f"{out.sheet_names['piezo']} sheet: unrecognised key {key!r} "
                    "was kept on the payload but is not drawn"
                )

    notes = ""
    if "notes" in out.sheet_names:
        sheet_name = out.sheet_names["notes"]
        parts = []
        for f_row, d_row in zip(
            formulas[sheet_name].iter_rows(min_col=1, max_col=1, max_row=extent[sheet_name][0]),
            cached[sheet_name].iter_rows(min_col=1, max_col=1, max_row=extent[sheet_name][0]),
        ):
            value = _cached_value(f_row[0], d_row[0], sheet_name, f_row[0].coordinate, out.warnings)
            if value is not None:
                parts.append(str(value).strip())
        notes = "\n".join(parts)

    depth_per_sheet = 20.0
    termination = None
    if "meta" in out.sheet_names:
        known_meta = {key for key, _default, _tip in META_FIELDS}
        for row_no, key, value in kv_items("meta"):
            out.key_rows["meta"][key] = row_no
            if key not in known_meta:
                out.warnings.append(
                    f"{out.sheet_names['meta']} sheet: unrecognised key {key!r} was ignored"
                )
                continue
            if value is None:
                continue
            if isinstance(value, bool):
                raise InputError(
                    f"{out.sheet_names['meta']} sheet, row {row_no}: {key} "
                    f"must be a number in metres (got the Excel boolean {value!r})"
                )
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise InputError(
                    f"{out.sheet_names['meta']} sheet, row {row_no}: {key} "
                    f"must be a number (got {value!r})"
                ) from None
            if key == "depth_per_sheet_m":
                depth_per_sheet = number
            elif key == "termination_depth_m":
                termination = number

    out.payload = {
        "depth_per_sheet_m": depth_per_sheet,
        "termination_depth_m": termination,
        "info": info,
        "layers": layers,
        "tests": tests,
        "piezo": piezo,
        "notes": notes,
    }
    return out


def describe_payload_error(exc: PayloadError, src: WorkbookData) -> list[str]:
    """Turn validation locations into sheet, row, and column sentences."""
    def sheet(key: str, default: str) -> str:
        return src.sheet_names.get(key, default)

    lines = []
    for loc, msg, value in exc.errors:
        got = f" (got {value!r})" if value is not None else ""
        head = loc[0] if loc else None
        if head in ("layers", "tests"):
            index = loc[1]
            rows = src.table_rows[head]
            row = rows[index] if isinstance(index, int) and index < len(rows) else "?"
            name = sheet("layer", "Layers") if head == "layers" else sheet("test", "Samples")
            column = loc[2] if len(loc) > 2 else "?"
            lines.append(f"{name} sheet, row {row}, column {column}: {msg}{got}")
        elif head == "piezo":
            row = src.key_rows["piezo"].get(loc[1], "?") if len(loc) > 1 else "?"
            field = loc[1] if len(loc) > 1 else "?"
            lines.append(f"{sheet('piezo', 'Piezo')} sheet, row {row} ({field}): {msg}{got}")
        elif head == "depth_per_sheet_m":
            row = src.key_rows["meta"].get("depth_per_sheet_m", "?")
            lines.append(
                f"{sheet('meta', 'Settings')} sheet, row {row} (depth_per_sheet_m): {msg}{got}"
            )
        elif head == "termination_depth_m":
            row = src.key_rows["meta"].get("termination_depth_m", "?")
            lines.append(
                f"{sheet('meta', 'Settings')} sheet, row {row} (termination_depth_m): {msg}{got}"
            )
        elif head == "info" and len(loc) > 1:
            row = src.key_rows["info"].get(str(loc[1]).upper(), "?")
            lines.append(f"{sheet('info', 'Project')} sheet, row {row} ({loc[1]}): {msg}{got}")
        else:
            lines.append(f"{sheet('layer', 'Layers')} sheet: {msg}{got}")
    return lines


def input_warnings(src: WorkbookData) -> list[str]:
    """Soft problems that still produce a PDF."""
    warns = list(src.warnings)
    if "layer" not in src.sheet_names:
        warns.append('no "Layers" sheet found; the PDF will have no soil layers.')
    for index, layer in enumerate(src.payload.get("layers", [])):
        if "<- delete" in str(layer.get("desc") or ""):
            row = src.table_rows["layers"][index]
            warns.append(
                f"Layers sheet, row {row}: template example row still present "
                '("<- delete this example row").'
            )
    return warns
