import math

import pytest

from opendrill.layout import (
    clip_interval,
    contains_point,
    data_page_windows,
    depth_axis,
    format_depth,
    grid_line_count,
    log_extent_m,
    overlaps_interval,
    sheet_count,
)
from opendrill.series import plotted_series, spt_n_value


def test_half_open_points_are_not_duplicated_and_terminals_stay():
    assert contains_point(0, 0, 10)
    assert contains_point(10, 0, 10)
    assert not contains_point(10, 10, 20)
    assert contains_point(20, 10, 20)
    assert not contains_point(0, 10, 20)
    assert contains_point(5, 0, 10)
    assert not contains_point(0.0, 10, 20)


def test_zero_thickness_at_a_boundary_belongs_to_one_page():
    assert overlaps_interval(10, 10, 0, 10)
    assert not overlaps_interval(10, 10, 10, 20)
    assert clip_interval(8, 10, 10, 20) is None
    assert clip_interval(10, 12, 0, 10) is None
    clipped = clip_interval(8, 12, 0, 10)
    assert clipped == (8, 10)
    assert clip_interval(8, 12, 10, 20) == (10, 12)


def test_integer_sheet_keeps_one_metre_ticks_and_the_real_end():
    axis = depth_axis(0, 20)
    assert axis.major_step_m == 1
    assert axis.label_depths_m[0] == 1
    assert axis.label_depths_m[-1] == 20
    assert 0 not in axis.label_depths_m
    assert axis.minor_count == 200


def test_fractional_span_labels_the_true_end_and_does_not_collapse():
    short = depth_axis(0, 2.5)
    assert short.label_depths_m[-1] == pytest.approx(2.5)
    assert 2 in short.label_depths_m or any(abs(v - 2) < 1e-9 for v in short.label_depths_m)
    tiny = depth_axis(0, 0.4)
    assert tiny.label_depths_m[-1] == pytest.approx(0.4)
    assert tiny.minor_count >= 1
    assert grid_line_count(0.2) >= 1
    assert grid_line_count(0.4) >= 1
    assert grid_line_count(20) == 20
    assert grid_line_count(10) == 20


def test_depth_axis_rejects_a_non_positive_span():
    with pytest.raises(ValueError):
        depth_axis(1, 1)
    with pytest.raises(ValueError):
        depth_axis(0, math.nan)


def test_format_depth_drops_a_needless_decimal():
    assert format_depth(1.0) == "1"
    assert format_depth(2.5) == "2.5"
    assert format_depth(20) == "20"


def test_extent_includes_samples_water_instrument_and_termination():
    payload = {
        "layers": [{"depth_start_m": 0, "depth_end_m": 4}],
        "tests": [{"depth_top_m": 30, "depth_bot_m": 31}],
        "info": {"WATER LEVEL (M)": 40},
        "piezo": {"bottom_depth_m": 50, "bottom_screen_m": 48},
        "termination_depth_m": 55,
    }
    assert log_extent_m(payload) == 55
    assert sheet_count(55, 20) == 3
    assert data_page_windows(20, 20) == [(0, 20)]
    assert len(data_page_windows(20.1, 20)) == 2


def test_series_plot_independently_of_spt_and_of_each_other():
    lab = {
        "test": "SHELBY",
        "depth_top_m": 1,
        "depth_bot_m": 1.5,
        "w_pct": 25,
        "fines_pct": 10,
        "su_kPa": 40,
        "su_kind": "lab_peak",
    }
    flags = plotted_series(lab)
    assert flags["w"] and flags["fines"] and flags["su"]
    assert not flags["spt_n"]
    assert not flags["wp"] and not flags["wl"]
    limits_only = dict(lab)
    limits_only["w_pct"] = None
    limits_only["wp_pct"] = 15
    limits_only["wl_pct"] = None
    assert plotted_series(limits_only)["wp"]
    assert not plotted_series(limits_only)["wl"]
    assert not plotted_series(limits_only)["w"]
    spt = {"test": "spt", "depth_top_m": 1, "depth_bot_m": 2, "spt2": 4, "spt3": 5}
    assert plotted_series(spt)["spt_n"]
    assert spt_n_value(spt) == 9
