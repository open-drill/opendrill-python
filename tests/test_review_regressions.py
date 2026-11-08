"""Regression tests for the findings of the first external review (v0.1.0)."""
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

import pytest

from opendrill import validate_log
from opendrill.cli import main
from opendrill.errors import InputError, PayloadError
from opendrill.excel_io import build_workbook, read_workbook
from opendrill.layout import (
    MAX_PAGE_LINES,
    contains_point,
    data_page_windows,
    depth_axis,
    depth_marks,
    grid_depth_step_m,
    log_extent_m,
)
from opendrill.render import render_log
from opendrill.synthetic import synthetic_payload
from tests.conftest import base_payload, page_text

ROOT = Path(__file__).resolve().parents[1]


# 1. Fractional page boundaries


def test_fractional_terminal_sample_is_drawn_once():
    payload = {
        "depth_per_sheet_m": 0.3,
        "tests": [
            {"depth_top_m": 0.9, "depth_bot_m": 0.9, "test": "SPT", "spt1": 2, "spt2": 3, "spt3": 4}
        ],
    }
    windows = data_page_windows(log_extent_m(payload), 0.3)
    assert len(windows) == 3
    assert windows[-1][1] < 0.9  # 3 * 0.3 is 0.8999999999999999
    owners = [w for w in windows if contains_point(0.9, *w)]
    assert owners == [windows[-1]]

    result = render_log(payload)
    labels = sum(text.count("2/3/4") for text in page_text(result.pdf_bytes))
    assert labels == 1


def test_a_depth_on_a_shared_boundary_has_one_owner():
    for dps in (0.1, 0.3, 0.7, 1.1, 2.05, 3.3):
        windows = data_page_windows(dps * 7, dps)
        for index in range(1, len(windows)):
            boundary = index * dps
            owners = [w for w in windows if contains_point(boundary, *w)]
            assert owners == [windows[index - 1]], (dps, index)


# 4. Depth ticks at real depths


def test_fractional_sheet_ticks_align_with_depth_labels():
    axis = depth_axis(0, 2.05)
    ticks = axis.ticks()
    depths = [depth for depth, _major in ticks]
    assert depths[-1] == pytest.approx(2.05)
    for depth in depths[:-1]:
        assert depth * 10 == pytest.approx(round(depth * 10)), depth
    majors = [depth for depth, major in ticks if major]
    assert majors == pytest.approx([0.0, 1.0, 2.0, 2.05])
    for label in axis.label_depths_m:
        assert any(abs(label - depth) < 1e-9 for depth in majors), label

    grid = depth_marks(0, 2.05, grid_depth_step_m(2.05))
    assert grid == pytest.approx([0.0, 0.5, 1.0, 1.5, 2.0, 2.05])


# 5. Drawing work per page is bounded


def test_render_primitive_counts_are_bounded():
    with pytest.raises(PayloadError) as info:
        validate_log({"piezo": {"top_screen_m": 0, "bottom_screen_m": 1, "screen_line_spacing_m": 1e-12}})
    assert any(loc == ("piezo", "screen_line_spacing_m") for loc, _msg, _value in info.value.errors)

    for span in (1e12, 1e6, 5000, 20, 2.05, 0.3):
        assert len(depth_axis(0, span).ticks()) <= MAX_PAGE_LINES + 1, span
        assert span / grid_depth_step_m(span) <= MAX_PAGE_LINES, span

    started = time.monotonic()
    result = render_log({"depth_per_sheet_m": 1e12, "layers": [{"depth_start_m": 0, "depth_end_m": 1}]})
    assert result.page_count == 1
    assert time.monotonic() - started < 10


# 6. "samples" alias is not carried into the normalised payload


def test_normalized_samples_payload_can_be_rendered_and_revalidated():
    checked = validate_log({"samples": [{"depth_top_m": 1, "depth_bot_m": 2, "w_pct": 20}]})
    assert "samples" not in checked.payload
    assert len(checked.payload["tests"]) == 1
    validate_log(checked.payload)
    assert render_log(checked.payload).pdf_bytes.startswith(b"%PDF")


# 7. Notes follow a deeper termination on a later page


def test_notes_follow_termination_on_later_page():
    payload = base_payload(
        depth_per_sheet_m=10,
        layers=[{"depth_start_m": 0, "depth_end_m": 2, "soil_type": "SAND", "desc": "sand"}],
        termination_depth_m=16,
        notes="ENDNOTE",
    )
    pages = page_text(render_log(payload).pdf_bytes)
    assert len(pages) == 2
    assert "ENDNOTE" not in pages[0]
    assert "ENDNOTE" in pages[1]
    assert "Termination depth" in pages[1]


# 8. Excel booleans are not depths


@pytest.mark.parametrize("key", ["depth_per_sheet_m", "termination_depth_m"])
def test_excel_settings_reject_boolean_depths(tmp_path: Path, key: str):
    workbook = build_workbook(synthetic_payload(), filled=True)
    sheet = workbook["Settings"]
    row = next(r for r in range(2, sheet.max_row + 1) if sheet.cell(row=r, column=1).value == key)
    sheet.cell(row=row, column=2, value=True)
    path = tmp_path / "bool.xlsx"
    workbook.save(path)
    with pytest.raises(InputError, match="boolean"):
        read_workbook(path)


# 3. Sparse workbooks are rejected before expansion


def test_sparse_oversized_workbook_rejected_before_expansion(tmp_path: Path):
    workbook = build_workbook(synthetic_payload(), filled=True)
    workbook["Samples"].cell(row=100000, column=100, value=1)
    path = tmp_path / "sparse.xlsx"
    workbook.save(path)
    assert path.stat().st_size < 100_000
    started = time.monotonic()
    with pytest.raises(InputError, match="limit"):
        read_workbook(path)
    assert time.monotonic() - started < 5


def test_formatting_only_rows_do_not_count_toward_sheet_limits(tmp_path: Path):
    from openpyxl.styles import Font

    workbook = build_workbook(synthetic_payload(), filled=True)
    sheet = workbook["Samples"]
    for row in range(2, 8001):
        sheet.cell(row=row, column=1).font = Font(bold=True)
    path = tmp_path / "formatted.xlsx"
    workbook.save(path)
    data = read_workbook(path)
    assert len(data.payload["tests"]) == len(synthetic_payload()["tests"])


# 9. Malformed JSON is a clean error


def test_invalid_encoding_and_deep_json_exit_two(tmp_path: Path, capsys):
    bad_bytes = tmp_path / "bytes.json"
    bad_bytes.write_bytes(b'{"notes": "\xff"}')
    assert main(["validate", str(bad_bytes)]) == 2
    assert "UTF-8" in capsys.readouterr().err

    deep = tmp_path / "deep.json"
    deep.write_text('{"a": ' + "[" * 100_000 + "]" * 100_000 + "}", encoding="utf-8")
    assert main(["validate", str(deep)]) == 2
    assert "nested too deeply" in capsys.readouterr().err


# 10. Extreme numbers are validation errors


@pytest.mark.parametrize(
    "payload",
    [
        {"depth_per_sheet_m": 1e-320, "termination_depth_m": 1},
        {"termination_depth_m": 10**400},
        {"layers": [{"depth_start_m": 0, "depth_end_m": "1e400"}]},
    ],
)
def test_extreme_numbers_raise_payload_error(payload):
    with pytest.raises(PayloadError):
        validate_log(payload)


# 2. Output never touches a guessable temporary name


def _render_args(tmp_path: Path) -> list[str]:
    source = tmp_path / "hole.json"
    source.write_text(json.dumps(base_payload()), encoding="utf-8")
    return ["render", str(source), "--out"]


def test_output_preserves_existing_temp_files_and_symlinks(tmp_path: Path):
    args = _render_args(tmp_path)
    stale = tmp_path / "out.pdf.tmp"
    stale.write_text("keep me", encoding="utf-8")
    assert main(args + [str(tmp_path / "out.pdf")]) == 0
    assert stale.read_text(encoding="utf-8") == "keep me"

    if hasattr(os, "symlink"):
        victim = tmp_path / "victim.txt"
        victim.write_text("untouched", encoding="utf-8")
        (tmp_path / "second.pdf.tmp").symlink_to(victim)
        assert main(args + [str(tmp_path / "second.pdf")]) == 0
        assert victim.read_text(encoding="utf-8") == "untouched"
        assert (tmp_path / "second.pdf").read_bytes().startswith(b"%PDF")

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".") and p.name.endswith(".tmp")]
    assert leftovers == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_output_file_gets_normal_permissions(tmp_path: Path):
    out = tmp_path / "perm.pdf"
    umask = os.umask(0o022)
    try:
        assert main(_render_args(tmp_path) + [str(out)]) == 0
    finally:
        os.umask(umask)
    assert out.stat().st_mode & 0o777 == 0o644


def test_existing_output_is_not_replaced_without_force(tmp_path: Path):
    out = tmp_path / "out.pdf"
    out.write_text("original", encoding="utf-8")
    assert main(_render_args(tmp_path) + [str(out)]) == 2
    assert out.read_text(encoding="utf-8") == "original"
    assert main(_render_args(tmp_path) + [str(out), "--force"]) == 0
    assert out.read_bytes().startswith(b"%PDF")


# 11. Filesystem errors on output are clean errors


def test_invalid_output_parent_returns_clear_error(tmp_path: Path, capsys):
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a folder", encoding="utf-8")
    args = _render_args(tmp_path)
    capsys.readouterr()
    assert main(args + [str(blocked / "out.pdf")]) == 2
    assert "cannot" in capsys.readouterr().err
    assert main(["example", "json", "--out", str(blocked / "x.json")]) == 2
    assert main(["template", "--out", str(blocked / "x.xlsx")]) == 2


# 12. Workflow policy


def test_workflow_actions_are_pinned_and_permissions_explicit():
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"^permissions:", text, re.MULTILINE), path.name
        for ref in re.findall(r"uses:\s*(\S+)", text):
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{path.name}: {ref}"
        header = "\n".join(
            line for line in text.split("\njobs:", 1)[0].splitlines() if not line.lstrip().startswith("#")
        )
        assert "id-token: write" not in header, path.name


# 13. Old package name only where it is meant to be


def test_old_package_names_only_appear_in_allowed_locations():
    allowed = {
        Path("README.md"): "It was first developed as `soil-log`.",
        Path("pyproject.toml"): '"soil-log"]',
    }
    offenders = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if not path.is_file() or relative.parts[0] in {".git", ".venv", "dist", "build"}:
            continue
        if "__pycache__" in relative.parts or relative == Path(__file__).relative_to(ROOT):
            continue
        if path.suffix not in {".py", ".md", ".toml", ".yml", ".json", ".txt", ".in"}:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if re.search(r"soil[_-]log", line) and allowed.get(relative, "\0") not in line:
                offenders.append(f"{relative}:{number}")
    assert offenders == []


# 14. README commands run in sequence


def test_readme_quickstart_commands_run_in_sequence(tmp_path: Path, monkeypatch):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Quickstart", 1)[1].split("## Python API", 1)[0]
    blocks = re.findall(r"```bash\n(.*?)```", section, re.DOTALL)
    commands = [
        shlex.split(line)
        for block in blocks
        for line in block.splitlines()
        if line.startswith("opendrill ") and "<<" not in line and "hole.json" not in line
    ]
    assert len(commands) >= 6
    monkeypatch.chdir(tmp_path)
    for command in commands:
        assert command[0] == "opendrill"
        assert main(command[1:]) == 0, command


# Second review (of cb13a56)


def test_blank_template_draws_nothing_but_the_marked_layer(tmp_path: Path):
    path = tmp_path / "blank.xlsx"
    build_workbook(None, filled=False).save(path)
    data = read_workbook(path)
    assert data.payload["tests"] == []
    assert data.payload["notes"] == ""
    from opendrill.excel_io import input_warnings

    assert any("delete this example row" in warning for warning in input_warnings(data))


def test_two_sample_sheet_aliases_are_an_error(tmp_path: Path):
    workbook = build_workbook(synthetic_payload(), filled=True)
    extra = workbook.copy_worksheet(workbook["Samples"])
    extra.title = "tests"
    path = tmp_path / "aliases.xlsx"
    workbook.save(path)
    with pytest.raises(InputError, match="aliases of the same sheet"):
        read_workbook(path)


def test_a_word_wider_than_the_column_is_broken_to_fit():
    from reportlab.pdfbase import pdfmetrics

    from opendrill.render import _DESC_FS, _wrap_text

    lines = _wrap_text("start " + "X" * 80 + " end", 190)
    assert len(lines) >= 3
    for line in lines:
        assert pdfmetrics.stringWidth(line, "Helvetica", _DESC_FS) <= 190
    assert "".join(lines).replace(" ", "") == "start" + "X" * 80 + "end"


def test_template_without_suffix_prints_the_path_written(tmp_path: Path, capsys):
    target = tmp_path / "nosuffix"
    assert main(["template", "--out", str(target)]) == 0
    written = tmp_path / "nosuffix.xlsx"
    assert written.exists()
    assert f"workbook: {written}" in capsys.readouterr().out


def test_derived_su_keeps_its_source_when_validated_again():
    once = validate_log({"tests": [{"depth_top_m": 1, "depth_bot_m": 1.5, "su_kind": "uc", "uc_kPa": 280}]})
    row = once.payload["tests"][0]
    assert (row["su_kPa"], row["su_source"]) == (140, "uc/2")
    twice = validate_log(once.payload).payload["tests"][0]
    assert (twice["su_kPa"], twice["su_source"]) == (140, "uc/2")

    edited = dict(once.payload, tests=[dict(row, su_kPa=100)])
    assert validate_log(edited).payload["tests"][0]["su_source"] == "given"


def test_unused_strength_reading_is_reported():
    checked = validate_log(
        {"tests": [{"depth_top_m": 1, "depth_bot_m": 1.5, "su_kind": "uc", "uc_kPa": 280, "ppen_kPa": 90}]}
    )
    assert checked.payload["tests"][0]["su_kPa"] == 140
    assert any("ppen_kPa (90 kPa) is kept on the row but not plotted" in w for w in checked.warnings)


@pytest.mark.parametrize("dps", [10.0, 0.3, 2.05, 20.0])
@pytest.mark.parametrize("offset", [0.0, 5e-7, 1e-6, 5e-6, 1e-5, 1.5e-5, 1e-4, 0.01])
def test_a_point_just_past_a_sheet_end_has_exactly_one_page(dps, offset):
    depth = dps + offset
    windows = data_page_windows(depth, dps)
    owners = [w for w in windows if contains_point(depth, *w)]
    assert len(owners) == 1, (dps, offset, windows)
    assert owners[0] == windows[-1]


# Third review


def _inject_into_sheet(source: Path, target: Path, sheet_title: str, xml: str, before: str) -> None:
    """Copy a workbook, inserting raw XML into one worksheet part before ``before``."""
    import zipfile

    from openpyxl import load_workbook

    titles = load_workbook(source).sheetnames
    part = f"xl/worksheets/sheet{titles.index(sheet_title) + 1}.xml"
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item)
            if item.filename == part:
                text = data.decode("utf-8")
                assert before in text, part
                data = text.replace(before, xml + before, 1).encode("utf-8")
            dst.writestr(item, data)


@pytest.mark.parametrize(
    "xml",
    [
        '<mergeCells count="1"><mergeCell ref="A3:CV100000"/></mergeCells>',
        '<mergeCells count="1"><mergeCell ref="A3:BL4500"/></mergeCells>',
    ],
)
def test_oversized_merged_range_rejected_before_loading(tmp_path: Path, xml: str):
    base = tmp_path / "base.xlsx"
    build_workbook(synthetic_payload(), filled=True).save(base)
    bad = tmp_path / "merged.xlsx"
    _inject_into_sheet(base, bad, "Samples", xml, "<pageMargins")
    assert bad.stat().st_size < 100_000
    started = time.monotonic()
    with pytest.raises(InputError):
        read_workbook(bad)
    assert time.monotonic() - started < 5


def test_oversized_hyperlink_range_rejected_before_loading(tmp_path: Path):
    base = tmp_path / "base.xlsx"
    build_workbook(synthetic_payload(), filled=True).save(base)
    bad = tmp_path / "link.xlsx"
    xml = '<hyperlinks><hyperlink ref="A3:CV100000" display="x" location="Layers!A1"/></hyperlinks>'
    _inject_into_sheet(base, bad, "Samples", xml, "<pageMargins")
    started = time.monotonic()
    with pytest.raises(InputError):
        read_workbook(bad)
    assert time.monotonic() - started < 5


def test_small_merged_ranges_still_read(tmp_path: Path):
    workbook = build_workbook(synthetic_payload(), filled=True)
    workbook["Project"].merge_cells("D1:F2")
    path = tmp_path / "merged-ok.xlsx"
    workbook.save(path)
    assert read_workbook(path).payload["layers"]


def test_notes_do_not_overlap_long_shallow_layer_description():
    from opendrill.render import _frame, _layout_page_text, _wrap_paragraphs

    payload = validate_log(
        {
            "layers": [{"depth_start_m": 0, "depth_end_m": 0.1, "desc": "SYNTHETIC description " * 20}],
            "notes": "ENDNOTE",
            "termination_depth_m": 0.1 + 1e-3,
        }
    ).payload
    frame = _frame()
    notes = _wrap_paragraphs(payload["notes"], frame.col_w)
    page = _layout_page_text(payload, (0.0, 20.0), frame, "start", notes)
    desc_baselines = [y for _x, y, text, _f, _s in page.texts if text.startswith("SYNTHETIC")]
    after = [y for _x, y, text, _f, _s in page.texts if not text.startswith("SYNTHETIC")]
    assert desc_baselines and after
    assert max(after) < min(desc_baselines), (min(desc_baselines), max(after))


def test_zero_spacing_with_complete_screen_returns_payload_error(tmp_path: Path, capsys):
    payload = {"piezo": {"top_screen_m": 0, "bottom_screen_m": 1, "screen_line_spacing_m": 0}}
    with pytest.raises(PayloadError):
        validate_log(payload)
    source = tmp_path / "zero.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["validate", str(source)]) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"info": {"COORDINATES (M) N": 10**400}},
        {"tests": [{"depth_top_m": 1, "depth_bot_m": 2, "test": "SPT", "spt2": 10**400, "spt3": 1}]},
        {"depth_per_sheet_m": 5e-324},
        {"depth_per_sheet_m": 0.001},
    ],
)
def test_extreme_coordinates_blows_and_sheet_lengths_fail_cleanly(payload):
    with pytest.raises(PayloadError):
        validate_log(payload)
    with pytest.raises(PayloadError):
        render_log(payload)


def test_json_integer_digit_limit_returns_exit_two(tmp_path: Path, capsys):
    source = tmp_path / "digits.json"
    source.write_text('{"termination_depth_m": ' + "9" * 5000 + "}", encoding="utf-8")
    assert main(["validate", str(source)]) == 2
    assert "number that cannot be read" in capsys.readouterr().err
