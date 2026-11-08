import json
from pathlib import Path

from opendrill.cli import main
from opendrill.synthetic import synthetic_payload


def test_render_json_and_reject_invalid_input(tmp_path: Path, capsys):
    source = tmp_path / "hole.json"
    source.write_text(json.dumps(synthetic_payload()), encoding="utf-8")
    out = tmp_path / "hole.pdf"
    assert main(["render", str(source), "--out", str(out)]) == 0
    assert out.read_bytes().startswith(b"%PDF")
    captured = capsys.readouterr()
    assert "pdf:" in captured.out

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"layers": [{"depth_start_m": 2, "depth_end_m": 1}]}), encoding="utf-8")
    assert main(["render", str(bad), "--out", str(tmp_path / "no.pdf")]) == 2
    err = capsys.readouterr().err
    assert "depth_end_m" in err
    assert "metres" in err
    assert not (tmp_path / "no.pdf").exists()


def test_overwrite_requires_force(tmp_path: Path, capsys):
    source = tmp_path / "hole.json"
    source.write_text(json.dumps({"layers": [{"depth_start_m": 0, "depth_end_m": 1, "desc": "a"}]}), encoding="utf-8")
    out = tmp_path / "hole.pdf"
    assert main(["render", str(source), "--out", str(out)]) == 0
    first = out.read_bytes()
    assert main(["render", str(source), "--out", str(out)]) == 2
    assert "already exists" in capsys.readouterr().err
    assert out.read_bytes() == first
    assert main(["render", str(source), "--out", str(out), "--force"]) == 0


def test_example_template_validate_and_legacy_flags(tmp_path: Path, capsys):
    pdf = tmp_path / "example.pdf"
    workbook = tmp_path / "example.xlsx"
    js = tmp_path / "example.json"
    blank = tmp_path / "blank.xlsx"
    assert main(["example", "pdf", "--out", str(pdf)]) == 0
    assert pdf.stat().st_size > 1000
    assert main(["example", "xlsx", "--out", str(workbook)]) == 0
    assert main(["example", "json", "--out", str(js)]) == 0
    assert json.loads(js.read_text(encoding="utf-8"))["info"]["HOLE NO"] == "SYN-BH-01"
    assert main(["template", "--out", str(blank)]) == 0
    assert main(["validate", str(js)]) == 0
    assert "valid:" in capsys.readouterr().out

    legacy_pdf = tmp_path / "legacy.pdf"
    assert main(["--example-pdf", str(legacy_pdf)]) == 0
    assert legacy_pdf.read_bytes().startswith(b"%PDF")
    rendered = tmp_path / "from-xlsx.pdf"
    assert main([str(workbook), "--out", str(rendered)]) == 0
    assert rendered.read_bytes().startswith(b"%PDF")


def test_stdout_broken_pipe_exits_cleanly(tmp_path: Path):
    import os
    import subprocess
    import sys

    source = tmp_path / "hole.json"
    source.write_text(
        json.dumps({"layers": [{"depth_start_m": 0, "depth_end_m": 1, "soil_type": "SAND", "desc": "a"}]}),
        encoding="utf-8",
    )
    env = os.environ.copy()
    root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-m", "opendrill", "render", str(source), "--out", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.stdout is not None
    proc.stdout.close()
    err = proc.stderr.read() if proc.stderr is not None else b""
    code = proc.wait(timeout=30)
    assert code == 0
    assert b"Traceback" not in err


def test_missing_file_and_bad_type(tmp_path: Path, capsys):
    assert main(["render", str(tmp_path / "missing.json"), "--out", str(tmp_path / "x.pdf")]) == 2
    assert "no such file" in capsys.readouterr().err
    odd = tmp_path / "notes.txt"
    odd.write_text("{}", encoding="utf-8")
    assert main(["render", str(odd), "--out", str(tmp_path / "x.pdf")]) == 2
    assert "unsupported" in capsys.readouterr().err
    assert main([]) == 2


def test_checked_in_example_matches_the_payload():
    data = json.loads(Path("examples/synthetic_borehole.json").read_text(encoding="utf-8"))
    assert data == synthetic_payload()
