"""Headless command line for opendrill.

The process never opens a window and never prompts. Exit status is 0 when a
file was written or a payload validated, and 2 when the input was rejected.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from opendrill.errors import InputError, PayloadError
from opendrill.synthetic import synthetic_payload

_COMMANDS = {"render", "validate", "template", "example"}


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns a process status instead of exiting."""
    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)
    try:
        try:
            if not argv:
                _legacy_parser().print_help(sys.stderr)
                return 2
            if argv[0] in _COMMANDS:
                return _commands(argv)
            return _legacy(argv)
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return 0
            return code if isinstance(code, int) else 2
    except BrokenPipeError:
        _silence_broken_pipe()
        return 0


def console_main() -> None:
    sys.exit(main())


def _legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opendrill",
        description=(
            "Render a soil or borehole log PDF from JSON or an Excel workbook. "
            "Depths are metres. The command does not prompt."
        ),
    )
    parser.add_argument("input", nargs="?", help="JSON file or Excel workbook (.xlsx, .xlsm)")
    parser.add_argument("--out", help="output PDF path (default: input name with .pdf)")
    parser.add_argument("--json", metavar="PATH", help="JSON payload to render")
    parser.add_argument("--template", metavar="XLSX", help="write a blank workbook and exit")
    parser.add_argument("--example", metavar="XLSX", help="write the synthetic example workbook and exit")
    parser.add_argument("--example-pdf", metavar="PDF", help="write the synthetic example PDF and exit")
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output file (without this, an existing file is left untouched)",
    )
    return parser


def _commands(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="opendrill")
    sub = parser.add_subparsers(dest="cmd", required=True)

    render = sub.add_parser("render", help="render a PDF from JSON or Excel")
    render.add_argument("input", help="path to .json, .xlsx, .xlsm, or - for stdin JSON")
    render.add_argument("--out", "-o", help="PDF path, or - for stdout")
    render.add_argument("--force", action="store_true")

    validate = sub.add_parser("validate", help="check a payload and print warnings")
    validate.add_argument("input", help="path to .json, .xlsx, .xlsm, or - for stdin JSON")

    template = sub.add_parser("template", help="write a blank Excel template")
    template.add_argument("--out", "-o", required=True)
    template.add_argument("--force", action="store_true")

    example = sub.add_parser("example", help="write the synthetic example")
    example.add_argument("kind", choices=("json", "xlsx", "pdf"))
    example.add_argument("--out", "-o", required=True)
    example.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "render":
        return _render(args.input, args.out, args.force)
    if args.cmd == "validate":
        return _validate(args.input)
    if args.cmd == "template":
        return _write_template(Path(args.out), args.force)
    return _write_example(args.kind, Path(args.out), args.force)


def _legacy(argv: list[str]) -> int:
    args = _legacy_parser().parse_args(argv)
    if args.template:
        return _write_template(Path(args.template), args.force)
    if args.example:
        return _write_example("xlsx", Path(args.example), args.force)
    if args.example_pdf:
        return _write_example("pdf", Path(args.example_pdf), args.force)
    if args.json:
        return _render(args.json, args.out, args.force)
    if not args.input:
        _legacy_parser().print_help(sys.stderr)
        return 2
    return _render(args.input, args.out, args.force)


def _die(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _render(source: str, out: str | None, force: bool) -> int:
    try:
        payload, workbook, warnings = _load(source)
    except InputError as exc:
        return _die(str(exc))
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    from opendrill.render import render_log

    try:
        result = render_log(payload)
    except PayloadError as exc:
        return _die(_payload_message(source, exc, workbook))
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    try:
        destination = _pdf_destination(source, out)
        _emit_pdf(destination, result.pdf_bytes, force)
    except InputError as exc:
        return _die(str(exc))
    if destination is None:
        return 0
    print(f"pdf: {destination}  ({len(result.pdf_bytes):,} bytes, {result.page_count} pages)")
    return 0


def _validate(source: str) -> int:
    try:
        payload, workbook, warnings = _load(source)
    except InputError as exc:
        return _die(str(exc))
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    from opendrill.layout import data_page_windows, log_extent_m
    from opendrill.validate import validate_log

    try:
        checked = validate_log(payload)
    except PayloadError as exc:
        return _die(_payload_message(source, exc, workbook))
    for warning in checked.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    extent = log_extent_m(checked.payload)
    dps = float(checked.payload["depth_per_sheet_m"])
    pages = data_page_windows(extent, dps)
    layers = len(checked.payload.get("layers") or [])
    tests = len(checked.payload.get("tests") or [])
    print(
        f"valid: {layers} layers, {tests} samples, extent {extent:g} m, "
        f"{len(pages)} depth sheet(s) at {dps:g} m/sheet"
    )
    return 0


def _write_template(path: Path, force: bool) -> int:
    from opendrill.excel_io import build_workbook

    try:
        _save_workbook(build_workbook(None, filled=False), path, force)
    except InputError as exc:
        return _die(str(exc))
    print(f"workbook: {path}")
    return 0


def _write_example(kind: str, path: Path, force: bool) -> int:
    payload = synthetic_payload()
    if kind == "json":
        try:
            _write_text(path, json.dumps(payload, indent=2) + "\n", force)
        except InputError as exc:
            return _die(str(exc))
        print(f"json: {path}")
        return 0
    if kind == "xlsx":
        from opendrill.excel_io import build_workbook

        try:
            _save_workbook(build_workbook(payload, filled=True), path, force)
        except InputError as exc:
            return _die(str(exc))
        print(f"workbook: {path}")
        return 0
    from opendrill.render import render_log

    result = render_log(payload)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    try:
        _emit_pdf(path, result.pdf_bytes, force)
    except InputError as exc:
        return _die(str(exc))
    print(f"pdf: {path}  ({len(result.pdf_bytes):,} bytes, {result.page_count} pages)")
    return 0


def _load(source: str):
    if source == "-":
        if sys.stdin.isatty():
            raise InputError("stdin is a terminal; pass a JSON file or pipe a payload")
        text = sys.stdin.read()
        payload = _parse_json(text, "stdin")
        return payload, None, []
    path = Path(source).expanduser()
    if not path.exists():
        raise InputError(f"no such file: {path}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise InputError(f"cannot read {path}: {exc}") from exc
        return _parse_json(text, path.name), None, []
    if suffix in (".xlsx", ".xlsm"):
        from opendrill.excel_io import input_warnings, read_workbook

        workbook = read_workbook(path)
        return workbook.payload, workbook, input_warnings(workbook)
    raise InputError(
        f"unsupported file type {path.suffix!r}; expected .json, .xlsx, or .xlsm"
    )


def _parse_json(text: str, label: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{label}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise InputError(f"{label}: JSON root must be an object")
    return data


def _payload_message(source: str, exc: PayloadError, workbook) -> str:
    if workbook is not None:
        from opendrill.excel_io import describe_payload_error

        lines = describe_payload_error(exc, workbook)
    else:
        lines = []
        for loc, msg, value in exc.errors:
            got = f" (got {value!r})" if value is not None else ""
            where = ".".join(str(part) for part in loc)
            lines.append(f"{where}: {msg}{got}" if where else f"{msg}{got}")
    name = source if source != "-" else "stdin"
    return f"{name} has {len(lines)} problem(s):\n  " + "\n  ".join(lines)


def _pdf_destination(source: str, out: str | None) -> Path | None:
    if out == "-":
        return None
    if out:
        return Path(out).expanduser()
    if source == "-":
        raise InputError("reading JSON from stdin requires --out")
    return Path(source).expanduser().with_suffix(".pdf")


def _silence_broken_pipe() -> None:
    """Point stdout at /dev/null so a closed pipe does not raise again on shutdown."""
    try:
        sys.stdout.close()
    except Exception:
        pass
    try:
        null = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null, 1)
        finally:
            os.close(null)
    except Exception:
        pass


def _emit_pdf(path: Path | None, data: bytes, force: bool) -> None:
    if path is None:
        if sys.stdout.isatty():
            raise InputError("refusing to write a PDF to a terminal; pass --out")
        try:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            _silence_broken_pipe()
            raise
        return
    _refuse_overwrite(path, force)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    except PermissionError as exc:
        raise InputError(f"cannot write {path}: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_text(path: Path, text: str, force: bool) -> None:
    _refuse_overwrite(path, force)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _save_workbook(workbook, path: Path, force: bool) -> None:
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        path = path.with_suffix(".xlsx")
    _refuse_overwrite(path, force)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        workbook.save(temporary)
        temporary.replace(path)
    except PermissionError as exc:
        raise InputError(f"cannot write {path}: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _refuse_overwrite(path: Path, force: bool) -> None:
    if path.exists() and not force:
        raise InputError(
            f"{path} already exists; pass --force to replace it. The existing file was not modified."
        )
