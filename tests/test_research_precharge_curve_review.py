"""Independent declared-envelope and observation-coverage checks."""

import json

import numpy as np
import pytest

from batterylog_research.precharge_curve_review import (
    main,
    review_precharge_curve,
    synthetic_campaign,
    synthetic_cases,
)


def _source():
    return (
        np.array([-0.1, 0, 1, 2, 2.1]),
        np.array([0, 1, 1, 1, 0]),
        np.array([0, 1, 1, 1, 0], dtype=float),
        np.full(5, 100.0),
        np.full(5, 90.0),
    )


def _envelope():
    return np.array([[0, 0, 2, 0, 0.2], [2, 0, 2, 0, 0.2]], dtype=float)


def _review(arrays=None, envelope=None, **kwargs):
    return review_precharge_curve(
        *(_source() if arrays is None else arrays),
        _envelope() if envelope is None else envelope,
        max_gap_s=1,
        **kwargs,
    )


def test_known_curve_has_covered_interval_and_no_deviation():
    report = _review()
    assert report["declared_interval_covered"]
    assert report["reviewed_samples"] == 3
    assert report["outside_envelope_samples"] == 0
    assert report["observed_start_bracket_s"] == [-0.1, 0]
    assert report["last_qualified_elapsed_s"] == 2
    assert report["reference_horizon_bracket_s"] == [2, 2]


def test_horizon_between_samples_is_bracketed_without_extrapolation():
    arrays = (
        [-0.1, 0, 0.8, 1.6, 2.4, 2.5],
        [0, 1, 1, 1, 1, 0],
        [0, 1, 1, 1, 4, 0],
        np.full(6, 100),
        np.full(6, 90),
    )
    report = _review(arrays)
    assert report["declared_interval_covered"]
    assert report["reference_horizon_bracket_s"] == [1.6, 2.4]
    assert report["last_qualified_elapsed_s"] == 1.6
    assert report["reviewed_samples"] == 3
    assert report["outside_envelope_samples"] == 0  # 2.4 s is outside the declaration.


def test_linear_reference_interpolation_matches_independent_arithmetic():
    rng = np.random.default_rng(20261014)
    time = np.r_[-0.1, np.arange(0, 2.01, 0.125)]
    active = np.r_[0, np.ones(17)]
    envelope = np.array([[0, 0.1, 1, -0.05, 0.2], [2, 0.3, 2, 0.05, 0.4]])
    for _ in range(80):
        current = rng.uniform(-2.5, 2.5, len(time))
        pack = rng.uniform(50, 500, len(time))
        gap = rng.uniform(-0.1, 0.6, len(time))
        bus = pack * (1 - gap)
        expected = 0
        current_excess = voltage_excess = 0.0
        for i, t in enumerate(time[1:], 1):
            lower_i, upper_i = 0.1 + 0.1 * t, 1 + 0.5 * t
            lower_v, upper_v = -0.05 + 0.05 * t, 0.2 + 0.1 * t
            di = max(lower_i - abs(current[i]), abs(current[i]) - upper_i, 0)
            dv = max(lower_v - gap[i], gap[i] - upper_v, 0)
            expected += bool(di or dv)
            current_excess, voltage_excess = max(current_excess, di), max(voltage_excess, dv)
        report = _review((time, active, current, pack, bus), envelope)
        assert report["declared_interval_covered"]
        assert report["outside_envelope_samples"] == expected
        assert report["max_current_excess_a"] == pytest.approx(current_excess)
        assert report["max_voltage_gap_fraction_excess"] == pytest.approx(voltage_excess)


def test_exact_bounds_pass_and_recorded_current_sign_is_preserved():
    arrays = list(_source())
    arrays[2][1:] = -2
    arrays[4][1:] = 80
    assert _review(arrays)["outside_envelope_samples"] == 0
    arrays[2][2] = -3
    report = _review(arrays)
    assert report["outside_envelope_samples"] == 1
    assert report["examples"][0]["current_a"] == -3


def test_dc_link_overshoot_is_not_same_as_undershoot():
    arrays = list(_source())
    arrays[4][2] = 110
    report = _review(arrays)
    assert report["outside_envelope_samples"] == 1
    assert report["examples"][0]["voltage_gap_fraction"] == pytest.approx(-0.1)
    envelope = _envelope()
    envelope[:, 3] = -0.2
    assert _review(arrays, envelope)["outside_envelope_samples"] == 0


@pytest.mark.parametrize(
    "kind", ["gap", "duplicate", "unknown_phase", "early_end", "short_capture"]
)
def test_incomplete_capture_never_claims_full_interval(kind):
    arrays = [a.copy() for a in _source()]
    if kind == "gap":
        arrays[0][2:] += 3
    elif kind == "duplicate":
        arrays[0][2] = 0
    elif kind == "unknown_phase":
        arrays[1][2] = 2
    elif kind == "early_end":
        arrays[1][2:] = 0
    else:
        arrays = [a[:3] for a in arrays]
    report = _review(arrays)
    assert not report["declared_interval_covered"]
    assert report["incomplete_reasons"]


def test_earlier_deviation_survives_later_gap():
    arrays = [a.copy() for a in _source()]
    arrays[2][1] = 3
    arrays[0][2:] += 3
    report = _review(arrays)
    assert report["outside_envelope_samples"] == 1
    assert not report["declared_interval_covered"]
    assert report["examples"][0]["sample_index"] == 1


def test_active_start_has_no_invented_activation_time():
    report = _review(tuple(a[1:] for a in _source()))
    assert not report["declared_interval_covered"]
    assert report["observed_start_bracket_s"] is None
    assert report["reviewed_samples"] == 0
    assert "activation_not_observed" in report["incomplete_reasons"]


def test_multiple_activations_not_hidden_by_a_complete_first_interval():
    time = np.array([-0.1, 0, 1, 2, 2.1, 3, 4, 5], dtype=float)
    arrays = (time, [0, 1, 1, 1, 0, 1, 1, 0], np.ones(8), np.full(8, 100), np.full(8, 90))
    with pytest.raises(ValueError, match="multiple observed activations"):
        _review(arrays)


def test_finite_reference_values_cannot_create_infinite_interpolated_evidence():
    envelope = np.array([[0, 0, 2, -1e308, -0.5e308], [2, 0, 2, 1e308, 1.5e308]])
    with pytest.raises(ValueError, match="interpolation overflowed"):
        _review(envelope=envelope)


def test_finite_source_and_bounds_cannot_create_infinite_deviation():
    arrays = list(_source())
    arrays[3][:] = 1
    arrays[4][2] = 1e308
    envelope = np.array([[0, 0, 2, 1e308, 1.5e308], [2, 0, 2, 1e308, 1.5e308]])
    with pytest.raises(ValueError, match="comparison overflowed"):
        _review(arrays, envelope)


def test_finite_timestamps_cannot_create_infinite_elapsed_evidence():
    arrays = (
        [-1.5e308, -1.4e308, -0.5e308, 0.5e308],
        [0, 1, 1, 1],
        [0, 1, 1, 1],
        [100] * 4,
        [90] * 4,
    )
    envelope = [[0, 0, 2, 0, 0.2], [1.6e308, 0, 2, 0, 0.2]]
    with pytest.raises(ValueError, match="Elapsed-time calculation overflowed"):
        review_precharge_curve(*arrays, envelope, max_gap_s=1.1e308)


@pytest.mark.parametrize("column", [2, 3, 4])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_bad_active_measurement_breaks_qualification(column, value):
    arrays = [a.astype(float) for a in _source()]
    arrays[column][2] = value
    report = _review(arrays)
    assert not report["declared_interval_covered"]
    assert "invalid_active_measurement" in report["incomplete_reasons"]
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("value", [0, -100])
def test_nonpositive_pack_voltage_cannot_define_relative_gap(value):
    arrays = [a.copy() for a in _source()]
    arrays[3][2] = value
    assert not _review(arrays)["declared_interval_covered"]


@pytest.mark.parametrize("value", [True, False, "1", 1j])
def test_measurements_do_not_silently_coerce_unsupported_values(value):
    arrays = list(_source())
    arrays[2] = [0, 1, value, 1, 0]
    with pytest.raises(ValueError, match="real numeric"):
        _review(arrays)


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "nonzero_start",
        "reversed_current",
        "reversed_gap",
        "negative_current",
        "nan",
        "wrong_columns",
        "one_knot",
        "boolean",
    ],
)
def test_malformed_reference_rejected(kind):
    envelope = _envelope()
    if kind == "duplicate":
        envelope[1, 0] = 0
    elif kind == "nonzero_start":
        envelope[0, 0] = 0.1
    elif kind == "reversed_current":
        envelope[0, 1] = 3
    elif kind == "reversed_gap":
        envelope[0, 3] = 1
    elif kind == "negative_current":
        envelope[0, 1] = -1
    elif kind == "nan":
        envelope[0, 2] = np.nan
    elif kind == "wrong_columns":
        envelope = envelope[:, :4]
    elif kind == "one_knot":
        envelope = envelope[:1]
    else:
        envelope = envelope.tolist()
        envelope[0][1] = False
    with pytest.raises(ValueError):
        _review(envelope=envelope)


def test_one_checkpoint_can_pass_while_declared_curve_deviates():
    cases = {s["scenario"]: s for s in synthetic_campaign()["scenarios"]}
    for name in (
        "slow_but_checkpoint_current_drop_sufficient",
        "early_disturbance_then_checkpoint_recovers",
        "finite_voltage_inconsistency",
    ):
        assert cases[name]["existing_checkpoint_status"] == "PASS"
        assert cases[name]["outside_envelope_samples"] > 0
        assert cases[name]["declared_interval_covered"]
    assert cases["declared_normal"]["outside_envelope_samples"] == 0


def test_inputs_are_immutable_and_examples_bounded():
    envelope, cases = synthetic_cases()
    arrays = cases["slow_but_checkpoint_current_drop_sufficient"]
    originals = [a.copy() for a in arrays]
    original_envelope = envelope.copy()
    report = review_precharge_curve(*arrays, envelope, max_gap_s=0.2, max_examples=1)
    assert len(report["examples"]) == 1
    for source, original in zip(arrays, originals, strict=True):
        np.testing.assert_array_equal(source, original)
    np.testing.assert_array_equal(envelope, original_envelope)


def test_cli_preserves_existing_output(tmp_path):
    output = tmp_path / "result.json"
    assert main(["--output", str(output)]) == 0
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        main(["--output", str(output)])
    assert output.read_bytes() == original
