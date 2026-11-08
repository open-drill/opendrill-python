import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_validate_import_does_not_load_pdf_excel_or_gui():
    code = (
        "import opendrill.validate, sys\n"
        "banned = ('reportlab', 'openpyxl', 'tkinter', 'matplotlib', 'PIL')\n"
        "loaded = [name for name in banned if name in sys.modules]\n"
        "print(','.join(loaded))\n"
        "raise SystemExit(0 if not loaded else 1)\n"
    )
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() in ("", "[]")
