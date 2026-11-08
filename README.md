# opendrill

Render a soil or borehole log as a PDF from a JSON object or an Excel workbook. The drawing is the single-file ReportLab generator this repository started from: same page frame, same columns, same hatches, same legend. The package adds a non-interactive command, validation with field paths, and the corrections listed in [docs/migration.md](docs/migration.md).

It is not a soil classification and it does not implement USCS, ASTM, or CFEM. Hatches are the five drawing categories from that generator. SPT N is `spt2 + spt3` and is not N60. Depths are metres. There is no imperial depth axis.

Nothing in this repository is a field record. The worked example is synthetic and is labelled that way.

This package is released under the MIT License. See [LICENSE](LICENSE). Copyright 2026 OpenDrill contributors and grok-ja. Release steps are in [docs/pypi-release.md](docs/pypi-release.md).

## Install

```bash
python -m pip install opendrill
opendrill --help
```

Python 3.10 or newer. The runtime dependencies are `reportlab` and `openpyxl`. Importing `opendrill.validate` does not import either of them, and the package does not import a GUI toolkit.

## Quickstart

```bash
opendrill example json --out synthetic.json
opendrill render synthetic.json --out synthetic.pdf
opendrill validate synthetic.json
```

`synthetic.pdf` is a two-sheet log. Sheet length is 10 m. The hole is given a termination depth of 16 m, so the second sheet is real depth, not an empty extra page.

Excel still works:

```bash
opendrill template --out blank.xlsx
opendrill example xlsx --out synthetic.xlsx
opendrill render synthetic.xlsx --out synthetic-from-xlsx.pdf
```

The older flags are still there: `--template`, `--example`, `--example-pdf`, and a workbook path as the only argument.

Existing output files are left untouched unless you pass `--force`. The command never prompts and never opens a window. Exit status `0` means the file was written or the payload validated. Exit status `2` means the input was rejected; the reason is on stderr.

```bash
opendrill render hole.json --out hole.pdf
opendrill render - --out hole-from-stdin.pdf <<'EOF'
{"layers":[{"depth_start_m":0,"depth_end_m":2,"soil_type":"SAND","desc":"Synthetic sand"}]}
EOF
```

## Python API

```python
from opendrill import validate_log, render_log, build_pdf

checked = validate_log(payload)      # .payload, .warnings
result = render_log(checked.payload) # .pdf_bytes, .warnings, .page_count
pdf_bytes = build_pdf(payload)       # bytes only; still validates
```

`validate_log` and `validate_payload` raise `PayloadError`. Its `.errors` entries are `(location, message, value)`. Workbook problems that happen before validation raise `InputError`.

```python
from opendrill.excel_io import read_workbook, build_workbook
```

Those two import openpyxl. Call them only when you are actually reading or writing a workbook.

## Structured input

The root is an object. Depths are metres. Strength is kilopascals. Percent fields are literal percent, not a fraction. Unknown info keys are kept for workbook round-trip and are not printed unless they are in the list below. No coordinate system, datum, or termination depth is invented when the field is absent.

| Field | Unit | Rule |
| --- | --- | --- |
| `depth_per_sheet_m` | m | Finite and > 0. Default 20. A value that would create more than 200 pages is rejected. |
| `termination_depth_m` | m | Optional end-of-hole depth. Pagination includes it. If it is shallower than other data, the deeper data is kept and a warning is printed. |
| `notes` | text | A string, or a list of strings joined with newlines. |
| `layers[]` | | One object per layer. |
| `layers[].depth_start_m` | m | Required, ≥ 0. |
| `layers[].depth_end_m` | m | Required, ≥ start. Zero thickness is allowed. Gaps are allowed. Overlaps are not. |
| `layers[].soil_type` | | `ASPHALT`, `CLAY`, `GRAVEL`, `SAND`, `BACKFILL`, or blank. |
| `layers[].desc` | text | Wrapped into the materials column. If `soil_type` is blank, the hatch may be guessed from this text (asphalt, then clay, then gravel, then sand). |
| `tests[]` or `samples[]` | | Use one of these names, not both. |
| `tests[].depth_top_m`, `depth_bot_m` | m | Both required when the row has any measurement. Bottom ≥ top. |
| `tests[].no` | | Integer sample number. |
| `tests[].test` | | Printed as entered. Dropdown suggestions are `SPT`, `SHELBY`, `UC2`, `VANE`. Other text is allowed. `SPT` is matched without case sensitivity. |
| `tests[].recovery` | percent | 0 to 100. |
| `tests[].spt1`, `spt2`, `spt3` | blows | Integers ≥ 0. These are the template's three 6-inch increments, not depths. |
| `tests[].wp_pct` | percent | Plastic limit, ≥ 0. Must be ≤ `wl_pct` when both are set. May exceed 100 if the liquid limit is higher. |
| `tests[].w_pct` | percent | Moisture, ≥ 0. May exceed 100. Plotted even when the limits are absent. |
| `tests[].wl_pct` | percent | Liquid limit, ≥ 0. May exceed 100. |
| `tests[].fines_pct` | percent | 0 to 100. Plotted for any test type. |
| `tests[].su_kPa` | kPa | Undrained shear strength drawn as entered. Never halved. ≥ 0. Values above 200 are marked on the edge of the axis. |
| `tests[].su_kind` | | `field_peak`, `field_remold`, `lab_peak`, `lab_remold`, `uc`, `ppen`. |
| `tests[].uc_kPa` | kPa | Unconfined compressive strength as entered. No unit conversion. |
| `tests[].ppen_kPa` | kPa | Pocket-penetrometer reading as entered, already in kPa. No unit conversion. |
| `piezo.bottom_depth_m` | m | Backfill / hole bottom. |
| `piezo.bottom_piezo_m` | m | Casing or piezometer bottom. |
| `piezo.top_screen_m`, `bottom_screen_m` | m | Both or neither. Bottom must be deeper than top. A screen deeper than `bottom_piezo_m` is warned and still drawn. |
| `piezo.screen_line_spacing_m` | m | > 0. Drawn spacing is 0.1 m when the key is omitted. |

Header fields live under `info`. Names are matched without case.

| Key | Meaning |
| --- | --- |
| `LOG TITLE` | Replaces the default title `TEST HOLE LOG`. |
| `PROJECT`, `PROJECT NO`, `LOCATION`, `HOLE NO` | Footer. |
| `STARTED`, `FINISHED` | Free text. |
| `DRILL METHOD` | Free text. |
| `GROUND ELEV. (M)` | Metres. May be negative. Layer-boundary elevations are this value minus depth. |
| `WATER LEVEL (M)` | Depth to water in metres, ≥ 0. |
| `COORDINATES (M) N`, `COORDINATES (M) E` | Printed as metres. A number must be finite. Text is printed as typed. |
| `CRS`, `HORIZONTAL DATUM`, `VERTICAL DATUM` | Optional labels. Printed only if present, on the coordinate line, as `CRS  horizontal/vertical`. |
| `LOGGED BY`, `CHECKED BY` | Free text. |

### What gets plotted

Rows are independent.

- Su is drawn when `su_kPa` (or a derived value, below) and `su_kind` and both depths are present. The symbol follows `su_kind`.
- SPT N is drawn only for an SPT row with `spt2` and `spt3`. N = `spt2 + spt3`. The label is `spt1/spt2/spt3`. A missing `spt1` is shown as `-`.
- Plastic limit, liquid limit, moisture, and fines are each drawn when that field is present. Moisture does not require the limits. None of them require an SPT row.
- The template draws Su on a 0–200 kPa scale and draws N and the percent series on a 0–100 scale, on the same horizontal line. That shared line is unchanged. A value past the end of its scale is drawn on the edge and listed in the warnings. It is not dropped.

### Strength

The printed legend says `UC/2` and `P.PEN/2`. That text is part of the original template. It means those two symbols are an Su estimate equal to half of a measured unconfined compressive strength or pocket-penetrometer reading.

- If you already have Su, put it in `su_kPa`. It is plotted as entered, including when `su_kind` is `uc` or `ppen`.
- If you have the raw measurement and no Su, omit `su_kPa`, set `su_kind` to `uc` or `ppen`, and set `uc_kPa` or `ppen_kPa`. The plotted value is the measurement divided by 2. `su_source` on the normalised row is `uc/2` or `ppen/2`.
- If you set both and they disagree with that halving, `su_kPa` is plotted and a warning reports both numbers.

This division is the template legend's arithmetic. It is not a new correlation, and it is not applied to a value you already put in `su_kPa`.

### Pages

A sheet owns depths in the half-open window `(start, end]` in metres. A point exactly on 10 m is drawn on the sheet that ends at 10 m, not again on the next sheet. 0 m stays on the first sheet. The depth column labels whole metres as integers. On a 20 m sheet the major ticks are still every 1 m, with the original 0.1 m minor ticks. A 10 m sheet keeps the 0.5 m plot grid; a 20 m sheet keeps the 1 m plot grid.

Sheets of less than 2 m use a 1-2-5 tick step so a 2.5 m sheet is labelled through 2.5, not rounded to 2. The page-end depth is always labelled. The footer sheet number stays visible from sheet 1 through sheet 200; `OF` moves right when the number needs more than one digit.

Notes start under the last layer (and under a supplied termination caption when that depth is deeper). Lines that do not fit continue on the next sheet. A sheet that exists only to carry that text says `notes` in the depth column and does not extend the metre scale past the hole.

## Excel

Sheet names are case-insensitive. Aliases from the original script still work: `Project` / `project info` / `info`, `Layers`, `Samples` / `tests`, `Piezo`, `Notes`, `Settings` / `meta`.

Do not put formulas in value cells unless Excel has saved a cached result. A formula with an empty cache is an error, because reading it as a blank would drop the number. A cached result is used, and a warning says it may be stale. This package does not calculate formulas. Duplicate keys in a KEY/VALUE sheet are an error; the later row does not replace the earlier one.

`opendrill template` writes the column comments, dropdowns, and one placeholder layer row whose description contains `<- delete this example row`. Leaving that row in produces a warning. The template has no example sample or note, so nothing else from it is drawn on the PDF.

## For an automated agent

1. Install from the checkout or from git as shown above. Do not assume the name exists on PyPI.
2. Build one JSON object. Depths in metres, strength in kPa, percentages as percent. Do not convert units inside the file and do not add a datum or CRS the user did not supply.
3. Run `opendrill validate hole.json`. Status 2 means do not render; read stderr and fix the named field.
4. Run `opendrill render hole.json --out hole.pdf`. Pass `--force` only when replacing a file you created in the same run.
5. Treat warnings as part of the result. An off-scale point is drawn on the axis edge; it is not a successful silent plot.
6. Do not describe the PDF as compliant with a logging standard. Do not call SPT N an N60. Do not describe a hatch as a USCS group.
7. `examples/synthetic_borehole.json` is fake. Do not copy it into a report as subsurface data.
8. The command is headless. Do not look for a GUI.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m pip install build
python -m build
```

CI runs the tests on Python 3.10, 3.11, and 3.12 and installs the built wheel in a clean virtual environment.

## Provenance

The page geometry was baked from a DXF template by the original script, which described itself as a standalone copy of an OpenDrill PDF generator. The coordinates in `opendrill.geometry` are that drawing, in its own units, scaled onto the page. They are not map coordinates. This package is now published as `opendrill`. It was first developed as `soil-log`.
