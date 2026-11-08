"""Workbook preflight rejects unsafe inputs before openpyxl expands cells."""
import struct
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

import opendrill.excel_io as excel_io
from opendrill.cli import main
from opendrill.errors import InputError


@pytest.fixture
def workbook_path(tmp_path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Layers"
    sheet.append(["depth_start_m", "depth_end_m"])
    sheet.append([0, 1])
    path = tmp_path / "base.xlsx"
    workbook.save(path)
    return path


def rewrite_sheet(source, target, *, part="xl/worksheets/sheet1.xml", reference=None,
                  relative=False):
    original = "xl/worksheets/sheet1.xml"
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            name = item.filename
            if name == original:
                name = part
                if reference is not None:
                    xml = f'<mergeCells count="1"><mergeCell ref="{reference}"/></mergeCells>'
                    data = data.replace(b"</worksheet>", xml.encode() + b"</worksheet>")
            elif name == "xl/_rels/workbook.xml.rels":
                rel_target = part.removeprefix("xl/") if relative else "/" + part
                data = data.replace(("/" + original).encode(), rel_target.encode())
            elif name == "[Content_Types].xml":
                data = data.replace(("/" + original).encode(), ("/" + part).encode())
            dst.writestr(name, data)


@pytest.mark.parametrize("part", ["xl/worksheets/nested/sheet1.xml", "xl/custom/sheet.data"])
@pytest.mark.parametrize("relative", [False, True])
def test_relocated_worksheet_cannot_bypass_expansion_limits(workbook_path, tmp_path, monkeypatch,
                                                          part, relative):
    path = tmp_path / "relocated.xlsx"
    rewrite_sheet(workbook_path, path, part=part, reference="A3:CV100000", relative=relative)

    def unexpected_load(*args, **kwargs):
        pytest.fail("openpyxl must not load a workbook that fails preflight")

    monkeypatch.setattr(excel_io, "load_workbook", unexpected_load)
    with pytest.raises(InputError, match="limit"):
        excel_io.read_workbook(path)
    assert main(["validate", str(path)]) == 2


@pytest.mark.parametrize("relative", [False, True])
def test_small_relocated_worksheet_still_reads(workbook_path, tmp_path, relative):
    path = tmp_path / "relocated.xlsx"
    rewrite_sheet(workbook_path, path, part="xl/custom/sheet.data", reference="A3:B4",
                  relative=relative)
    assert excel_io.read_workbook(path).payload["layers"] == [
        {"depth_start_m": 0, "depth_end_m": 1}
    ]


@pytest.mark.parametrize("reference", [" ", "", "A1 B2", "invalid", "B2:A1", "A0:A1"])
def test_malformed_merge_reference_returns_exit_two(workbook_path, tmp_path, reference, capsys):
    path = tmp_path / "invalid-range.xlsx"
    rewrite_sheet(workbook_path, path, reference=reference)
    with pytest.raises(InputError, match="invalid.*range"):
        excel_io.read_workbook(path)
    assert main(["validate", str(path)]) == 2
    assert "invalid" in capsys.readouterr().err


def test_corrupt_worksheet_crc_returns_exit_two(workbook_path, tmp_path, capsys):
    path = tmp_path / "crc.xlsx"
    with zipfile.ZipFile(workbook_path) as src, zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as dst:
        for item in src.infolist():
            dst.writestr(item.filename, src.read(item.filename))
    with zipfile.ZipFile(path) as archive:
        header = archive.getinfo("xl/worksheets/sheet1.xml").header_offset
    data = bytearray(path.read_bytes())
    name_size, extra_size = struct.unpack_from("<HH", data, header + 26)
    data[header + 30 + name_size + extra_size] ^= 1
    path.write_bytes(data)
    with pytest.raises(InputError, match="CRC"):
        excel_io.read_workbook(path)
    assert main(["validate", str(path)]) == 2
    assert "CRC" in capsys.readouterr().err
