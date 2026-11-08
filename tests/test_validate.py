import math

import pytest

from opendrill.errors import PayloadError
from opendrill.validate import validate_log, validate_payload


def _sample(**fields):
    row = {"depth_top_m": 1, "depth_bot_m": 1.5, "test": "SHELBY"}
    row.update(fields)
    return {"tests": [row]}


def test_nan_and_inf_are_rejected():
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(PayloadError) as caught:
            validate_payload(_sample(depth_top_m=bad))
        assert "finite" in str(caught.value)


def test_negative_blows_recovery_fines_and_plastic_limit_above_liquid_limit():
    with pytest.raises(PayloadError, match="blows"):
        validate_payload(_sample(test="SPT", spt1=-1, spt2=1, spt3=1))
    with pytest.raises(PayloadError, match="percent"):
        validate_payload(_sample(recovery=150))
    with pytest.raises(PayloadError, match="percent"):
        validate_payload(_sample(fines_pct=-1))
    with pytest.raises(PayloadError, match="liquid limit"):
        validate_payload(_sample(wp_pct=40, wl_pct=20))


def test_moisture_and_liquid_limit_may_exceed_100_percent():
    payload = validate_payload(_sample(w_pct=150, wl_pct=120, wp_pct=40))
    row = payload["tests"][0]
    assert row["w_pct"] == 150
    assert row["wl_pct"] == 120


def test_partial_sample_depths_are_a_controlled_error():
    with pytest.raises(PayloadError, match="both be set"):
        validate_payload({"tests": [{"depth_top_m": 1, "test": "SPT", "spt2": 1, "spt3": 1}]})
    with pytest.raises(PayloadError, match="required"):
        validate_payload({"tests": [{"test": "SPT", "spt2": 4, "spt3": 5}]})
    with pytest.raises(PayloadError, match="depth_bot_m must be >= depth_top_m"):
        validate_payload(_sample(depth_top_m=2, depth_bot_m=1))


def test_layers_allow_gaps_and_zero_thickness_but_not_overlaps():
    validate_payload({
        "layers": [
            {"depth_start_m": 0, "depth_end_m": 1, "soil_type": "SAND", "desc": "a"},
            {"depth_start_m": 1, "depth_end_m": 1, "soil_type": "CLAY", "desc": "contact"},
            {"depth_start_m": 3, "depth_end_m": 4, "soil_type": "GRAVEL", "desc": "gap above"},
        ]
    })
    with pytest.raises(PayloadError, match="overlap"):
        validate_payload({
            "layers": [
                {"depth_start_m": 0, "depth_end_m": 2, "desc": "a"},
                {"depth_start_m": 1, "depth_end_m": 3, "desc": "b"},
            ]
        })
    with pytest.raises(PayloadError, match="zero-thickness"):
        validate_payload({
            "layers": [
                {"depth_start_m": 4, "depth_end_m": 4, "desc": "a"},
                {"depth_start_m": 4, "depth_end_m": 4, "desc": "b"},
            ]
        })
    with pytest.raises(PayloadError, match="depth_end_m must be >="):
        validate_payload({"layers": [{"depth_start_m": 2, "depth_end_m": 1, "desc": "bad"}]})


def test_screen_interval_must_be_ordered_and_complete():
    with pytest.raises(PayloadError, match="bottom_screen_m must be >"):
        validate_payload({"piezo": {"top_screen_m": 5, "bottom_screen_m": 2}})
    with pytest.raises(PayloadError, match="both be set"):
        validate_payload({"piezo": {"top_screen_m": 1}})
    with pytest.raises(PayloadError, match="metres"):
        validate_payload({"piezo": {"screen_line_spacing_m": 0}})


def test_depth_per_sheet_must_be_finite_and_cannot_explode_the_page_count():
    with pytest.raises(PayloadError):
        validate_payload({"depth_per_sheet_m": 0, "layers": [{"depth_start_m": 0, "depth_end_m": 1, "desc": "a"}]})
    with pytest.raises(PayloadError, match="pages"):
        validate_payload({
            "depth_per_sheet_m": 1e-6,
            "layers": [{"depth_start_m": 0, "depth_end_m": 10, "desc": "a"}],
        })


def test_su_is_not_halved_when_supplied_and_raw_strength_can_derive_it():
    given = validate_log(_sample(su_kPa=100, su_kind="uc", uc_kPa=80))
    assert given.payload["tests"][0]["su_kPa"] == 100
    assert given.payload["tests"][0]["su_source"] == "given"
    assert any("not halved" in warning for warning in given.warnings)

    derived = validate_payload(_sample(su_kind="uc", uc_kPa=80))
    assert derived["tests"][0]["su_kPa"] == 40
    assert derived["tests"][0]["su_source"] == "uc/2"
    again = validate_payload(derived)
    assert again["tests"][0]["su_kPa"] == 40

    ppen = validate_payload(_sample(su_kind="ppen", ppen_kPa=90))
    assert ppen["tests"][0]["su_kPa"] == 45
    assert ppen["tests"][0]["su_source"] == "ppen/2"


def test_samples_alias_and_info_numbers():
    payload = validate_payload({
        "samples": [{"depth_top_m": 1, "depth_bot_m": 2, "test": "VANE", "w_pct": 10}],
        "info": {"water level (m)": 4, "ground elev. (m)": -2.5, "crs": "SYN-CRS"},
    })
    assert "tests" in payload and len(payload["tests"]) == 1
    assert payload["info"]["WATER LEVEL (M)"] == 4
    assert payload["info"]["GROUND ELEV. (M)"] == -2.5
    assert payload["info"]["CRS"] == "SYN-CRS"
    with pytest.raises(PayloadError, match="not both"):
        validate_payload({"tests": [], "samples": []})
    with pytest.raises(PayloadError, match="WATER LEVEL"):
        validate_payload({"info": {"WATER LEVEL (M)": "deep"}})


def test_termination_shallower_than_data_warns_but_keeps_the_data():
    result = validate_log({
        "termination_depth_m": 3,
        "layers": [{"depth_start_m": 0, "depth_end_m": 5, "desc": "a"}],
    })
    assert result.payload["termination_depth_m"] == 3
    assert any("shallower" in warning for warning in result.warnings)


def test_su_without_kind_is_warned_and_not_plotted():
    from opendrill.series import plotted_series

    result = validate_log(_sample(su_kPa=40))
    assert any("su_kind is missing" in warning and "no Su point" in warning for warning in result.warnings)
    assert plotted_series(result.payload["tests"][0])["su"] is False


def test_screen_deeper_than_the_pipe_warns_but_stays():
    result = validate_log({
        "piezo": {
            "bottom_piezo_m": 12.5,
            "top_screen_m": 10.2,
            "bottom_screen_m": 13.8,
        }
    })
    assert result.payload["piezo"]["bottom_screen_m"] == 13.8
    assert any(
        "bottom_screen_m" in warning and "bottom_piezo_m" in warning
        for warning in result.warnings
    )


def test_synthetic_screen_is_inside_the_pipe_and_crosses_10_m():
    from opendrill.synthetic import synthetic_payload

    piezo = synthetic_payload()["piezo"]
    assert piezo["top_screen_m"] < piezo["bottom_screen_m"] <= piezo["bottom_piezo_m"] <= piezo["bottom_depth_m"]
    assert piezo["top_screen_m"] < 10 < piezo["bottom_screen_m"]
    result = validate_log(synthetic_payload())
    assert not any("bottom_screen_m" in warning and "bottom_piezo_m" in warning for warning in result.warnings)


def test_bool_is_not_a_number():
    with pytest.raises(PayloadError, match="finite"):
        validate_payload(_sample(w_pct=True))
