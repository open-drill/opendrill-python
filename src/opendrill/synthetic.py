"""Synthetic borehole used by the example commands.

Every identifier here is invented for the example. It is not a field record,
not a survey, and not a classification. Coordinates are 0. CRS and datum
strings are labels supplied for the example; the package does not look them
up and does not assume a coordinate system when they are absent.
"""
from __future__ import annotations

import copy

SYNTHETIC_PAYLOAD: dict = {
    "depth_per_sheet_m": 10,
    "termination_depth_m": 16,
    "info": {
        "LOG TITLE": "SYNTHETIC TEST HOLE LOG",
        "PROJECT": "Synthetic example — not a field record",
        "PROJECT NO": "SYN-001",
        "HOLE NO": "SYN-BH-01",
        "DRILL METHOD": "Synthetic method",
        "LOCATION": "Synthetic location",
        "STARTED": "2000-01-01",
        "FINISHED": "2000-01-02",
        "COORDINATES (M) N": 0,
        "COORDINATES (M) E": 0,
        "CRS": "SYN-CRS",
        "HORIZONTAL DATUM": "SYN-H",
        "VERTICAL DATUM": "SYN-V",
        "GROUND ELEV. (M)": 100,
        "WATER LEVEL (M)": 3.5,
        "LOGGED BY": "synthetic",
        "CHECKED BY": "synthetic",
    },
    "layers": [
        {
            "depth_start_m": 0,
            "depth_end_m": 0.25,
            "soil_type": "ASPHALT",
            "desc": "SYNTHETIC asphalt category, 0.25 m. Not a field record.",
        },
        {
            "depth_start_m": 0.25,
            "depth_end_m": 3,
            "soil_type": "SAND",
            "desc": "SYNTHETIC sand category. The hatch is a drawing pattern, not a classification.",
        },
        {
            "depth_start_m": 4,
            "depth_end_m": 8,
            "soil_type": "GRAVEL",
            "desc": "SYNTHETIC gravel category. The gap from 3 m to 4 m is intentional.",
        },
        {
            "depth_start_m": 8,
            "depth_end_m": 12,
            "soil_type": "CLAY",
            "desc": "SYNTHETIC clay category crossing the 10 m sheet boundary.",
        },
        {
            "depth_start_m": 12,
            "depth_end_m": 15,
            "soil_type": "BACKFILL",
            "desc": "SYNTHETIC backfill category.",
        },
    ],
    "tests": [
        {
            "no": 1,
            "test": "SPT",
            "depth_top_m": 1,
            "depth_bot_m": 1.5,
            "recovery": 80,
            "spt1": 4,
            "spt2": 6,
            "spt3": 8,
            "wp_pct": 20,
            "wl_pct": 45,
            "w_pct": 30,
            "fines_pct": 12,
            "su_kPa": 40,
            "su_kind": "field_peak",
        },
        {
            "no": 2,
            "test": "SPT",
            "depth_top_m": 2,
            "depth_bot_m": 2.4,
            "recovery": 60,
            "spt1": 3,
            "spt2": 4,
            "spt3": 5,
            "su_kPa": 70,
            "su_kind": "field_remold",
        },
        {
            "no": 3,
            "test": "SHELBY",
            "depth_top_m": 4.6,
            "depth_bot_m": 5.1,
            "su_kPa": 90,
            "su_kind": "lab_peak",
            "w_pct": 28,
        },
        {
            "no": 4,
            "test": "VANE",
            "depth_top_m": 6.2,
            "depth_bot_m": 6.7,
            "fines_pct": 35,
            "su_kPa": 110,
            "su_kind": "lab_remold",
        },
        {
            "no": 5,
            "test": "UC2",
            "depth_top_m": 8.4,
            "depth_bot_m": 8.9,
            "su_kind": "uc",
            "uc_kPa": 280,
        },
        {
            "no": 6,
            "test": "UC2",
            "depth_top_m": 11.2,
            "depth_bot_m": 11.7,
            "su_kind": "ppen",
            "ppen_kPa": 340,
        },
        {
            "no": 7,
            "test": "SPT",
            "depth_top_m": 13.1,
            "depth_bot_m": 13.6,
            "recovery": 55,
            "spt1": 8,
            "spt2": 10,
            "spt3": 12,
            "wp_pct": 15,
            "wl_pct": 33,
            "w_pct": 22,
        },
        {
            "no": 8,
            "test": "SHELBY",
            "depth_top_m": 14.2,
            "depth_bot_m": 14.6,
            "w_pct": 18,
        },
    ],
    "piezo": {
        "bottom_depth_m": 14.5,
        "bottom_piezo_m": 13.2,
        "top_screen_m": 9.2,
        "bottom_screen_m": 12.8,
        "screen_line_spacing_m": 0.4,
    },
    "notes": (
        "SYNTHETIC EXAMPLE — NOT A FIELD RECORD.\n"
        "Depths are metres. su_kPa is kilopascals plotted as entered.\n"
        "Sample 5 plots Su = uc_kPa / 2 (280 / 2 = 140) because su_kPa was omitted.\n"
        "Sample 6 plots Su = ppen_kPa / 2 (340 / 2 = 170) on the same rule.\n"
        "SPT N = spt2 + spt3, not N60. Counts are the template's 6-inch increments.\n"
        "Hatches are categories, not a classification system.\n"
        "CRS SYN-CRS and datums SYN-H / SYN-V were typed in for this example and are not a real geodetic definition.\n"
        "Termination depth (supplied) is 16 m, below the last layer at 15 m."
    ),
}


def synthetic_payload() -> dict:
    """Return a deep copy of the synthetic example."""
    return copy.deepcopy(SYNTHETIC_PAYLOAD)
