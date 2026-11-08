import io

from pypdf import PdfReader


def page_text(data: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(data))
    return [page.extract_text() or "" for page in reader.pages]


def base_payload(**overrides) -> dict:
    payload = {
        "depth_per_sheet_m": 20,
        "info": {
            "LOG TITLE": "SYNTHETIC LOG",
            "PROJECT": "Synthetic example — not a field record",
            "PROJECT NO": "SYN-001",
            "HOLE NO": "SYN-BH-01",
            "DRILL METHOD": "Synthetic method",
            "LOCATION": "Synthetic location",
            "STARTED": "2000-01-01",
            "FINISHED": "2000-01-02",
            "LOGGED BY": "synthetic",
            "CHECKED BY": "synthetic",
            "GROUND ELEV. (M)": 100,
        },
        "layers": [
            {
                "depth_start_m": 0,
                "depth_end_m": 5,
                "soil_type": "CLAY",
                "desc": "SYNTHETIC clay category",
            }
        ],
        "tests": [],
        "piezo": {},
        "notes": "",
    }
    payload.update(overrides)
    return payload
