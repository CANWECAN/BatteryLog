"""Independent numeric expectations, censored observations and chunk regressions."""

import copy
import json
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator, ValidationError

from batterylog import (
    AnalysisService,
    BalancingConfig,
    CellSagConfig,
    DataQualityConfig,
    FailureModelConfig,
    SignalMapping,
    SignalPattern,
    SourceUnits,
    SustainedImbalanceConfig,
    TemperatureRiseConfig,
    ValidationConfig,
    ValidationLimits,
    analyze_directory,
    normalize_measurement,
    validate_result_semantics,
)
from batterylog.__main__ import run
from batterylog.analysis.core import _analyze_battery_frame, analyze_battery_bytes
from batterylog.analysis.streaming import (
    _analyze_battery_chunks,
    analyze_battery_file_streaming,
    analyze_battery_file_with_report_series,
    analyze_battery_log_streaming,
    analyze_measurement_loader,
    analyze_measurement_loader_with_report_series,
)
from batterylog.config import load_validation_config_bytes
from batterylog.failure_config import parse_failure_models
from batterylog.loaders import CsvFileLoader
from batterylog.reporting.html import render_html_report

ROOT = Path(__file__).parents[1]
VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "batterylog/schema/result-v9.json").read_text())
)
BALANCE = BalancingConfig("balance_active", 2, 0.03125, 0.125, 4)
SAG = CellSagConfig("discharge", 2, 20, 3, 1, 0.125)


def _frame(times=range(7), *, delta=0.25, **columns):
    times = list(times)
    count = len(times)
    values = {
        "timestamp_s": times,
        "cell_1_v": [3.5] * count,
        "cell_2_v": [3.5] * count,
        "cell_3_v": [3.5 - delta] * count,
        "temp_c": [25.0] * count,
    }
    values.update(columns)
    return pd.DataFrame(values)


def _check(frame, config, **kwargs):
    expected = _analyze_battery_frame(frame, failure_models=config, **kwargs)
    for size in (1, 2, 3, 17):
        chunks = (frame.iloc[i : i + size] for i in range(0, len(frame), size))
        assert _analyze_battery_chunks(chunks, failure_models=config, **kwargs) == expected
    VALIDATOR.validate(json.loads(json.dumps(expected, allow_nan=False)))
    validate_result_semantics(expected)
    return expected


def _evaluation(result, code):
    return next(item for item in result["failure_models"]["evaluations"] if item["code"] == code)


def test_sustained_duration_peak_and_earliest_tie():
    cfg = FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.125, 3))
    frame = _frame(cell_3_v=[3.5, 3.25, 3.25, 3.0, 3.0, 3.25, 3.5])
    result = _check(frame, cfg)
    item = _evaluation(result, "CELL_IMBALANCE_SUSTAINED")
    event = item["events"][0]
    assert item["status"] == "FAIL"
    assert (event["start_time_s"], event["end_time_s"], event["duration_s"]) == (1, 5, 4)
    assert event["peak_time_s"] == 3
    assert event["measured_value"] == 0.5
    assert event["sample_count"] == 5
    assert event["signals"] == ["cell_1_v", "cell_2_v", "cell_3_v"]


@pytest.mark.parametrize("delta", [0, 0.125, np.nextafter(0.125, np.inf)])
def test_sustained_threshold_guard_and_pass(delta):
    result = _check(
        _frame(delta=delta),
        FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.125, 3)),
    )
    assert result["validation_status"] == "PASS"
    assert not result["failure_models"]["evaluations"][0]["events"]


@pytest.mark.parametrize("last,expected", [(2, "FAIL"), (1.99, "NOT_EVALUATED")])
def test_sustained_exact_duration_boundary(last, expected):
    result = _check(
        _frame([0, 1, last]),
        FailureModelConfig(1.1, sustained_imbalance=SustainedImbalanceConfig(0.125, 2)),
    )
    assert result["validation_status"] == expected


def test_short_bursts_do_not_accumulate_duration():
    frame = _frame(cell_3_v=[3.25, 3.25, 3.5, 3.25, 3.25, 3.5, 3.5])
    result = _check(
        frame, FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.125, 2))
    )
    assert result["validation_status"] == "PASS"


@pytest.mark.parametrize("gap", [1, 1.01])
def test_gap_limit_exact_boundary(gap):
    result = _check(
        _frame([0, gap, 2 * gap]),
        FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.125, 2)),
    )
    assert result["validation_status"] == ("FAIL" if gap == 1 else "NOT_EVALUATED")


def test_excluded_measurement_breaks_all_temporal_continuity():
    frame = _frame(temp_c=[25, 25, "bad", 25, 25, 25, 25])
    result = _check(
        frame,
        FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.125, 4)),
        data_quality=DataQualityConfig("exclude_invalid_rows"),
    )
    assert result["rows_excluded"] == 1
    assert result["validation_status"] == "FAIL"
    assert _evaluation(result, "CELL_IMBALANCE_SUSTAINED")["status"] == "NOT_EVALUATED"


def test_unrounded_later_peak_survives_chunk_boundary():
    frame = _frame([0, 1, 2], cell_3_v=[3.25, 3.25 - 4e-13, 3.25])
    result = _check(
        frame, FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.125, 2))
    )
    assert _evaluation(result, "CELL_IMBALANCE_SUSTAINED")["events"][0]["peak_time_s"] == 1


def test_temperature_rate_uses_minutes_and_reports_sample_pair():
    result = _check(
        _frame([0, 30, 60], temp_c=[25, 26, 24]),
        FailureModelConfig(30, temperature_rise=TemperatureRiseConfig(1, 1)),
    )
    event = _evaluation(result, "TEMPERATURE_RISE_HIGH")["events"][0]
    assert event["measured_value"] == 2
    assert event["start_time_s"] == event["end_time_s"] == event["peak_time_s"] == 30
    assert event["evidence"] == {
        "previous_time_s": 0,
        "interval_s": 30,
        "previous_temperature_c": 25,
        "temperature_c": 26,
    }


def test_temperature_duplicate_replaces_reference_and_breaks_event():
    result = _check(
        _frame([0, 1, 1, 2], temp_c=[25, 26, 50, 51]),
        FailureModelConfig(1, temperature_rise=TemperatureRiseConfig(10, 0.1)),
    )
    events = _evaluation(result, "TEMPERATURE_RISE_HIGH")["events"]
    assert len(events) == 2
    assert [event["measured_value"] for event in events] == [60, 60]
    assert events[1]["evidence"]["previous_temperature_c"] == 50


@pytest.mark.parametrize(
    "times,status",
    [
        ([0, 0], "NOT_EVALUATED"),
        ([0, 0.05], "NOT_EVALUATED"),
        ([0, 2], "NOT_EVALUATED"),
        ([0, 0.1], "PASS"),
        ([0, 1], "PASS"),
    ],
)
def test_temperature_pair_eligibility(times, status):
    result = _check(
        _frame(times), FailureModelConfig(1, temperature_rise=TemperatureRiseConfig(10, 0.1))
    )
    assert result["validation_status"] == status


def test_temperature_fastest_sensor_and_cooling():
    frame = _frame([0, 1, 2]).drop(columns="temp_c")
    frame["temp_1_c"] = [25, 24, 23]
    frame["temp_2_c"] = [25, 27, 30]
    result = _check(frame, FailureModelConfig(1, temperature_rise=TemperatureRiseConfig(60, 0.1)))
    event = _evaluation(result, "TEMPERATURE_RISE_HIGH")["events"][0]
    assert event["measured_value"] == 180
    assert event["peak_time_s"] == 2
    assert event["signals"] == ["temp_2_c"]


@pytest.mark.parametrize(
    "values,limit,status", [([25, 26], 60, "PASS"), ([26, 25], 0, "PASS"), ([25, 25], 0, "PASS")]
)
def test_temperature_rate_exact_threshold(values, limit, status):
    assert (
        _check(
            _frame([0, 1], temp_c=values),
            FailureModelConfig(1, temperature_rise=TemperatureRiseConfig(limit, 0.1)),
        )["validation_status"]
        == status
    )


def _sag_frame(current=(0, 40, 40, 40, 0)):
    return _frame(
        range(5),
        delta=0,
        pack_current_a=list(current),
        cell_1_v=[3.5, 3.375, 3.375, 3.375, 3.5],
        cell_2_v=[3.5, 3.375, 3.375, 3.375, 3.5],
        cell_3_v=[3.5, 3.0, 3.0, 3.0, 3.5],
    )


def test_cell_sag_frozen_baseline_settling_and_relative_drop():
    result = _check(_sag_frame(), FailureModelConfig(1, cell_sag=SAG))
    event = _evaluation(result, "CELL_SAG_UNDER_LOAD")["events"][0]
    assert event["start_time_s"] == 2
    assert event["end_time_s"] == 3
    assert event["measured_value"] == 0.375  # 0.5 V cell drop minus 0.125 V peer median.
    assert event["signals"] == ["cell_3_v"]
    assert event["evidence"]["baseline_time_s"] == 0
    assert event["evidence"]["load_start_time_s"] == 1
    assert event["evidence"]["median_sag_v"] == 0.125


def test_cell_sag_charge_positive_sign_convention_is_equivalent():
    positive = _check(_sag_frame(), FailureModelConfig(1, cell_sag=SAG))
    negative = _check(
        _sag_frame((0, -40, -40, -40, 0)),
        FailureModelConfig(1, cell_sag=replace(SAG, positive_direction="charge")),
    )
    assert negative["validation_status"] == positive["validation_status"] == "FAIL"
    assert _evaluation(negative, "CELL_SAG_UNDER_LOAD")["events"][0]["measured_value"] == 0.375


@pytest.mark.parametrize(
    "case",
    [
        "missing_current",
        "too_few_cells",
        "starts_loaded",
        "no_load",
        "too_short",
        "same_time",
        "stale_baseline",
    ],
)
def test_cell_sag_ineligible_cases_never_pass(case):
    frame = _sag_frame()
    if case == "missing_current":
        frame = frame.drop(columns="pack_current_a")
    if case == "too_few_cells":
        frame = frame.drop(columns="cell_2_v")
    if case == "starts_loaded":
        frame = frame.iloc[1:]
    if case == "no_load":
        frame["pack_current_a"] = 0
    if case == "too_short":
        frame = frame.iloc[:2]
    if case == "same_time":
        frame["timestamp_s"] = [0, 0, 0, 0, 1]
    if case == "stale_baseline":
        frame["pack_current_a"] = [0, 10, 10, 40, 40]
        frame["timestamp_s"] = [0, 1, 2, 3, 4]
    cfg = replace(SAG, baseline_max_age_s=2) if case == "stale_baseline" else SAG
    assert (
        _check(frame, FailureModelConfig(1, cell_sag=cfg))["validation_status"] == "NOT_EVALUATED"
    )


def test_uniform_load_sag_and_exact_relative_limit_pass():
    for third in (3.375, 3.25):
        frame = _sag_frame()
        frame["cell_3_v"] = [3.5, third, third, third, 3.5]
        assert _check(frame, FailureModelConfig(1, cell_sag=SAG))["validation_status"] == "PASS"


def test_rest_reference_updates_and_load_reference_is_frozen():
    frame = _frame(
        range(7),
        delta=0,
        pack_current_a=[0, 0, 20, 20, 20, 0, 0],
        cell_3_v=[3.5, 3.25, 3.0, 3.0, 2.75, 3.5, 3.5],
    )
    result = _check(frame, FailureModelConfig(1, cell_sag=SAG))
    event = _evaluation(result, "CELL_SAG_UNDER_LOAD")["events"][0]
    assert event["evidence"]["baseline_time_s"] == 1
    assert event["evidence"]["baseline_cell_v"] == 3.25
    assert event["measured_value"] == 0.5
    assert event["peak_time_s"] == 4


def _balance_frame(*, improvement=0, status=(0, 1, 1, 1, 1, 1, 1, 0)):
    count = len(status)
    return _frame(
        range(count),
        delta=0.25,
        balance_active=list(status),
        cell_3_v=[3.25 if i < 3 else 3.25 + improvement for i in range(count)],
    )


def test_balancing_ineffective_and_timeout_first_detection():
    result = _check(_balance_frame(), FailureModelConfig(1, balancing=BALANCE))
    ineffective = _evaluation(result, "BALANCING_INEFFECTIVE")
    timeout = _evaluation(result, "BALANCING_ACTIVE_TOO_LONG")
    assert len(ineffective["events"]) == len(timeout["events"]) == 1
    assert ineffective["events"][0]["end_time_s"] == 3
    assert ineffective["events"][0]["measured_value"] == 0
    assert timeout["events"][0]["end_time_s"] == 6
    assert timeout["events"][0]["measured_value"] == 5
    assert timeout["events"][0]["signals"] == ["balance_active", "cell_1_v", "cell_2_v", "cell_3_v"]


def test_balancing_exact_improvement_and_timeout_boundaries_pass():
    result = _check(
        _balance_frame(improvement=0.03125, status=(0, 1, 1, 1, 1, 1, 0)),
        FailureModelConfig(1, balancing=BALANCE),
    )
    assert result["validation_status"] == "PASS"
    assert all(item["status"] == "PASS" for item in result["failure_models"]["evaluations"])


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "starts_active",
        "never_active",
        "ends_active",
        "too_short",
        "small_initial",
        "gap",
    ],
)
def test_balancing_censored_and_missing_cases(case):
    frame = _balance_frame(improvement=0.0625, status=(0, 1, 1, 1, 0))
    if case == "missing":
        frame = frame.drop(columns="balance_active")
    if case == "starts_active":
        frame["balance_active"] = [1, 1, 1, 1, 0]
    if case == "never_active":
        frame["balance_active"] = 0
    if case == "ends_active":
        frame = frame.iloc[:-1]
    if case == "too_short":
        frame["balance_active"] = [0, 1, 0, 0, 0]
    if case == "small_initial":
        frame["cell_3_v"] = 3.4375
    if case == "gap":
        frame["timestamp_s"] = [0, 1, 10, 11, 12]
    result = _check(
        frame, FailureModelConfig(1, balancing=BALANCE), limits=ValidationLimits(cell_max_v=4.2)
    )
    assert result["validation_status"] == "NOT_EVALUATED"
    assert any(
        item["status"] == "NOT_EVALUATED" for item in result["failure_models"]["evaluations"]
    )
    assert "lack eligible observations" in render_html_report(result)


@pytest.mark.parametrize("bad", [2, -1, "active", None, float("nan"), float("inf")])
def test_bad_balancing_state_rejects_or_makes_observation_incomplete(bad):
    frame = _balance_frame(improvement=0.0625, status=(0, 1, 1, 1, 0))
    frame["balance_active"] = pd.Series([0, bad, 1, 1, 0], dtype=object)
    cfg = FailureModelConfig(1, balancing=BALANCE)
    with pytest.raises(ValueError, match="Balancing status"):
        _analyze_battery_frame(frame, failure_models=cfg)
    with pytest.raises(ValueError, match="data row 2"):
        _analyze_battery_chunks((frame.iloc[:1], frame.iloc[1:]), failure_models=cfg)
    result = _check(frame, cfg, data_quality=DataQualityConfig("exclude_invalid_rows"))
    assert result["validation_status"] == "NOT_EVALUATED"
    assert all(
        item["incomplete_intervals"] == 1
        and item["reason"] == "Invalid balancing status samples were excluded"
        for item in result["failure_models"]["evaluations"]
    )


def test_contiguous_invalid_balancing_status_is_one_incomplete_interval():
    frame = _balance_frame(improvement=0.0625, status=(0, 1, 1, 1, 1, 0))
    frame["balance_active"] = pd.Series([0, 1, 2, 2, 1, 0], dtype=object)
    result = _check(
        frame,
        FailureModelConfig(1, balancing=BALANCE),
        data_quality=DataQualityConfig("exclude_invalid_rows"),
    )
    assert all(
        item["incomplete_intervals"] == 1
        and item["reason"] == "Invalid balancing status samples were excluded"
        for item in result["failure_models"]["evaluations"]
    )


def test_boolean_and_text_balancing_states_are_equivalent():
    cfg = FailureModelConfig(1, balancing=BALANCE)
    numeric = _check(_balance_frame(), cfg)
    for cast in (bool, str):
        frame = _balance_frame()
        frame["balance_active"] = frame["balance_active"].astype(cast)
        assert _check(frame, cfg) == numeric
    frame["balance_active"] = ["false", "true", "true", "true", "true", "true", "true", "false"]
    assert _check(frame, cfg) == numeric


def test_left_censored_session_prevents_pass_even_after_eligible_session():
    frame = _balance_frame(improvement=0.0625, status=(1, 0, 1, 1, 1, 0))
    result = _check(frame, FailureModelConfig(1, balancing=BALANCE))
    assert result["validation_status"] == "NOT_EVALUATED"
    assert all(
        item["incomplete_intervals"] == 1 for item in result["failure_models"]["evaluations"]
    )


def test_balancing_status_role_conflicts_duplicate_and_chunk_presence_change():
    frame = _balance_frame()
    for source in ("timestamp_s", "cell_1_v", "temp_c"):
        with pytest.raises(ValueError, match="measurement role"):
            _analyze_battery_frame(
                frame,
                failure_models=FailureModelConfig(
                    1, balancing=replace(BALANCE, active_source=source)
                ),
            )
    doubled = pd.concat([frame, frame[["balance_active"]]], axis=1)
    with pytest.raises(ValueError, match="Duplicate balancing"):
        _analyze_battery_frame(doubled, failure_models=FailureModelConfig(1, balancing=BALANCE))
    with pytest.raises(ValueError, match="presence changed"):
        _analyze_battery_chunks(
            (frame.iloc[:2], frame.iloc[2:].drop(columns="balance_active")),
            failure_models=FailureModelConfig(1, balancing=BALANCE),
        )


def test_explicit_mapping_preserves_named_status_and_rejects_alias():
    frame = _balance_frame().rename(
        columns={
            "timestamp_s": "Time",
            "temp_c": "T1",
            "cell_1_v": "V1",
            "cell_2_v": "V2",
            "cell_3_v": "V3",
            "balance_active": "Bal",
        }
    )
    mapping = SignalMapping(
        "Time", SignalPattern(r"V(?P<index>\d+)"), SignalPattern(r"T(?P<index>\d+)")
    )
    result = _check(
        frame,
        FailureModelConfig(1, balancing=replace(BALANCE, active_source="Bal")),
        signal_mapping=mapping,
    )
    assert result["validation_status"] == "FAIL"
    with pytest.raises(ValueError, match="measurement role"):
        _analyze_battery_frame(
            frame,
            failure_models=FailureModelConfig(1, balancing=replace(BALANCE, active_source="V1")),
            signal_mapping=mapping,
        )


@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize("chunk_rows", [1, 20])
@pytest.mark.parametrize("line_ending", ["\n", "\r\n"], ids=["LF", "CRLF"])
def test_normalization_preserves_balancing_status_and_identity_chain(
    tmp_path, monkeypatch, mapped, chunk_rows, line_ending
):
    from batterylog import normalization as module

    monkeypatch.setattr(module, "DEFAULT_CSV_CHUNK_ROWS", chunk_rows)
    frame = _balance_frame()
    frame["timestamp_s"] *= 1000
    for name in ("cell_1_v", "cell_2_v", "cell_3_v"):
        frame[name] *= 1000
    frame["temp_c"] = 298.15
    frame = frame.rename(columns={"balance_active": "Bal"})
    mapping = None
    if mapped:
        frame = frame.rename(
            columns={
                "timestamp_s": "Clock",
                "temp_c": "T1",
                "cell_1_v": "V1",
                "cell_2_v": "V2",
                "cell_3_v": "V3",
            }
        )
        mapping = SignalMapping(
            "Clock", SignalPattern(r"V(?P<index>\d+)"), SignalPattern(r"T(?P<index>\d+)")
        )
    models = FailureModelConfig(1, balancing=replace(BALANCE, active_source="Bal"))
    path = tmp_path / "source.csv"
    frame.to_csv(path, index=False, lineterminator=line_ending)
    output = tmp_path / "prepared"
    conversion = normalize_measurement(
        path,
        output,
        units=SourceUnits("ms", "mV", "K"),
        config=ValidationConfig(signals=mapping, failure_models=models),
    )
    normalized = pd.read_csv(output / "normalized.csv")
    assert normalized["Bal"].tolist() == [0, 1, 1, 1, 1, 1, 1, 0]
    chain = next(c for c in conversion["conversions"] if c["canonical"] == "Bal")
    assert chain == {
        "source": "Bal",
        "canonical": "Bal",
        "source_unit": "1",
        "target_unit": "1",
        "divisor": 1.0,
        "offset": 0.0,
    }
    expected = _check(_balance_frame().rename(columns={"balance_active": "Bal"}), models)
    actual = (
        AnalysisService(ValidationConfig(failure_models=models))
        .analyze_path(output / "normalized.csv")
        .result
    )
    assert actual == expected
    assert conversion["analysis_performed"] is False


def test_normalization_rejects_bad_status_and_canonical_name_collision(tmp_path):
    frame = _balance_frame()
    frame["balance_active"] = [0, 2, 1, 1, 1, 1, 1, 0]
    path = tmp_path / "source.csv"
    frame.to_csv(path, index=False)
    config = ValidationConfig(
        failure_models=FailureModelConfig(1, balancing=BALANCE),
        data_quality=DataQualityConfig("exclude_invalid_rows"),
    )
    with pytest.raises(ValueError, match="Balancing status"):
        normalize_measurement(
            path, tmp_path / "out", units=SourceUnits("s", "V", "degC"), config=config
        )
    assert not (tmp_path / "out").exists()
    frame = _balance_frame().rename(
        columns={
            "timestamp_s": "Clock",
            "temp_c": "T1",
            "cell_1_v": "V1",
            "cell_2_v": "V2",
            "cell_3_v": "V3",
            "balance_active": "cell_1_v",
        }
    )
    mapping = SignalMapping(
        "Clock", SignalPattern(r"V(?P<index>\d+)"), SignalPattern(r"T(?P<index>\d+)")
    )
    with pytest.raises(ValueError, match="measurement role"):
        _analyze_battery_frame(
            frame,
            signal_mapping=mapping,
            failure_models=FailureModelConfig(
                1, balancing=replace(BALANCE, active_source="cell_1_v")
            ),
        )


def test_normalization_rejects_status_disappearing_between_chunks(tmp_path, monkeypatch):
    from batterylog import normalization as module

    frame = _balance_frame()
    source = tmp_path / "source.csv"
    frame.to_csv(source, index=False)
    monkeypatch.setattr(
        module,
        "iter_battery_csv_file",
        lambda *args, **kwargs: iter(
            (frame.iloc[:2], frame.iloc[2:].drop(columns="balance_active"))
        ),
    )
    with pytest.raises(ValueError, match="presence changed during normalization"):
        normalize_measurement(
            source,
            tmp_path / "out",
            units=SourceUnits("s", "V", "degC"),
            config=ValidationConfig(failure_models=FailureModelConfig(1, balancing=BALANCE)),
        )
    assert not (tmp_path / "out").exists()


def test_semantic_validation_rejects_v9_absence_wrong_status_and_v8_extension():
    result = _check(
        _frame(), FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.125, 2))
    )
    absent = copy.deepcopy(result)
    absent.pop("failure_models")
    with pytest.raises(ValueError, match="requires failure_models"):
        validate_result_semantics(absent)
    wrong = copy.deepcopy(result)
    wrong["validation_status"] = "PASS"
    with pytest.raises(ValueError, match="validation_status"):
        validate_result_semantics(wrong)
    legacy = copy.deepcopy(result)
    legacy["schema_version"] = 8
    with pytest.raises(ValueError, match="cannot contain"):
        validate_result_semantics(legacy)


@pytest.mark.parametrize("bad", [True, -1, 0, float("nan"), float("inf"), 10**400, "2"])
def test_invalid_common_time_parameters(bad):
    with pytest.raises((TypeError, ValueError)):
        FailureModelConfig(bad, sustained_imbalance=SustainedImbalanceConfig(0.125, 2))


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {},
        {"max_gap_s": 1},
        {"max_gap_s": 1, "bogus": {}},
        {"max_gap_s": 1, "sustained_imbalance": []},
        {"max_gap_s": 1, "sustained_imbalance": {}},
        {"max_gap_s": 1, "sustained_imbalance": {"max_delta_v": 0.1, "duration_s": 2, "typo": 1}},
        {"max_gap_s": 1, "sustained_imbalance": {"max_delta_v": True, "duration_s": 2}},
    ],
)
def test_malformed_model_config_rejected(raw):
    with pytest.raises((TypeError, ValueError)):
        parse_failure_models(raw)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TemperatureRiseConfig(1, 0),
        lambda: CellSagConfig("unknown", 2, 20, 3, 1, 0.1),
        lambda: CellSagConfig("charge", 20, 20, 3, 1, 0.1),
        lambda: BalancingConfig("", 2, 0.02, 0.1, 5),
        lambda: BalancingConfig(1, 2, 0.02, 0.1, 5),
        lambda: BalancingConfig("bal", 2, 0.2, 0.1, 5),
        lambda: FailureModelConfig(1, temperature_rise=TemperatureRiseConfig(1, 2)),
        lambda: FailureModelConfig(1, cell_sag={}),
        lambda: ValidationConfig(failure_models={}),
    ],
)
def test_contradictory_and_wrong_type_config_rejected(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_config_version_gate_and_current_conventions():
    data = (ROOT / "examples/failure_models.example.yaml").read_bytes()
    cfg = load_validation_config_bytes(data)
    assert cfg.failure_models.cell_sag == SAG.__class__("discharge", 2, 20, 5, 1, 0.1)
    with pytest.raises(ValueError, match="Unknown top-level"):
        load_validation_config_bytes(data.replace(b"schema_version: 7", b"schema_version: 6"))
    assert parse_failure_models(None) is None
    assert parse_failure_models(asdict(cfg.failure_models)) == cfg.failure_models
    limits = ValidationLimits(pack_discharge_max_a=100, pack_current_positive_direction="charge")
    with pytest.raises(ValueError, match="same positive_direction"):
        ValidationConfig(limits=limits, failure_models=FailureModelConfig(1, cell_sag=SAG))
    with pytest.raises(ValueError, match="same positive_direction"):
        _analyze_battery_frame(
            _sag_frame(), limits=limits, failure_models=FailureModelConfig(1, cell_sag=SAG)
        )
    with pytest.raises(TypeError, match="FailureModelConfig"):
        _analyze_battery_frame(_frame(), failure_models={})


@pytest.mark.parametrize("case", ["temperature", "sag", "time"])
def test_derived_arithmetic_overflow_fails_closed(case):
    if case == "temperature":
        frame = _frame([0, 1], temp_c=[-1e308, 1e308])
        cfg = FailureModelConfig(1, temperature_rise=TemperatureRiseConfig(1, 0.1))
    elif case == "sag":
        frame = _frame(
            [0, 1],
            cell_1_v=[1e308, -1e308],
            cell_2_v=[1e308, -1e308],
            cell_3_v=[1e308, -1e308],
            pack_current_a=[0, 40],
        )
        cfg = FailureModelConfig(1, cell_sag=replace(SAG, settling_s=0))
    else:
        frame = _frame([-1e308, 1e308])
        cfg = FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.125, 2))
    for chunks in (False, True):
        with pytest.raises(ValueError, match="overflowed"):
            if chunks:
                _analyze_battery_chunks((frame.iloc[:1], frame.iloc[1:]), failure_models=cfg)
            else:
                _analyze_battery_frame(frame, failure_models=cfg)


def test_all_models_service_cli_reports_and_legacy_contract(tmp_path, capsys):
    cfg = load_validation_config_bytes((ROOT / "examples/failure_models.example.yaml").read_bytes())
    data = (ROOT / "examples/failure_models_demo.csv").read_bytes()
    expected = analyze_battery_bytes(data, limits=cfg.limits, failure_models=cfg.failure_models)
    VALIDATOR.validate(expected)
    assert expected["validation_status"] == "FAIL"
    assert expected["rules_evaluated"] == ["PACK_VOLTAGE_CELL_SUM_MISMATCH"]
    assert len(expected["violations"]) == 1
    assert all(item["events"] for item in expected["failure_models"]["evaluations"])
    loader = CsvFileLoader(BytesIO(data), chunk_rows=1)
    service = AnalysisService(cfg)
    output = service.analyze_loader(loader, report_max_points=20)
    assert output.result == expected
    kwargs = {"limits": cfg.limits, "failure_models": cfg.failure_models}
    assert (
        analyze_measurement_loader(CsvFileLoader(BytesIO(data), chunk_rows=2), **kwargs) == expected
    )
    assert (
        analyze_measurement_loader_with_report_series(CsvFileLoader(BytesIO(data)), **kwargs)[0]
        == expected
    )
    assert analyze_battery_file_streaming(BytesIO(data), **kwargs) == expected
    assert analyze_battery_file_with_report_series(BytesIO(data), **kwargs)[0] == expected
    path = tmp_path / "measurement.csv"
    path.write_bytes(data)
    assert analyze_battery_log_streaming(path, **kwargs) == expected
    report = tmp_path / "report.html"
    result_path = tmp_path / "result.json"
    assert (
        run(
            [
                str(path),
                "--config",
                str(ROOT / "examples/failure_models.example.yaml"),
                "--report",
                str(report),
                "--json-out",
                str(result_path),
            ]
        )
        == 1
    )
    capsys.readouterr()
    assert json.loads(result_path.read_text()) == expected
    html = report.read_text()
    assert "Failure model outcomes" in html
    for item in expected["failure_models"]["evaluations"]:
        assert item["code"] in html
    assert "median_sag_v" in html and "improvement_v" in html
    inputs = tmp_path / "batch-inputs"
    inputs.mkdir()
    (inputs / "measurement.csv").write_bytes(data)
    batch = analyze_directory(inputs, tmp_path / "batch-results", service=service)
    assert batch["files"][0]["status"] == "FAIL"
    assert batch["files"][0]["violation_events"] == 6
    legacy = analyze_battery_bytes(data)
    assert legacy["schema_version"] == 8 and "failure_models" not in legacy
    old = Draft202012Validator(json.loads((ROOT / "batterylog/schema/result-v8.json").read_text()))
    old.validate(legacy)
    with pytest.raises(ValidationError):
        old.validate(expected)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["failure_models"]["evaluations"].pop(),
        lambda r: r["failure_models"]["evaluations"].append(
            copy.deepcopy(r["failure_models"]["evaluations"][0])
        ),
        lambda r: r["failure_models"]["evaluations"][0]["events"][0].update(duration_s=9),
        lambda r: r["failure_models"]["evaluations"][0]["events"][0].update(limit_value=2),
        lambda r: r.update(validation_status="PASS"),
        lambda r: r["failure_models"]["evaluations"][0]["events"][0]["evidence"].update(
            cell_min_v=0
        ),
    ],
)
def test_mutated_model_provenance_or_arithmetic_is_rejected(mutation):
    result = _check(
        _frame(), FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.125, 2))
    )
    mutation(result)
    with pytest.raises((ValueError, ValidationError)):
        VALIDATOR.validate(result)
        validate_result_semantics(result)


@settings(max_examples=100, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from([0, 0.5, 1, 3]), st.sampled_from([0, 0.0625, 0.25]), st.booleans()
        ),
        min_size=1,
        max_size=20,
    )
)
def test_randomized_sustained_intervals_match_independent_oracle(rows):
    times = []
    deltas = []
    valid = []
    t = 0
    for dt, delta, ok in rows:
        t += dt
        times.append(t)
        deltas.append(delta)
        valid.append(ok)
    frame = _frame(
        times,
        cell_3_v=[3.5 - d for d in deltas],
        temp_c=[25 if ok else float("nan") for ok in valid],
    )
    config = FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.125, 1))
    result = _check(frame, config, data_quality=DataQualityConfig("exclude_invalid_rows"))
    ranges = []
    active = []
    for i, (t, delta, ok) in enumerate(zip(times, deltas, valid)):
        if not ok or delta <= 0.125 or (active and t - times[active[-1]] > 1):
            if active and times[active[-1]] - times[active[0]] >= 1:
                ranges.append((times[active[0]], times[active[-1]], len(active)))
            active = []
        if ok and delta > 0.125:
            active.append(i)
    if active and times[active[-1]] - times[active[0]] >= 1:
        ranges.append((times[active[0]], times[active[-1]], len(active)))
    actual = _evaluation(result, "CELL_IMBALANCE_SUSTAINED")["events"]
    assert [(e["start_time_s"], e["end_time_s"], e["sample_count"]) for e in actual] == ranges
