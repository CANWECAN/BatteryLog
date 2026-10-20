"""Authored observability examples; no physical reference or threshold calibration."""

import json

import pytest

pytest.importorskip("cantools")

from batterylog_research.channel_age_sensitivity import prepare_case, run_campaign


def test_same_temperature_samples_gain_rows_but_not_independent_acquisitions():
    case = prepare_case(analyze=True)
    assert case["anchor_rows"] == case["usable_temperature_rows"] == 101
    assert case["unique_used_context_frames"] == 11
    assert case["reused_context_rows"] == 90
    assert case["context_clock_core"]["rate_status"] == "PASS"
    assert case["prepared_core"]["rate_status"] == "FAIL"
    assert case["prepared_core"]["rate_event_count"] == 10
    assert case["prepared_core"]["maximum_violating_rise_c_per_min"] == pytest.approx(6000)
    assert case["maximum_accepted_age_s"] == 0.09


@pytest.mark.parametrize(
    ("age", "accepted", "reused"), [(0, 11, 0), (0.01, 21, 10), (0.1, 101, 90)]
)
def test_exact_age_budget_changes_coverage_without_filling_expired_rows(age, accepted, reused):
    case = prepare_case(max_age_s=age)
    assert case["usable_temperature_rows"] == accepted
    assert case["missing_or_expired_rows"] == 101 - accepted
    assert case["reused_context_rows"] == reused


def test_equal_timestamp_source_order_does_not_make_future_samples_available():
    before = prepare_case(max_age_s=0, context_first=True)
    after = prepare_case(max_age_s=0, context_first=False)
    assert before["usable_temperature_rows"] == 11
    assert after["usable_temperature_rows"] == 0
    assert after["unique_used_context_frames"] == 0
    assert before["source_sha256"] != after["source_sha256"]


def test_same_authored_pulse_is_missed_or_repeated_with_a_phase_change():
    missed = prepare_case(kind="pulse", phase_ms=0)
    observed = prepare_case(kind="pulse", phase_ms=50)
    assert missed["maximum_prepared_temperature_c"] == 20
    assert missed["prepared_rows_above_55_c"] == 0
    assert observed["maximum_prepared_temperature_c"] == 80
    assert observed["prepared_rows_above_55_c"] == 10
    assert observed["unique_used_context_frames"] == 10


@pytest.mark.parametrize(
    "options",
    [
        {"anchor_ms": 0},
        {"anchor_ms": True},
        {"context_ms": 1001},
        {"phase_ms": -1},
        {"phase_ms": 100},
        {"kind": "physical"},
        {"context_first": 1},
        {"max_age_s": float("nan")},
    ],
)
def test_case_parameters_are_not_coerced(options):
    with pytest.raises((ValueError, TypeError)):
        prepare_case(**options)


def test_campaign_checks_all_source_order_and_age_outcomes():
    report = run_campaign()
    assert report["case_count"] == len(report["cases"]) == 576
    assert report["oracle_mismatches"] == 0
    assert not report["physical_calibration"] and not report["production_decisions_changed"]
    assert len(report["implementation_sha256"]["can_prepare.py"]) == 64
    assert report["showcases"]["pulse_missed"]["prepared_rows_above_55_c"] == 0
    json.dumps(report, allow_nan=False)
