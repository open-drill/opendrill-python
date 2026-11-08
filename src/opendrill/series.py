"""Which measurements on a sample row are plotted.

Each series is independent. A lab moisture, Atterberg limit, fines content,
or strength point does not require an SPT row, and moisture does not require
plastic and liquid limits. SPT N is plotted only for an SPT row that has
``spt2`` and ``spt3``; N is their sum and is not an N60.
"""
from __future__ import annotations


def is_spt(test: dict) -> bool:
    return str(test.get("test") or "").strip().upper() == "SPT"


def _has_depths(test: dict) -> bool:
    return test.get("depth_top_m") is not None and test.get("depth_bot_m") is not None


def plotted_series(test: dict) -> dict[str, bool]:
    """Flags for the series that should be drawn for one normalised sample row."""
    depths = _has_depths(test)
    spt = is_spt(test)
    return {
        "su": depths and test.get("su_kPa") is not None and bool(test.get("su_kind")),
        "spt_n": (
            depths
            and spt
            and test.get("spt2") is not None
            and test.get("spt3") is not None
        ),
        "wp": depths and test.get("wp_pct") is not None,
        "wl": depths and test.get("wl_pct") is not None,
        "w": depths and test.get("w_pct") is not None,
        "fines": depths and test.get("fines_pct") is not None,
    }


def spt_n_value(test: dict) -> float | None:
    """Raw SPT N = spt2 + spt3. Not corrected to N60. None if either count is missing."""
    spt2 = test.get("spt2")
    spt3 = test.get("spt3")
    if spt2 is None or spt3 is None:
        return None
    return float(spt2) + float(spt3)


def spt_blow_label(test: dict) -> str:
    """Label ``spt1/spt2/spt3``. A missing first increment is shown as ``-``."""
    def part(value: object) -> str:
        if value is None:
            return "-"
        return str(int(value))

    return f"{part(test.get('spt1'))}/{part(test.get('spt2'))}/{part(test.get('spt3'))}"
