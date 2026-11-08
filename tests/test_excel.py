from pathlib import Path

import pytest
from openpyxl import Workbook

from opendrill.errors import InputError
from opendrill.excel_io import build_workbook, describe_payload_error, read_workbook
from opendrill.errors import PayloadError
from opendrill.synthetic import synthetic_payload
from opendrill.validate import validate_payload


def test_roundtrip_preserves_synthetic_fields(tmp_path: Path):
    path = tmp_path / "synthetic.xlsx"
    build_workbook(synthetic_payload(), filled=True).save(path)
    loaded = read_workbook(path)
    again = validate_payload(loaded.payload)
    original = validate_payload(synthetic_payload())
    assert again["layers"] == original["layers"]
    assert again["termination_depth_m"] == 16
    assert again["info"]["HOLE NO"] == "SYN-BH-01"
    assert again["info"]["CRS"] == "SYN-CRS"
    assert again["info"]["HORIZONTAL DATUM"] == "SYN-H"
    assert again["info"]["VERTICAL DATUM"] == "SYN-V"
    assert again["piezo"]["top_screen_m"] == pytest.approx(9.2)
    assert again["piezo"]["bottom_screen_m"] == pytest.approx(12.8)
    assert again["piezo"]["bottom_piezo_m"] == pytest.approx(13.2)
    assert again["tests"][4]["uc_kPa"] == 280
    assert again["tests"][4]["su_kPa"] == 140
    assert again["tests"][5]["ppen_kPa"] == 340
    assert "not N60" in again["notes"]


def test_template_sheets_dropdowns_and_aliases(tmp_path: Path):
    path = tmp_path / "blank.xlsx"
    book = build_workbook(None, filled=False)
    assert book.sheetnames == ["Project", "Layers", "Samples", "Piezo", "Notes", "Settings"]
    assert book.properties.creator == "opendrill"
    samples = book["Samples"]
    assert samples["N1"].value == "su_kind"
    assert samples["O1"].value == "uc_kPa"
    assert len(samples.data_validations.dataValidation) == 2
    book.save(path)
    # Rename sheets to the historical aliases and read them back.
    book["Project"].title = "project info"
    book["Samples"].title = "tests"
    alias_path = tmp_path / "alias.xlsx"
    book.save(alias_path)
    loaded = read_workbook(alias_path)
    assert "info" in loaded.sheet_names
    assert "test" in loaded.sheet_names


def test_duplicate_keys_and_uncached_formulas_fail(tmp_path: Path):
    path = tmp_path / "dup.xlsx"
    book = build_workbook(synthetic_payload(), filled=True)
    sheet = book["Project"]
    sheet.cell(row=30, column=1, value="HOLE NO")
    sheet.cell(row=30, column=2, value="OTHER")
    book.save(path)
    with pytest.raises(InputError, match="duplicate key"):
        read_workbook(path)

    formula = tmp_path / "formula.xlsx"
    built = Workbook()
    ws = built.active
    ws.title = "Layers"
    ws.append(["depth_start_m", "depth_end_m", "soil_type", "desc"])
    ws.append([0, "=1+1", "SAND", "formula row"])
    built.save(formula)
    with pytest.raises(InputError, match="no cached"):
        read_workbook(formula)


def test_excel_error_mentions_the_sheet_row(tmp_path: Path):
    path = tmp_path / "bad.xlsx"
    book = build_workbook({
        "layers": [{"depth_start_m": 0, "depth_end_m": 1, "desc": "ok"},
                   {"depth_start_m": 0.5, "depth_end_m": 2, "desc": "overlap"}],
    }, filled=True)
    book.save(path)
    src = read_workbook(path)
    with pytest.raises(PayloadError) as caught:
        validate_payload(src.payload)
    message = " ".join(describe_payload_error(caught.value, src))
    assert "Layers sheet" in message
    assert "overlap" in message
