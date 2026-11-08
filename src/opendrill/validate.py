"""Normalise a opendrill payload and reject values that cannot be plotted honestly.

Units, with no conversion:
- depths, coordinates, elevation, and termination are metres
- ``su_kPa``, ``uc_kPa``, and ``ppen_kPa`` are kilopascals
- ``recovery``, ``fines_pct``, ``wp_pct``, ``w_pct``, and ``wl_pct`` are literal percent

``su_kPa`` is the value drawn on the Su axis. It is never halved. The template
legend reads UC/2 and P.PEN/2: those symbols mean an Su estimate equal to half
of a measured unconfined compressive strength or pocket-penetrometer reading.
If ``su_kPa`` is omitted and ``su_kind`` is ``uc`` or ``ppen``, the plotted Su
is ``uc_kPa / 2`` or ``ppen_kPa / 2`` and ``su_source`` records that. A value
already supplied in ``su_kPa`` is left unchanged.

SPT blow counts are whole numbers of the template's 6-inch increments.
N plotted on the log is ``spt2 + spt3`` and is not N60.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from opendrill.errors import PayloadError
from opendrill.layout import MAX_PAGE_LINES, MAX_PAGES, DEPTH_TOL_M, log_extent_m, sheet_count
from opendrill.series import is_spt

SOIL_TYPES = ("ASPHALT", "CLAY", "GRAVEL", "SAND", "BACKFILL")
SU_KINDS = ("field_peak", "field_remold", "lab_peak", "lab_remold", "uc", "ppen")
# Dropdown suggestions from the original workbook. Any other text is printed as entered.
TEST_TYPES = ("SPT", "SHELBY", "UC2", "VANE")

_TEST_INT_FIELDS = ("no", "spt1", "spt2", "spt3")
_TEST_FLOAT_FIELDS = (
    "depth_top_m",
    "depth_bot_m",
    "recovery",
    "wp_pct",
    "wl_pct",
    "w_pct",
    "fines_pct",
    "su_kPa",
    "uc_kPa",
    "ppen_kPa",
)
_PIEZO_FIELDS = (
    "bottom_depth_m",
    "bottom_piezo_m",
    "top_screen_m",
    "bottom_screen_m",
    "screen_line_spacing_m",
)
_MEASUREMENT_FIELDS = (
    "no",
    "test",
    "recovery",
    "spt1",
    "spt2",
    "spt3",
    "wp_pct",
    "w_pct",
    "wl_pct",
    "fines_pct",
    "su_kPa",
    "su_kind",
    "uc_kPa",
    "ppen_kPa",
)

_MISSING = object()


@dataclass(frozen=True)
class Validation:
    """Normalised payload plus warnings that do not by themselves reject the log."""

    payload: dict
    warnings: tuple[str, ...]


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("must be a finite number")
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError as exc:
            raise ValueError("must be a finite number") from exc
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except (ValueError, OverflowError) as exc:
            raise ValueError("must be a finite number") from exc
    else:
        raise ValueError("must be a finite number")
    if not math.isfinite(number):
        raise ValueError("must be a finite number")
    return number


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("must be a whole number")
    if isinstance(value, int):
        return value
    number = _as_float(value)
    if not number.is_integer():
        raise ValueError("must be a whole number")
    return int(number)


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def validate_log(payload: dict) -> Validation:
    """Validate ``payload`` and return the normalised copy plus warnings."""
    if not isinstance(payload, dict):
        raise PayloadError([((), "payload must be an object", payload)])
    errors: list[tuple[tuple, str, object]] = []
    warnings: list[str] = []

    def num(value, loc, conv=_as_float, required=False, ge=None, gt=None, le=None, unit=None):
        if not _present(value):
            if required:
                errors.append((loc, "required value is missing", value))
            return None
        try:
            converted = conv(value)
        except ValueError as exc:
            errors.append((loc, str(exc), value))
            return None
        suffix = f" {unit}" if unit else ""
        if ge is not None and converted < ge:
            errors.append((loc, f"must be >= {ge}{suffix}", value))
        if gt is not None and converted <= gt:
            errors.append((loc, f"must be > {gt}{suffix}", value))
        if le is not None and converted > le:
            errors.append((loc, f"must be <= {le}{suffix}", value))
        return converted

    out = dict(payload)
    out.pop("su_source", None)

    dps = payload.get("depth_per_sheet_m", _MISSING)
    if dps is _MISSING or dps is None or (isinstance(dps, str) and not str(dps).strip()):
        out["depth_per_sheet_m"] = 20.0
    else:
        parsed = num(dps, ("depth_per_sheet_m",), gt=0, unit="metres")
        out["depth_per_sheet_m"] = 20.0 if parsed is None else parsed

    info_in = payload.get("info") or {}
    if not isinstance(info_in, dict):
        errors.append((("info",), "must be an object of field names to values", info_in))
        info_in = {}
    info = {str(key).strip().upper(): value for key, value in info_in.items()}
    _check_info_number(info, "WATER LEVEL (M)", errors, ge=0, unit="metres")
    _check_info_number(info, "GROUND ELEV. (M)", errors, ge=None, unit="metres")
    for coord_key in ("COORDINATES (M) N", "COORDINATES (M) E"):
        _check_optional_finite(info, coord_key, errors)
    out["info"] = info

    notes_in = payload.get("notes")
    if notes_in is None:
        out["notes"] = ""
    elif isinstance(notes_in, str):
        out["notes"] = notes_in
    elif isinstance(notes_in, list) and all(isinstance(line, str) for line in notes_in):
        out["notes"] = "\n".join(notes_in)
    else:
        errors.append((("notes",), "must be a string or a list of strings", notes_in))
        out["notes"] = ""

    term = num(payload.get("termination_depth_m"), ("termination_depth_m",), ge=0, unit="metres")
    out["termination_depth_m"] = term

    layers = _layers(payload.get("layers") or [], num, errors)
    out["layers"] = layers
    _check_layer_geometry(layers, errors)

    if "tests" in payload and "samples" in payload:
        errors.append((("tests",), "provide tests or samples, not both", None))
        tests_in: object = []
    elif "samples" in payload and "tests" not in payload:
        tests_in = payload.get("samples")
    else:
        tests_in = payload.get("tests") or []
    tests = _tests(tests_in, num, errors, warnings)
    out["tests"] = tests
    # "samples" is an input alias. The normalised payload carries only
    # "tests", so it can be validated and rendered again.
    out.pop("samples", None)

    piezo_in = payload.get("piezo") or {}
    if not isinstance(piezo_in, dict):
        errors.append((("piezo",), "must be an object", piezo_in))
        piezo_in = {}
    piezo: dict = {}
    for field in _PIEZO_FIELDS:
        limit_gt = 0 if field == "screen_line_spacing_m" else None
        limit_ge = 0 if field != "screen_line_spacing_m" else None
        piezo[field] = num(
            piezo_in.get(field),
            ("piezo", field),
            gt=limit_gt,
            ge=limit_ge,
            unit="metres",
        )
    _check_piezo(piezo, errors, warnings)
    out["piezo"] = piezo

    if term is not None:
        deepest_data = _deepest_without_termination(out)
        if deepest_data is not None and term + DEPTH_TOL_M < deepest_data:
            warnings.append(
                "termination_depth_m "
                f"({format(term, 'g')} m) is shallower than other log data "
                f"({format(deepest_data, 'g')} m); pagination includes the deeper data"
            )

    dps_value = out.get("depth_per_sheet_m")
    if isinstance(dps_value, (int, float)) and math.isfinite(dps_value) and dps_value > 0:
        extent = log_extent_m(out)
        pages = sheet_count(extent, float(dps_value))
        if pages > MAX_PAGES:
            errors.append((
                ("depth_per_sheet_m",),
                f"value {dps_value:g} m would create more than {MAX_PAGES} pages for an "
                f"extent of {extent:g} m; increase depth_per_sheet_m",
                dps_value,
            ))

    if errors:
        raise PayloadError(errors)
    return Validation(out, tuple(warnings))


def validate_payload(payload: dict) -> dict:
    """Return the normalised payload. Raises :class:`PayloadError` on failure."""
    return validate_log(payload).payload


def _check_info_number(info: dict, key: str, errors: list, *, ge: float | None, unit: str) -> None:
    value = info.get(key, "")
    if not _present(value):
        info[key] = ""
        return
    try:
        number = _as_float(value)
    except ValueError:
        errors.append((("info", key), f"must be a finite number ({unit})", value))
        return
    if ge is not None and number < ge:
        errors.append((("info", key), f"must be >= {ge} {unit}", value))
        return
    info[key] = int(number) if number.is_integer() else number


def _check_optional_finite(info: dict, key: str, errors: list) -> None:
    """Coordinates may be numbers or free text. Numbers must be finite. Nothing is invented."""
    value = info.get(key, "")
    if not _present(value):
        info[key] = ""
        return
    if isinstance(value, bool):
        errors.append((("info", key), "must be a finite number or text", value))
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            errors.append((("info", key), "must be a finite number", value))
            return
        number = float(value)
        info[key] = int(number) if number.is_integer() else number
        return
    info[key] = str(value).strip()


def _layers(rows: object, num, errors: list) -> list[dict]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        errors.append((("layers",), "must be a list", rows))
        return []
    layers = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append((("layers", index), "must be an object", row))
            layers.append({
                "depth_start_m": None,
                "depth_end_m": None,
                "desc": "",
                "soil_type": None,
            })
            continue
        item = dict(row)
        item["depth_start_m"] = num(
            row.get("depth_start_m"),
            ("layers", index, "depth_start_m"),
            required=True,
            ge=0,
            unit="metres",
        )
        item["depth_end_m"] = num(
            row.get("depth_end_m"),
            ("layers", index, "depth_end_m"),
            required=True,
            ge=0,
            unit="metres",
        )
        start = item["depth_start_m"]
        end = item["depth_end_m"]
        if start is not None and end is not None and end < start:
            errors.append((
                ("layers", index, "depth_end_m"),
                "depth_end_m must be >= depth_start_m (metres); zero thickness is allowed",
                row.get("depth_end_m"),
            ))
        item["desc"] = "" if row.get("desc") is None else str(row.get("desc"))
        soil = row.get("soil_type")
        if not _present(soil):
            item["soil_type"] = None
        elif str(soil).strip().upper() in SOIL_TYPES:
            item["soil_type"] = str(soil).strip().upper()
        else:
            errors.append((
                ("layers", index, "soil_type"),
                f"must be one of {', '.join(SOIL_TYPES)}",
                soil,
            ))
            item["soil_type"] = None
        layers.append(item)
    return layers


def _check_layer_geometry(layers: list[dict], errors: list) -> None:
    ok = [
        layer for layer in layers
        if layer["depth_start_m"] is not None and layer["depth_end_m"] is not None
    ]
    ok.sort(key=lambda layer: (layer["depth_start_m"], layer["depth_end_m"]))
    for left, right in zip(ok, ok[1:]):
        same_point = (
            abs(left["depth_start_m"] - left["depth_end_m"]) <= DEPTH_TOL_M
            and abs(right["depth_start_m"] - right["depth_end_m"]) <= DEPTH_TOL_M
            and abs(left["depth_start_m"] - right["depth_start_m"]) <= DEPTH_TOL_M
        )
        if same_point:
            errors.append((
                (),
                "duplicate zero-thickness layer at "
                f"{left['depth_start_m']:g} m",
                None,
            ))
        elif right["depth_start_m"] < left["depth_end_m"] - DEPTH_TOL_M:
            errors.append((
                (),
                "layer overlap: "
                f"[{left['depth_start_m']:g}, {left['depth_end_m']:g}] m and "
                f"[{right['depth_start_m']:g}, {right['depth_end_m']:g}] m",
                None,
            ))


def _tests(rows: object, num, errors: list, warnings: list[str]) -> list[dict]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        errors.append((("tests",), "must be a list", rows))
        return []
    tests = []
    for index, row in enumerate(rows):
        loc_row = ("tests", index)
        if not isinstance(row, dict):
            errors.append((loc_row, "must be an object", row))
            continue
        if not any(_present(row.get(field)) for field in _MEASUREMENT_FIELDS) and not any(
            _present(row.get(field)) for field in ("depth_top_m", "depth_bot_m")
        ):
            continue
        item = dict(row)
        prior_source = item.pop("su_source", None)
        for field in _TEST_INT_FIELDS:
            lower = 0 if field in ("spt1", "spt2", "spt3") else None
            unit = "blows" if field in ("spt1", "spt2", "spt3") else None
            item[field] = num(row.get(field), (*loc_row, field), conv=_as_int, ge=lower, unit=unit)
        for field in _TEST_FLOAT_FIELDS:
            if field in ("depth_top_m", "depth_bot_m"):
                unit = "metres"
            elif field in ("su_kPa", "uc_kPa", "ppen_kPa"):
                unit = "kPa"
            elif field in ("recovery", "fines_pct", "wp_pct", "w_pct", "wl_pct"):
                unit = "percent"
            else:
                unit = None
            ge = 0 if unit else None
            le = 100 if field in ("recovery", "fines_pct") else None
            item[field] = num(row.get(field), (*loc_row, field), ge=ge, le=le, unit=unit)
        _check_sample_interval(item, index, errors)
        if item["wp_pct"] is not None and item["wl_pct"] is not None and item["wp_pct"] > item["wl_pct"]:
            errors.append((
                (*loc_row, "wp_pct"),
                "plastic limit must be <= liquid limit (wl_pct); both are percent",
                row.get("wp_pct"),
            ))
        test_name = row.get("test")
        item["test"] = None if not _present(test_name) else str(test_name).strip()
        kind = row.get("su_kind")
        if not _present(kind):
            item["su_kind"] = None
        elif str(kind).strip().lower() in SU_KINDS:
            item["su_kind"] = str(kind).strip().lower()
        else:
            errors.append((
                (*loc_row, "su_kind"),
                f"must be one of {', '.join(SU_KINDS)}",
                kind,
            ))
            item["su_kind"] = None
        _apply_strength(item, index, warnings, prior_source)
        if is_spt(item):
            has_2 = item["spt2"] is not None
            has_3 = item["spt3"] is not None
            if has_2 != has_3 or (item["spt1"] is not None and not (has_2 and has_3)):
                warnings.append(
                    f"tests.{index}: SPT blow counts are incomplete; "
                    "N = spt2 + spt3 is plotted only when both spt2 and spt3 are set "
                    "(raw 6-inch increments, not N60)"
                )
        elif any(item[field] is not None for field in ("spt1", "spt2", "spt3")):
            warnings.append(
                f"tests.{index}: spt1/spt2/spt3 are plotted only when test is SPT "
                f"(this row is {item['test']!r}); blow counts were not plotted"
            )
        tests.append(item)
    return tests


def _check_sample_interval(item: dict, index: int, errors: list) -> None:
    top = item["depth_top_m"]
    bot = item["depth_bot_m"]
    has_other = any(_present(item.get(field)) for field in _MEASUREMENT_FIELDS)
    if top is None and bot is None:
        if has_other:
            errors.append((
                ("tests", index, "depth_top_m"),
                "depth_top_m and depth_bot_m are required when a sample has measurements (metres)",
                None,
            ))
        return
    if top is None or bot is None:
        missing = "depth_bot_m" if bot is None else "depth_top_m"
        errors.append((
            ("tests", index, missing),
            "depth_top_m and depth_bot_m must both be set (metres)",
            None,
        ))
        return
    if bot < top:
        errors.append((
            ("tests", index, "depth_bot_m"),
            "depth_bot_m must be >= depth_top_m (metres)",
            bot,
        ))


def _apply_strength(item: dict, index: int, warnings: list[str], prior_source: object = None) -> None:
    """Plot ``su_kPa`` as entered. Derive Su from uc/ppen only when it was omitted.

    ``prior_source`` is the ``su_source`` already on the row. A payload that
    was validated before carries the derived ``su_kPa``; when it still equals
    half of the matching reading, the ``uc/2`` or ``ppen/2`` label is kept
    instead of being relabelled ``given``.
    """
    kind = item.get("su_kind")
    su = item.get("su_kPa")
    uc = item.get("uc_kPa")
    ppen = item.get("ppen_kPa")
    if su is not None:
        derived_from = {"uc/2": ("uc", uc), "ppen/2": ("ppen", ppen)}.get(str(prior_source))
        if (
            derived_from is not None
            and kind == derived_from[0]
            and derived_from[1] is not None
            and math.isclose(su, derived_from[1] / 2.0, rel_tol=1e-9, abs_tol=1e-9)
        ):
            item["su_source"] = prior_source
            return
        item["su_source"] = "given"
        if not kind:
            warnings.append(
                f"tests.{index}: su_kPa is set ({su:g} kPa) but su_kind is missing; "
                "no Su point is plotted"
            )
        elif kind == "uc" and uc is not None:
            _warn_if_half_disagrees(warnings, index, "uc_kPa", su, uc)
        elif kind == "ppen" and ppen is not None:
            _warn_if_half_disagrees(warnings, index, "ppen_kPa", su, ppen)
        else:
            if uc is not None and kind != "uc":
                warnings.append(
                    f"tests.{index}: uc_kPa is not used for the Su point because su_kind is "
                    f"{kind or 'missing'}; su_kPa is plotted as entered and is not halved"
                )
            if ppen is not None and kind != "ppen":
                warnings.append(
                    f"tests.{index}: ppen_kPa is not used for the Su point because su_kind is "
                    f"{kind or 'missing'}; su_kPa is plotted as entered and is not halved"
                )
        return
    if kind == "uc" and uc is not None:
        item["su_kPa"] = uc / 2.0
        item["su_source"] = "uc/2"
        if ppen is not None:
            warnings.append(
                f"tests.{index}: su_kind is uc, so Su is uc_kPa / 2; ppen_kPa "
                f"({ppen:g} kPa) is kept on the row but not plotted"
            )
        return
    if kind == "ppen" and ppen is not None:
        item["su_kPa"] = ppen / 2.0
        item["su_source"] = "ppen/2"
        if uc is not None:
            warnings.append(
                f"tests.{index}: su_kind is ppen, so Su is ppen_kPa / 2; uc_kPa "
                f"({uc:g} kPa) is kept on the row but not plotted"
            )
        return
    item["su_source"] = None
    if kind:
        warnings.append(
            f"tests.{index}: su_kind is {kind} but su_kPa is missing"
            + (
                " (uc_kPa or ppen_kPa would be halved only for kind uc or ppen)"
                if kind in ("uc", "ppen")
                else ""
            )
            + "; no Su point is plotted"
        )
    elif uc is not None or ppen is not None:
        warnings.append(
            f"tests.{index}: uc_kPa/ppen_kPa is not plotted without su_kind "
            "'uc' or 'ppen', and su_kPa was not supplied"
        )


def _warn_if_half_disagrees(warnings: list[str], index: int, raw_name: str, su: float, raw: float) -> None:
    half = raw / 2.0
    tolerance = max(0.05, abs(half) * 1e-6)
    if abs(su - half) > tolerance:
        warnings.append(
            f"tests.{index}: su_kPa is plotted as entered ({su:g} kPa) and was not halved; "
            f"{raw_name} / 2 is {half:g} kPa. The legend UC/2 and P.PEN/2 describes that "
            "derivation, which is used only when su_kPa is omitted"
        )


def _check_piezo(piezo: dict, errors: list, warnings: list[str]) -> None:
    top = piezo.get("top_screen_m")
    bottom = piezo.get("bottom_screen_m")
    if (top is None) ^ (bottom is None):
        missing = "bottom_screen_m" if bottom is None else "top_screen_m"
        errors.append((
            ("piezo", missing),
            "top_screen_m and bottom_screen_m must both be set (metres)",
            None,
        ))
    elif top is not None and bottom is not None and bottom <= top:
        errors.append((
            ("piezo", "bottom_screen_m"),
            "bottom_screen_m must be > top_screen_m (metres)",
            bottom,
        ))
    spacing = piezo.get("screen_line_spacing_m")
    if top is not None and bottom is not None and spacing is not None and bottom > top:
        if (bottom - top) / spacing > MAX_PAGE_LINES:
            errors.append((
                ("piezo", "screen_line_spacing_m"),
                f"would draw more than {MAX_PAGE_LINES} screen lines; "
                f"use a spacing of at least {(bottom - top) / MAX_PAGE_LINES:g} metres",
                spacing,
            ))
    hole = piezo.get("bottom_depth_m")
    if top is not None and bottom is not None and hole is not None:
        if top < -DEPTH_TOL_M or bottom > hole + DEPTH_TOL_M:
            warnings.append(
                "piezo screen interval "
                f"[{top:g}, {bottom:g}] m extends outside the backfill depth "
                f"{hole:g} m; it is still drawn"
            )
    casing = piezo.get("bottom_piezo_m")
    if hole is not None and casing is not None and casing > hole + DEPTH_TOL_M:
        warnings.append(
            f"piezo bottom_piezo_m ({casing:g} m) is deeper than bottom_depth_m "
            f"({hole:g} m); both are still drawn"
        )
    if casing is not None and bottom is not None and bottom > casing + DEPTH_TOL_M:
        warnings.append(
            f"piezo bottom_screen_m ({bottom:g} m) is deeper than bottom_piezo_m "
            f"({casing:g} m); the screen is still drawn"
        )


def _deepest_without_termination(payload: dict) -> float | None:
    copy = dict(payload)
    copy["termination_depth_m"] = None
    extent = log_extent_m(copy)
    if extent <= 0:
        return None
    return extent
