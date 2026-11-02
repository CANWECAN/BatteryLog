"""Independent no-load persistence expectations across adapters and output contracts."""

import copy
import json
from dataclasses import asdict, replace
from io import BytesIO
from itertools import pairwise
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
    DataQualityConfig,
    FailureModelConfig,
    SignalMapping,
    SignalPattern,
    SourceUnits,
    SustainedImbalanceConfig,
    UnloadedCurrentConfig,
    ValidationConfig,
    analyze_directory,
    normalize_measurement,
    validate_result_semantics,
)
from batterylog.__main__ import run
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import _analyze_battery_chunks
from batterylog.config import load_validation_config_bytes
from batterylog.failure_config import parse_failure_models
from batterylog.reporting.html import render_html_report

ROOT = Path(__file__).parents[1]
SCHEMA = Draft202012Validator(json.loads((ROOT / "batterylog/schema/result-v9.json").read_text()))
MODEL = UnloadedCurrentConfig("unloaded", 0.5, 2)
MODELS = FailureModelConfig(1, unloaded_current=MODEL)


def _frame(current, *, state=None, times=None):
    count = len(current)
    return pd.DataFrame(
        {
            "timestamp_s": list(range(count)) if times is None else times,
            "cell_1_v": [3.5] * count,
            "cell_2_v": [3.5] * count,
            "temp_c": [25.0] * count,
            "pack_current_a": current,
            "unloaded": [True] * count if state is None else state,
        }
    )


def _check(frame, models=MODELS, **kwargs):
    result = _analyze_battery_frame(frame, failure_models=models, **kwargs)
    for size in (1, 2, 3, 17):
        chunks = (frame.iloc[start : start + size] for start in range(0, len(frame), size))
        assert _analyze_battery_chunks(chunks, failure_models=models, **kwargs) == result
    SCHEMA.validate(json.loads(json.dumps(result, allow_nan=False)))
    validate_result_semantics(result)
    return result


def _item(result):
    return next(
        e for e in result["failure_models"]["evaluations"] if e["code"] == "CURRENT_WHILE_UNLOADED"
    )


def test_signed_peak_chain_earliest_tie_and_state_edges():
    frame = _frame([20, 0, 1, -2, 2, 1, 20], state=[False, True, True, True, True, True, False])
    item = _item(_check(frame))
    assert item["status"] == "FAIL"
    assert item["incomplete_intervals"] == 0
    event = item["events"][0]
    assert (
        event["start_time_s"],
        event["end_time_s"],
        event["duration_s"],
        event["sample_count"],
    ) == (2, 5, 3, 4)
    assert (event["peak_time_s"], event["measured_value"], event["limit_value"], event["unit"]) == (
        3,
        2,
        0.5,
        "A",
    )
    assert event["signals"] == ["pack_current_a", "unloaded"]
    assert event["evidence"] == {"current_a": -2, "unloaded_status": 1, "required_duration_s": 2}


@pytest.mark.parametrize("current", [0, 0.5, -0.5, np.nextafter(0.5, np.inf)])
def test_boundary_guard_and_both_current_directions_pass(current):
    assert _item(_check(_frame([current] * 4)))["status"] == "PASS"


@pytest.mark.parametrize("current", [0.75, -0.75])
def test_exact_duration_at_eof_is_failure(current):
    item = _item(_check(_frame([current] * 3)))
    assert item["status"] == "FAIL"
    assert item["events"][0]["duration_s"] == 2


def test_short_spikes_inside_qualified_unloaded_span_do_not_accumulate():
    item = _item(_check(_frame([1, 1, 0, -1, -1, 0, 0])))
    assert item["status"] == "PASS" and not item["events"]


@pytest.mark.parametrize(
    "state,times",
    [([True, True, False, True, True], None), ([True] * 4, [0, 1, 3, 4]), ([True] * 3, [0, 0, 0])],
)
def test_transitions_gaps_and_duplicates_do_not_invent_elapsed_time(state, times):
    item = _item(_check(_frame([1] * len(state), state=state, times=times)))
    assert item["status"] == "NOT_EVALUATED" and not item["events"]
    assert item["incomplete_intervals"] > 0


def test_gap_at_limit_and_repeated_time_keep_observed_duration():
    item = _item(_check(_frame([1] * 4, times=[0, 1, 1, 2])))
    assert item["status"] == "FAIL"
    assert item["events"][0]["sample_count"] == 4


@pytest.mark.parametrize("missing", ["unloaded", "pack_current_a"])
def test_missing_source_is_not_evaluated(missing):
    item = _item(_check(_frame([1] * 4).drop(columns=missing)))
    assert item["status"] == "NOT_EVALUATED" and "Missing" in item["reason"]


def test_loaded_only_is_not_evaluated_even_with_large_current():
    assert _item(_check(_frame([20] * 4, state=[False] * 4)))["status"] == "NOT_EVALUATED"


@pytest.mark.parametrize("value", [True, False, 0, 1, 0.0, 1.0, " true ", "FALSE", "0", "1"])
def test_explicit_binary_status_forms(value):
    item = _item(_check(_frame([0] * 3, state=[value] * 3)))
    assert item["status"] == (
        "PASS" if str(value).strip().lower() in {"1", "1.0", "true"} else "NOT_EVALUATED"
    )


@pytest.mark.parametrize("value", [None, np.nan, np.inf, -1, 2, "idle", "1.0", "", pd.NA, [1]])
def test_invalid_state_strict_error_is_chunk_independent(value):
    frame = _frame([0] * 5, state=[True, True, value, True, True])
    for size in (1, 2, 7):
        with pytest.raises(ValueError, match="Unloaded status.*data row 3"):
            _analyze_battery_chunks(
                (frame.iloc[i : i + size] for i in range(0, len(frame), size)),
                failure_models=MODELS,
            )
    with pytest.raises(ValueError, match="Unloaded status.*data row 3"):
        _analyze_battery_frame(frame, failure_models=MODELS)


def test_excluded_unknown_state_interrupts_only_this_model_and_counts_one_unknown_run():
    frame = _frame([0] * 8, state=[True, True, True, "bad", "bad", True, True, True])
    models = replace(MODELS, sustained_imbalance=SustainedImbalanceConfig(0.2, 2))
    result = _check(frame, models, data_quality=DataQualityConfig("exclude_invalid_rows"))
    assert result["rows_excluded"] == 0
    assert result["failure_models"]["evaluations"][0]["status"] == "PASS"
    item = _item(result)
    assert item["status"] == "NOT_EVALUATED" and item["incomplete_intervals"] == 1


def test_excluded_measurement_breaks_current_run_and_preserves_completed_failure():
    frame = _frame([1, 1, 1, "bad", 1, 1])
    result = _check(frame, data_quality=DataQualityConfig("exclude_invalid_rows"))
    assert result["rows_excluded"] == 1
    item = _item(result)
    assert item["status"] == "FAIL"
    assert [(e["start_time_s"], e["end_time_s"]) for e in item["events"]] == [(0, 2)]


def test_excluded_measurement_does_not_allow_false_pass_after_qualified_span():
    result = _check(
        _frame([0, 0, 0, "bad", 0, 0, 0]), data_quality=DataQualityConfig("exclude_invalid_rows")
    )
    assert _item(result)["status"] == "NOT_EVALUATED"


@pytest.mark.parametrize("source", ["pack_current_a", "timestamp_s", "cell_1_v", "temp_c"])
def test_status_cannot_reuse_measurement_role(source):
    with pytest.raises(ValueError, match="measurement role"):
        _analyze_battery_frame(
            _frame([0] * 4),
            failure_models=replace(MODELS, unloaded_current=replace(MODEL, unloaded_source=source)),
        )


def test_duplicate_status_and_changed_presence_are_rejected():
    frame = _frame([0] * 4)
    with pytest.raises(ValueError, match="Duplicate unloaded"):
        _analyze_battery_frame(
            pd.concat([frame, frame[["unloaded"]]], axis=1), failure_models=MODELS
        )
    with pytest.raises(ValueError, match="presence changed"):
        _analyze_battery_chunks(
            [frame.iloc[:2], frame.iloc[2:].drop(columns="unloaded")], failure_models=MODELS
        )


def test_mapping_retains_independent_state_and_rejects_mapped_current_as_state():
    frame = _frame([1] * 3).rename(
        columns={
            "timestamp_s": "Time",
            "cell_1_v": "V1",
            "cell_2_v": "V2",
            "temp_c": "T1",
            "pack_current_a": "I",
        }
    )
    mapping = SignalMapping(
        "Time", SignalPattern(r"V(?P<index>\d+)"), SignalPattern(r"T(?P<index>\d+)"), "I"
    )
    assert _item(_check(frame, signal_mapping=mapping))["status"] == "FAIL"
    with pytest.raises(ValueError, match="measurement role"):
        _analyze_battery_frame(
            frame,
            signal_mapping=mapping,
            failure_models=replace(MODELS, unloaded_current=replace(MODEL, unloaded_source="I")),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"duration_s": 0},
        {"duration_s": True},
        {"max_abs_current_a": -1},
        {"max_abs_current_a": np.inf},
        {"unloaded_source": " "},
        {"unloaded_source": 1},
    ],
)
def test_invalid_configuration_is_rejected(change):
    with pytest.raises((TypeError, ValueError)):
        replace(MODEL, **change)


def test_yaml_schema_and_disabled_payload_compatibility():
    data = b"schema_version: 7\nfailure_models:\n  max_gap_s: 1\n  unloaded_current:\n    unloaded_source: unloaded\n    max_abs_current_a: 0.5\n    duration_s: 2\n"
    config = load_validation_config_bytes(data)
    assert config.failure_models == MODELS
    assert parse_failure_models(asdict(MODELS)) == MODELS
    with pytest.raises(ValueError):
        load_validation_config_bytes(data.replace(b"schema_version: 7", b"schema_version: 6"))
    with pytest.raises(ValueError, match="Unknown"):
        parse_failure_models({"max_gap_s": 1, "unloaded_current": {**asdict(MODEL), "extra": 1}})
    with pytest.raises(ValueError, match="Missing"):
        parse_failure_models({"max_gap_s": 1, "unloaded_current": {"unloaded_source": "unloaded"}})
    with pytest.raises(TypeError):
        FailureModelConfig(1, unloaded_current={})
    legacy = _analyze_battery_frame(_frame([0] * 3))
    assert legacy["schema_version"] == 8 and "failure_models" not in legacy
    previous = _check(
        _frame([0] * 3), FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.2, 2))
    )
    assert "unloaded_current" not in previous["failure_models"]["config"]


@pytest.mark.parametrize(
    "defect", ["duration", "magnitude", "state", "source", "limit", "required_duration", "code"]
)
def test_serialized_evidence_tampering_is_rejected(defect):
    result = copy.deepcopy(_check(_frame([-1] * 3)))
    event = _item(result)["events"][0]
    if defect == "duration":
        event["duration_s"] = 1
    elif defect == "magnitude":
        event["evidence"]["current_a"] = -2
    elif defect == "state":
        event["evidence"]["unloaded_status"] = 0
    elif defect == "source":
        event["signals"] = ["pack_current_a"]
    elif defect == "limit":
        event["limit_value"] = 0.25
    elif defect == "required_duration":
        event["evidence"]["required_duration_s"] = 1
    else:
        event["code"] = "CELL_IMBALANCE_SUSTAINED"
    with pytest.raises((ValueError, ValidationError)):
        SCHEMA.validate(result)
        validate_result_semantics(result)


@settings(max_examples=70, deadline=None)
@given(
    st.lists(
        st.tuples(st.booleans(), st.sampled_from([-2, -0.5, 0, 0.5, 2])), min_size=1, max_size=45
    )
)
def test_random_state_and_current_runs_against_independent_interval_reference(samples):
    states, currents = zip(*samples)
    result = _check(_frame(list(currents), state=list(states)))
    # Binary unit-second intervals: enumerate maximal high-current runs independently.
    active = [state and abs(current) > 0.5 for state, current in samples]
    changes = [i for i in range(len(active)) if i == 0 or active[i] != active[i - 1]] + [
        len(active)
    ]
    expected = [
        (start, end - 1) for start, end in pairwise(changes) if active[start] and end - start >= 3
    ]
    assert [(e["start_time_s"], e["end_time_s"]) for e in _item(result)["events"]] == expected
    state_edges = [i for i in range(len(states)) if i == 0 or states[i] != states[i - 1]] + [
        len(states)
    ]
    intervals = [(start, end) for start, end in pairwise(state_edges) if states[start]]
    eligible = sum(max(end - start - 2, 0) for start, end in intervals)
    incomplete = sum(end - start < 3 for start, end in intervals)
    item = _item(result)
    assert item["evaluated_samples"] == eligible
    assert item["incomplete_intervals"] == incomplete
    assert item["status"] == (
        "FAIL" if expected else "NOT_EVALUATED" if incomplete or not eligible else "PASS"
    )


@pytest.mark.parametrize("chunk_rows", [1, 100])
def test_csv_normalization_retains_two_statuses_and_identity_evidence(
    tmp_path, monkeypatch, chunk_rows
):
    from batterylog import normalization as module

    monkeypatch.setattr(module, "DEFAULT_CSV_CHUNK_ROWS", chunk_rows)
    frame = _frame([1000] * 4)
    frame["timestamp_s"] *= 1000
    frame[["cell_1_v", "cell_2_v"]] *= 1000
    frame["Bal"] = [False, False, False, False]
    models = replace(MODELS, balancing=BalancingConfig("Bal", 2, 0.01, 0.1, 4))
    source = tmp_path / "source.csv"
    frame.to_csv(source, index=False)
    output = tmp_path / "prepared"
    evidence = normalize_measurement(
        source,
        output,
        units=SourceUnits("ms", "mV", "degC", "mA"),
        config=ValidationConfig(failure_models=models),
    )
    normalized = pd.read_csv(output / "normalized.csv")
    assert normalized["unloaded"].tolist() == [1] * 4
    assert normalized["Bal"].tolist() == [0] * 4
    assert normalized["pack_current_a"].tolist() == [1] * 4
    for name in ("unloaded", "Bal"):
        assert next(c for c in evidence["conversions"] if c["canonical"] == name) == {
            "source": name,
            "canonical": name,
            "source_unit": "1",
            "target_unit": "1",
            "divisor": 1.0,
            "offset": 0.0,
        }
    assert (
        _item(
            AnalysisService(ValidationConfig(failure_models=models))
            .analyze_path(output / "normalized.csv")
            .result
        )["status"]
        == "FAIL"
    )


def test_normalization_rejects_invalid_state_without_final_output(tmp_path):
    source = tmp_path / "source.csv"
    _frame([0] * 3, state=[True, "bad", True]).to_csv(source, index=False)
    output = tmp_path / "prepared"
    with pytest.raises(ValueError, match="Unloaded status.*data row 2"):
        normalize_measurement(
            source,
            output,
            units=SourceUnits("s", "V", "degC", "A"),
            config=ValidationConfig(failure_models=MODELS),
        )
    assert not output.exists()


def test_cli_service_file_batch_and_html_share_current_evidence(tmp_path):
    data = ROOT / "examples/unloaded_current_demo.csv"
    config_path = ROOT / "examples/unloaded_current.example.yaml"
    config = load_validation_config_bytes(config_path.read_bytes())
    service = AnalysisService(config)
    result = service.analyze_path(data).result
    assert service.analyze_file(BytesIO(data.read_bytes())).result == result
    json_out, html_out = tmp_path / "result.json", tmp_path / "report.html"
    assert (
        run(
            [
                str(data),
                "--config",
                str(config_path),
                "--json-out",
                str(json_out),
                "--report",
                str(html_out),
            ]
        )
        == 1
    )
    assert json.loads(json_out.read_text()) == result
    assert "CURRENT_WHILE_UNLOADED" in html_out.read_text(encoding="utf-8")
    assert "current_a" in render_html_report(result)
    folder = tmp_path / "input"
    folder.mkdir()
    (folder / "one.csv").write_bytes(data.read_bytes())
    summary = analyze_directory(folder, tmp_path / "batch", service=service)
    assert summary["files"][0]["status"] == "FAIL"
