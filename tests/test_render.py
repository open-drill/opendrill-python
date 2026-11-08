import pytest

from opendrill.render import build_pdf, render_log
from opendrill.synthetic import synthetic_payload
from tests.conftest import base_payload, page_text


def test_pdf_header_and_preserved_header_footer_text():
    result = render_log(base_payload())
    assert result.pdf_bytes.startswith(b"%PDF")
    text = "\n".join(page_text(result.pdf_bytes))
    for label in (
        "SYNTHETIC LOG",
        "STARTED",
        "FINISHED",
        "DRILL METHOD",
        "GROUND ELEV",
        "PROJECT",
        "LOCATION",
        "LOGGED BY",
        "CHECKED BY",
        "HOLE NO",
        "SHEET",
        "OF",
        "DEPTH (m)",
        "RECOVERY",
        "Su - kPa",
        "UC/2",
        "P.PEN/2",
        "SPT N",
        "SYNTHETIC clay",
        "2000-01-01",
        "synthetic",
        "SYN-BH-01",
    ):
        assert label in text, label


def test_lab_series_change_the_pdf_without_an_spt_row():
    plain = build_pdf(base_payload())
    moisture = build_pdf(base_payload(tests=[{
        "no": 1, "test": "SHELBY", "depth_top_m": 1, "depth_bot_m": 1.5, "w_pct": 25,
    }]))
    fines = build_pdf(base_payload(tests=[{
        "no": 1, "test": "SHELBY", "depth_top_m": 1, "depth_bot_m": 1.5, "fines_pct": 30,
    }]))
    limits = build_pdf(base_payload(tests=[{
        "no": 1, "test": "SHELBY", "depth_top_m": 1, "depth_bot_m": 1.5, "wp_pct": 15,
    }]))
    both_limits = build_pdf(base_payload(tests=[{
        "no": 1, "test": "UC2", "depth_top_m": 1, "depth_bot_m": 1.5, "wl_pct": 40,
    }]))
    assert plain != moisture
    assert plain != fines
    assert plain != limits
    assert plain != both_limits
    assert moisture != fines


def test_out_of_axis_values_warn_and_still_render():
    result = render_log(base_payload(tests=[{
        "no": 9,
        "test": "SPT",
        "depth_top_m": 2,
        "depth_bot_m": 2.5,
        "spt1": 40,
        "spt2": 60,
        "spt3": 60,
        "su_kPa": 250,
        "su_kind": "field_peak",
        "w_pct": 140,
        "wl_pct": 130,
        "wp_pct": 20,
    }]))
    assert result.pdf_bytes.startswith(b"%PDF")
    blob = " ".join(result.warnings)
    assert "su_kPa" in blob and "marked at the axis edge" in blob
    assert "spt2+spt3" in blob and "not N60" in blob
    assert "w_pct" in blob
    assert "4/6/8" not in "\n".join(page_text(result.pdf_bytes))
    assert "40/60/60" in "\n".join(page_text(result.pdf_bytes))


def test_fractional_sheet_length_labels_the_real_depths():
    result = render_log(base_payload(
        depth_per_sheet_m=2.5,
        layers=[{"depth_start_m": 0, "depth_end_m": 5, "soil_type": "SAND", "desc": "SYNTHETIC sand"}],
    ))
    texts = page_text(result.pdf_bytes)
    assert len(texts) == 2
    assert "2.5" in {line.strip() for line in texts[0].splitlines()}
    assert "5" in {line.strip() for line in texts[1].splitlines()}
    tiny = render_log(base_payload(
        depth_per_sheet_m=0.4,
        layers=[{"depth_start_m": 0, "depth_end_m": 0.4, "soil_type": "CLAY", "desc": "thin"}],
        info={"LOG TITLE": "TINY", "HOLE NO": "T"},
    ))
    assert "0.4" in "\n".join(page_text(tiny.pdf_bytes))
    three = render_log(base_payload(
        depth_per_sheet_m=0.4,
        layers=[{"depth_start_m": 0, "depth_end_m": 1, "soil_type": "CLAY", "desc": "one metre"}],
        info={"LOG TITLE": "TINY", "HOLE NO": "T"},
    ))
    assert three.page_count == 3


def test_boundary_sample_number_is_on_one_page():
    payload = base_payload(
        depth_per_sheet_m=10,
        layers=[{"depth_start_m": 0, "depth_end_m": 20, "soil_type": "SAND", "desc": "full"}],
        tests=[
            {"no": 77, "test": "SHELBY", "depth_top_m": 10, "depth_bot_m": 10},
            {"no": 78, "test": "SHELBY", "depth_top_m": 0, "depth_bot_m": 0},
            {"no": 79, "test": "SHELBY", "depth_top_m": 15, "depth_bot_m": 15},
        ],
    )
    texts = page_text(build_pdf(payload))
    assert len(texts) == 2
    assert "77" in texts[0]
    assert "77" not in texts[1]
    assert "78" in texts[0]
    assert "79" in texts[1]
    assert "79" not in texts[0]


def test_pagination_follows_water_samples_instruments_and_termination():
    water = render_log(base_payload(
        depth_per_sheet_m=10,
        layers=[{"depth_start_m": 0, "depth_end_m": 5, "soil_type": "CLAY", "desc": "shallow"}],
        info={
            "LOG TITLE": "W",
            "HOLE NO": "W",
            "WATER LEVEL (M)": 12,
            "PROJECT": "Synthetic",
        },
    ))
    water_text = page_text(water.pdf_bytes)
    assert len(water_text) == 2
    assert "Water Level" in water_text[1]
    assert "Water Level" not in water_text[0]

    deep = render_log(base_payload(
        depth_per_sheet_m=10,
        layers=[{"depth_start_m": 0, "depth_end_m": 5, "soil_type": "CLAY", "desc": "shallow"}],
        tests=[{"no": 99, "test": "SHELBY", "depth_top_m": 12, "depth_bot_m": 12.4, "w_pct": 10}],
    ))
    deep_text = page_text(deep.pdf_bytes)
    assert "99" in deep_text[1]
    assert "99" not in deep_text[0]

    instrument = render_log(base_payload(
        depth_per_sheet_m=10,
        layers=[{"depth_start_m": 0, "depth_end_m": 5, "desc": "shallow"}],
        piezo={"bottom_depth_m": 12, "bottom_piezo_m": 11, "top_screen_m": 10.5, "bottom_screen_m": 11.5, "screen_line_spacing_m": 0.25},
    ))
    assert instrument.page_count == 2

    ended = render_log(base_payload(
        depth_per_sheet_m=10,
        termination_depth_m=16,
        layers=[{"depth_start_m": 0, "depth_end_m": 5, "soil_type": "SAND", "desc": "stops at 5"}],
    ))
    ended_text = page_text(ended.pdf_bytes)
    assert ended.page_count == 2
    assert "Termination depth (supplied) 16 m" in ended_text[1]


def test_long_notes_continue_without_inventing_deeper_metre_labels():
    notes = "\n".join(f"syntheticnote {i}" for i in range(80))
    result = render_log(base_payload(
        depth_per_sheet_m=10,
        layers=[{"depth_start_m": 0, "depth_end_m": 5, "soil_type": "CLAY", "desc": "short"}],
        notes=notes,
    ))
    texts = page_text(result.pdf_bytes)
    assert result.page_count >= 2
    assert any("notes continued" in warning for warning in result.warnings)
    assert "syntheticnote 0" in texts[0]
    assert any("syntheticnote 79" in text for text in texts[1:])
    # A false extra depth window would label 11 m, 12 m, ... The note text
    # itself does not contain those integers as depth ticks; "notes" marks
    # the continuation sheet's depth column.
    assert "notes" in texts[-1]
    continued_lines = {line.strip() for line in texts[-1].splitlines()}
    assert "11" not in continued_lines
    assert "12" not in continued_lines


def test_long_description_keeps_the_footer_and_continues():
    desc = " ".join(["syntheticword"] * 800)
    result = render_log(base_payload(
        layers=[{"depth_start_m": 0, "depth_end_m": 2, "soil_type": "CLAY", "desc": desc}],
    ))
    texts = page_text(result.pdf_bytes)
    assert "SYN-BH-01" in texts[0]
    assert "syntheticword" in texts[0]
    assert result.page_count >= 2
    assert any("description text continued" in warning for warning in result.warnings)
    assert "syntheticword" in texts[-1]


def test_long_footer_value_is_truncated_with_a_warning():
    huge = "SYNTHETIC " * 40
    result = render_log(base_payload(info={
        "LOG TITLE": "T",
        "PROJECT": huge,
        "HOLE NO": "H",
    }))
    assert any("PROJECT was truncated" in warning for warning in result.warnings)
    assert "PROJECT" in page_text(result.pdf_bytes)[0]


def test_zero_thickness_gap_and_hatch_override_render():
    result = render_log(base_payload(layers=[
        {"depth_start_m": 0, "depth_end_m": 1, "soil_type": "SAND", "desc": "SAND AND GRAVEL explicit sand"},
        {"depth_start_m": 1, "depth_end_m": 1, "soil_type": "CLAY", "desc": "CONTACTMARK"},
        {"depth_start_m": 3, "depth_end_m": 4, "desc": "CLAY guessed from words"},
    ]))
    text = "\n".join(page_text(result.pdf_bytes))
    assert "CONTACTMARK" in text
    assert "explicit sand" in text
    assert "guessed from words" in text


def test_synthetic_example_is_multipage_and_carries_every_category():
    result = render_log(synthetic_payload())
    texts = page_text(result.pdf_bytes)
    assert result.pdf_bytes.startswith(b"%PDF")
    assert result.page_count >= 2
    assert not any("truncated" in warning for warning in result.warnings)
    joined = "\n".join(texts)
    for snippet in (
        "SYNTHETIC asphalt",
        "SYNTHETIC sand",
        "SYNTHETIC gravel",
        "SYNTHETIC clay",
        "SYNTHETIC backfill",
        "4/6/8",
        "80 %",
        "Water Level",
        "Termination depth (supplied) 16 m",
        "not N60",
        "SYN-CRS",
        "SYN-H",
        "SYN-V",
        "SHELBY",
        "VANE",
        "UC2",
        "NOT A FIELD RECORD",
    ):
        assert snippet in joined, snippet
    assert "asphalt" in texts[0].lower()
    assert "backfill" in texts[1].lower() or "BACKFILL" in texts[1]


def test_sheet_numbers_10_through_200_stay_in_the_footer():
    from reportlab.pdfbase import pdfmetrics

    from opendrill.render import _HOLE_NO_X, _tx, sheet_line_layout

    limit = _tx(_HOLE_NO_X) - 1.0
    for number in (1, 9, 10, 11, 99, 100, 200):
        placed = sheet_line_layout(number, 200)
        texts = [item.text for item in placed]
        assert texts == ["SHEET", str(number), "OF", "200"]
        spans = []
        for item in placed:
            width = pdfmetrics.stringWidth(item.text, item.font, item.size)
            assert item.x + width <= limit
            spans.append((item.x, item.x + width))
        ordered = sorted(spans)
        for (_a_start, a_end), (b_start, _b_end) in zip(ordered, ordered[1:]):
            assert a_end <= b_start + 0.05

    short = render_log(base_payload(
        depth_per_sheet_m=1.5,
        termination_depth_m=16,
        notes="",
        layers=[{"depth_start_m": 0, "depth_end_m": 1, "soil_type": "CLAY", "desc": "short"}],
    ))
    assert short.page_count == 11
    assert not any("SHEET was truncated" in warning for warning in short.warnings)
    _assert_footer_number(short.pdf_bytes, 10, 11)
    _assert_footer_number(short.pdf_bytes, 11, 11)

    many = render_log({
        "depth_per_sheet_m": 1,
        "info": {"LOG TITLE": "PAGES", "HOLE NO": "P"},
        "layers": [{"depth_start_m": 0, "depth_end_m": 200, "desc": ""}],
        "tests": [],
        "notes": "",
    })
    assert many.page_count == 200
    assert not any("SHEET was truncated" in warning for warning in many.warnings)
    _assert_footer_number(many.pdf_bytes, 10, 200)
    _assert_footer_number(many.pdf_bytes, 100, 200)
    _assert_footer_number(many.pdf_bytes, 200, 200)


def _assert_footer_number(data: bytes, sheet_num: int, sheet_total: int) -> None:
    from pypdf import PdfReader
    import io

    from opendrill.render import sheet_line_layout

    placed = {item.text: item for item in sheet_line_layout(sheet_num, sheet_total)}
    found = []

    def visit(text, _cm, tm, _font, _size):
        if text and text.strip():
            found.append((text.strip(), tm[4], tm[5]))

    PdfReader(io.BytesIO(data)).pages[sheet_num - 1].extract_text(visitor_text=visit)
    for label in (str(sheet_num), str(sheet_total), "SHEET", "OF"):
        target = placed[label]
        assert any(
            text == label and abs(x - target.x) < 1.5 and abs(y - target.y) < 1.5
            for text, x, y in found
        ), label


def test_low_n_blow_label_stays_inside_the_plot():
    from opendrill.render import _frame, spt_label_origin

    frame = _frame()
    # N = spt2 + spt3 = 6 + 8 = 14. The label is the three 6-inch counts.
    marker = frame.gx_l + (14 / 100) * (frame.gx_r - frame.gx_l)
    from reportlab.pdfbase import pdfmetrics
    width = pdfmetrics.stringWidth("4/6/8", "Helvetica", 6)
    origin = spt_label_origin(marker, width, frame.gx_l, frame.gx_r)
    assert origin >= frame.gx_l - 0.01
    assert origin + width <= frame.gx_r + 0.01
    # 4/6/8 is N=14, hard against the instrument column if drawn to the left.
    assert origin >= marker

    result = render_log(base_payload(tests=[{
        "no": 1, "test": "SPT", "depth_top_m": 2, "depth_bot_m": 2.5,
        "spt1": 4, "spt2": 6, "spt3": 8,
    }]))
    hits = _text_positions(result.pdf_bytes, "4/6/8")
    assert hits
    assert all(marker - 0.5 <= x and x + width <= frame.gx_r + 0.5 for x, _y, _size in hits)


def test_shelby_stays_inside_the_test_column():
    from reportlab.pdfbase import pdfmetrics

    from opendrill.render import COL_TEST_L, COL_TEST_R, _tx

    result = render_log(base_payload(tests=[{
        "no": 3, "test": "SHELBY", "depth_top_m": 4.6, "depth_bot_m": 5.1, "w_pct": 28,
    }]))
    hits = _text_positions(result.pdf_bytes, "SHELBY")
    assert hits, "SHELBY was ellipsised or dropped"
    left, right = _tx(COL_TEST_L), _tx(COL_TEST_R)
    for x, _y, size in hits:
        width = pdfmetrics.stringWidth("SHELBY", "Helvetica", size)
        assert left - 0.6 <= x
        assert x + width <= right + 0.6


def _text_positions(data: bytes, needle: str) -> list[tuple[float, float, float]]:
    import io

    from pypdf import PdfReader

    found = []

    def visit(text, _cm, tm, _font, size):
        if text and text.strip() == needle:
            found.append((tm[4], tm[5], size))

    for page in PdfReader(io.BytesIO(data)).pages:
        page.extract_text(visitor_text=visit)
    return found


def test_explicit_soil_type_beats_the_description_guess():
    from opendrill.patterns import desc_to_pattern, hatch_for_layer

    assert desc_to_pattern("SAND AND GRAVEL") == "gravel"
    assert desc_to_pattern("backfill material") is None
    assert hatch_for_layer("SAND", "CLAY") == "sand"
    assert hatch_for_layer(None, "ASPHALT pavement") == "asphalt"
    assert hatch_for_layer("BACKFILL", "SAND") == "backfill"
