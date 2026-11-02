"""Independent source-window and eligibility checks for an investigative harness."""

import numpy as np
import pytest

from batterylog import CellSagConfig, FailureModelConfig
from batterylog.analysis.core import _analyze_battery_frame
from batterylog_research.temporal_characterization import (
    _frame,
    sag_context,
    synthetic_campaign,
    temperature_rates,
)


def _window_oracle(times, temperatures, gap, horizon):
    result = np.full(temperatures.shape, np.nan)
    for i in range(len(times)):
        if not np.isfinite(temperatures[i]).all():
            continue
        start = i
        while start > 0:
            dt = times[start] - times[start - 1]
            if not 0 < dt <= gap or not np.isfinite(temperatures[start - 1]).all():
                break
            start -= 1
        candidates = [j for j in range(start, i) if times[i] - times[j] >= horizon]
        if candidates:
            j = candidates[-1]
            span = times[i] - times[j]
            if span <= horizon + gap:
                result[i] = (temperatures[i] - temperatures[j]) * 60 / span
    return result


@pytest.mark.parametrize("horizon", [0.5, 1, 2, 5])
def test_endpoint_window_matches_independent_enumeration(horizon):
    rng = np.random.default_rng(20261014)
    for _ in range(40):
        times = np.cumsum(rng.choice([0, 0.25, 0.5, 1, 3], 50))
        temperatures = 25 + np.cumsum(rng.normal(0, 0.1, (50, 3)), axis=0)
        temperatures[rng.integers(0, 50), 1] = np.nan
        source = temperatures.copy()
        _, actual = temperature_rates(
            times, temperatures, max_gap_s=1, min_interval_s=0.25, window_s=horizon
        )
        np.testing.assert_allclose(actual, _window_oracle(times, source, 1, horizon))
        np.testing.assert_array_equal(temperatures, source)


@pytest.mark.parametrize("horizon", [1, 2, 5])
def test_known_ramp_has_exact_slope_after_window_warmup(horizon):
    times = np.arange(20, dtype=float)
    temperatures = (25 + times * 0.2)[:, None]
    adjacent, window = temperature_rates(
        times, temperatures, max_gap_s=1, min_interval_s=0.25, window_s=horizon
    )
    np.testing.assert_allclose(adjacent[1:], 12)
    np.testing.assert_allclose(window[horizon:], 12)
    assert np.isnan(window[:horizon]).all()


@pytest.mark.parametrize("break_kind", ["invalid", "gap", "duplicate"])
def test_window_does_not_cross_unknown_or_nonpositive_intervals(break_kind):
    times = np.arange(10, dtype=float)
    temp = (25 + times)[:, None]
    if break_kind == "invalid":
        temp[4] = np.nan
        first_new = 5
    elif break_kind == "gap":
        times[5:] += 10
        first_new = 5
    else:
        times[5:] -= 1
        first_new = 5
    _, window = temperature_rates(times, temp, max_gap_s=1, min_interval_s=0.25, window_s=2)
    assert np.isnan(window[first_new : first_new + 2]).all()


def test_smoothing_can_miss_short_change_and_cannot_fix_implausible_value():
    report = synthetic_campaign()
    cases = {r["scenario"]: r for r in report["temperature"]}
    pulse = cases["short_0_5_c_pulse"]
    assert pulse["adjacent"]["exceeding_observations"] == 1
    assert pulse["endpoint_windows_s"]["5"]["exceeding_observations"] == 0
    spike = cases["implausible_655_c_pulse"]
    assert all(w["exceeding_observations"] > 0 for w in spike["endpoint_windows_s"].values())
    step = cases["single_0_1_c_step"]
    assert step["adjacent"]["exceeding_observations"] == 1
    assert step["endpoint_windows_s"]["1"]["exceeding_observations"] == 0


def test_repeated_identical_values_do_not_prove_stale_acquisition():
    times = np.arange(6, dtype=float)
    # These rows are compatible with fresh equal readings AND held old readings.
    temp = np.array([25, 25, 25, 25, 25, 26], dtype=float)[:, None]
    adjacent, window = temperature_rates(times, temp, max_gap_s=1, min_interval_s=0.25, window_s=5)
    assert adjacent[5, 0] == 60
    assert window[5, 0] == 12


def test_sag_context_matches_core_eligibility_for_seeded_dynamic_currents():
    rng = np.random.default_rng(14)
    config = CellSagConfig("discharge", 0.05, 2, 2, 0.5, 0.05)
    for _ in range(80):
        times = np.cumsum(rng.choice([0, 0.5, 1, 3], 30))
        current = rng.choice([0, 0.02, 1, 3, 5], 30)
        observed = _analyze_battery_frame(
            _frame(times, np.full(len(times), 25), current),
            failure_models=FailureModelConfig(1, cell_sag=config),
        )["failure_models"]["evaluations"][0]
        context = sag_context(times, current, config, max_gap_s=1)
        assert (
            sum(e["eligible_samples"] for e in context["episodes"]) == observed["evaluated_samples"]
        )


def test_sag_reference_is_consumed_and_single_low_sample_is_not_relaxation():
    cases = {r["scenario"]: r for r in synthetic_campaign()["sag"]}
    dynamic = cases["dynamic_load_without_new_rest"]
    assert dynamic["core_status"] == "NOT_EVALUATED"
    assert dynamic["reference_reason_counts"]["missing_rest_reference"] == 1
    assert dynamic["core_incomplete_intervals"] == 1
    assert cases["single_low_current_reference"]["episodes"][0]["observed_low_current_span_s"] == 0


@pytest.mark.parametrize("parameter", [0, -1, float("nan"), float("inf"), True])
def test_invalid_window_rejected(parameter):
    with pytest.raises(ValueError, match="Timing parameters"):
        temperature_rates(
            [0, 1], [[25], [26]], max_gap_s=1, min_interval_s=0.25, window_s=parameter
        )


@pytest.mark.parametrize("times", [[0, -1], [0, float("nan")], []])
def test_invalid_time_axis_rejected(times):
    with pytest.raises(ValueError, match="aligned samples"):
        temperature_rates(
            times, np.ones((len(times), 1)), max_gap_s=1, min_interval_s=0.25, window_s=1
        )
