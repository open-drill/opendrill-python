# Migration from the single-file generator

The previous generator was a single Python script that read an Excel workbook and drew a PDF with ReportLab. This package keeps that drawing and the workbook layout. The behavioural changes below are deliberate. They are the result of checking the original script against the cases it got wrong.

The original script's filled example (project, site, borehole id, map coordinates, personnel initials, and a drilling-contractor sentence) is not in this package. `opendrill example` writes a synthetic log labelled as such.

## What stayed

- Page frame, column positions, legend text, and hatch geometry from the script's DXF-derived template.
- Header and footer: title, started, finished, drill method, ground elevation, coordinates, project, project number, location, logged by, checked by, hole number, sheet count.
- Sample number, type, recovery, and depth bracket, including the small-bracket placement.
- Layer hatches. An explicit `soil_type` overrides a guess from the description. Guess order is still asphalt, then clay, then gravel, then sand. The word "backfill" in a description does not select the backfill hatch.
- Wrapped descriptions and the connector lines used when text runs past a layer boundary.
- Backfill column, casing rectangle, screen ticks, and the water-level symbol.
- Su symbols, SPT point, fines star, plastic-limit and liquid-limit marks, moisture circle, and the printed legend.
- Workbook sheets, aliases (`project info`, `samples`, `tests`, `meta`, and the others), dropdowns, comments, and row/column errors.
- CLI modes `--template`, `--example`, and `--example-pdf`, plus rendering a workbook by path.
- Depths in metres. No imperial depth axis was added.
- SPT N = `spt2 + spt3`, using the template's 6-inch increment columns. This is not N60.
- `su_kPa` is plotted as entered. It is not divided by 2.

## What changed

| Topic | Original script | This package |
| --- | --- | --- |
| Input | Excel only | Excel or a JSON object. `samples` is accepted as an alias of `tests` when `tests` is absent. |
| Lab results | Fines, plastic limit, liquid limit, and moisture were drawn only for a row with `test == "SPT"` and both `spt2` and `spt3`. Moisture was drawn only when both limits were present. | Each of those series is drawn on its own for any test type. SPT N is still only drawn for an SPT row with `spt2` and `spt3`. |
| Sheet length | `round(depth_per_sheet_m)` became the number of metre ticks. 0.4 m and 0.5 m raised `ZeroDivisionError`. 2.5 m was labelled 1.0 and 2.0, not 2.5. | The window keeps its real length. Sheets of 2 m and longer still use 1 m major ticks. Shorter sheets use a 1-2-5 step. The page-end depth is always labelled. Whole metres are printed as integers (`1`, not `1.0`). |
| Page extent | Only layer bottom depths. A deeper sample, water level, instrument, or end-of-hole depth was clipped away. | Extent is the deepest of layer depths, sample intervals, water level, backfill, casing, screen, and `termination_depth_m`. |
| Page boundary | Point data used a closed interval, so a point exactly on 10 m was drawn on both the 0–10 sheet and the 10–20 sheet. | Points use `(page_start, page_end]`. A shared boundary belongs to the sheet that ends there. 0 m stays on the first sheet. |
| Sample depths | Optional. A complete SPT without depths raised `TypeError`. | If a row has any measurement, both depths are required. One depth without the other is an error. The message names the field. |
| Non-finite numbers | `NaN` could crash later. `Infinity` was accepted. | `NaN` and infinities are rejected. |
| Blow counts, recovery, fines, Atterberg | Negative blows, recovery outside 0–100, fines outside 0–100, and plastic limit above liquid limit were accepted. | Those are errors. Moisture and liquid limit may be above 100 percent. |
| Off-scale points | Su outside 0–200 kPa, SPT N outside 0–100, and percent values outside 0–100 were omitted with no message. | The marker is drawn on the axis edge, with `<` or `>`, and a warning names the sample, field, value, and axis. |
| Strength | Legend says UC/2 and P.PEN/2. The code plotted `su_kPa` unchanged and had no place to store the raw measurement. | `su_kPa` is still never halved. Optional `uc_kPa` and `ppen_kPa` are the raw measurements in kPa, with no unit conversion. If `su_kPa` is omitted and `su_kind` is `uc` or `ppen`, the plotted Su is that measurement divided by 2 and `su_source` is `uc/2` or `ppen/2`. If both the raw value and `su_kPa` are set and they disagree with that halving, the given `su_kPa` is plotted and a warning says so. |
| Layers | Overlaps were rejected. Zero thickness and gaps happened to draw. | Same rules, stated in the errors. Two zero-thickness layers at the same depth are rejected. Touching layers are not an overlap. |
| Instruments | An inverted screen was skipped. | An inverted or one-sided screen is an error. Spacing must be greater than 0 metres. A screen outside the backfill depth, or deeper than the piezometer bottom (`bottom_piezo_m`), is warned and still drawn. |
| Long text | Descriptions and notes could draw through the footer. One extra depth sheet was added when notes did not fit, and that sheet continued the depth scale past the hole. | Text that would cross the footer moves to a later sheet. Extra note sheets are marked `notes` in the depth column and do not invent deeper metre labels. A description longer than a sheet is still restarted at the top of the next sheet the layer occupies. |
| Footer text | A long project name drew out of its cell. | Text is shrunk, then ellipsised, and a warning includes the full value. |
| Formulas | `data_only=True` reads Excel's cache. An uncalculated formula became an empty cell with no error. | A formula with no cached value is an error. A cached value is used and a warning says the cache may be stale. This package does not evaluate formulas. |
| Duplicate keys | The last KEY/VALUE row won. | Duplicate keys and duplicate table headers are errors and name both locations. |
| Overwrite | Workbooks were refused if the path existed. PDFs were replaced with no prompt. | Workbooks, JSON, and PDFs are refused when the path exists unless `--force` is passed. Writes go to a temporary file in the same directory and then replace the destination. |
| Workbook comment author | The string `opendrill`. | Unchanged, `opendrill`. PDF creator and author are also `opendrill`, not an account name. |
| Coordinates | Printed as stored. | Numbers must be finite. Text is still printed as entered. Optional `CRS`, `HORIZONTAL DATUM`, and `VERTICAL DATUM` are printed only when supplied. Nothing is assumed when they are blank. |
| Water level and ground elevation | Non-numeric values were ignored. | A non-numeric water level or ground elevation is an error. Ground elevation may be negative. Water-level depth must be ≥ 0 metres. |
| Page count | Unbounded. | More than 200 pages is an error that tells you to increase `depth_per_sheet_m` or shorten the text. Sheet numbers 10–200 stay in the footer; `OF` shifts right so the number is not clipped. |
| Command | `python <script>.py` | `opendrill`, including `render`, `validate`, `template`, and `example`. |

## Payload keys

The Excel reader still builds the same object the script used, plus the new optional fields.

```text
depth_per_sheet_m          metres, default 20
termination_depth_m        metres, optional
info                       header fields, keys matched case-insensitively
layers[]                   depth_start_m, depth_end_m, soil_type, desc
tests[]                    see README; JSON may use samples instead
piezo                      bottom_depth_m, bottom_piezo_m, top_screen_m,
                           bottom_screen_m, screen_line_spacing_m
notes                      string, or a list of strings in JSON
```

`su_source` is added by validation (`given`, `uc/2`, `ppen/2`, or null). It is not an input column.
