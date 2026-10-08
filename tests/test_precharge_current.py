"""Independent sampled current-drop expectations for declared precharge episodes."""

import copy
import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator, ValidationError

from batterylog import (
    AnalysisService,
    DataQualityConfig,
    FailureModelConfig,
    PrechargeCurrentConfig,
    SignalMapping,
    SignalPattern,
    SourceUnits,
    SustainedImbalanceConfig,
    ValidationConfig,
    normalize_measurement,
    validate_result_semantics,
)
from batterylog.__main__ import run
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import _analyze_battery_chunks
from batterylog.config import load_validation_config_bytes
from batterylog.failure_config import parse_failure_models

ROOT = Path(__file__).parents[1]
SCHEMA = Draft202012Validator(json.loads((ROOT / "batterylog/schema/result-v9.json").read_text()))
MODEL = PrechargeCurrentConfig("precharge", 2, 4, 3)
MODELS = FailureModelConfig(1, precharge_current=MODEL)


def _frame(currents, *, state=None, times=None):
    count = len(currents)
    return pd.DataFrame(
        {
            "timestamp_s": list(range(count)) if times is None else times,
            "cell_1_v": [3.5] * count,
            "cell_2_v": [3.5] * count,
            "temp_c": [25.0] * count,
            "pack_current_a": currents,
            "precharge": [False] + [True] * (count - 1) if state is None else state,
        }
    )


def _check(frame, models=MODELS, **kwargs):
    result = _analyze_battery_frame(frame, failure_models=models, **kwargs)
    for size in (1, 2, 3, 19):
        chunks = (frame.iloc[i : i + size] for i in range(0, len(frame), size))
        assert _analyze_battery_chunks(chunks, failure_models=models, **kwargs) == result
    SCHEMA.validate(json.loads(json.dumps(result, allow_nan=False)))
    validate_result_semantics(result)
    return result


def _item(result):
    return next(
        e
        for e in result["failure_models"]["evaluations"]
        if e["code"] == "PRECHARGE_CURRENT_DECAY_LOW"
    )


@pytest.mark.parametrize("sign", [1, -1])
def test_first_checkpoint_preserves_signed_reference_and_detection_sample(sign):
    item = _item(_check(_frame([sign * i for i in [0, 6, 5, 4.5, 1, 0]], state=[0, 1, 1, 1, 1, 0])))
    assert (
        item["status"] == "FAIL"
        and item["evaluated_samples"] == 1
        and not item["incomplete_intervals"]
    )
    assert len(item["events"]) == 1
    event = item["events"][0]
    assert (
        event["start_time_s"],
        event["end_time_s"],
        event["peak_time_s"],
        event["duration_s"],
        event["sample_count"],
    ) == (1, 3, 3, 2, 3)
    assert event["measured_value"] == 1.5 and event["limit_value"] == 3 and event["unit"] == "A"
    assert event["signals"] == ["pack_current_a", "precharge"]
    assert event["evidence"] == {
        "previous_time_s": 0,
        "previous_precharge_active": 0,
        "precharge_active": 1,
        "initial_current_a": sign * 6,
        "current_a": sign * 4.5,
        "current_drop_a": 1.5,
        "required_evaluation_s": 2,
    }


@pytest.mark.parametrize(
    "currents,states,status,evaluated,incomplete",
    [
        ([0, 6, 4, 3], [0, 1, 1, 1], "PASS", 1, 0),
        ([0, 4, 3, 1], [0, 1, 1, 1], "PASS", 1, 0),  # equality at both bounds
        ([0, 6, 6, 8], [0, 1, 1, 1], "FAIL", 1, 0),  # rising magnitude gives negative drop
        ([0, 6, 4, 0], [0, 1, 1, 0], "NOT_EVALUATED", 0, 1),  # inactive current cannot prove decay
        ([0, 6, 4], [0, 1, 1], "NOT_EVALUATED", 0, 1),  # EOF before checkpoint
        ([6, 5, 1], [1, 1, 1], "NOT_EVALUATED", 0, 1),  # no edge
        ([0, 0, 0], [0, 0, 0], "NOT_EVALUATED", 0, 0),
        (
            [0, 1, 6, 1],
            [0, 1, 1, 1],
            "NOT_EVALUATED",
            0,
            1,
        ),  # low initial reference is never replaced
        ([6, 5, 0, 6, 4, 3], [1, 1, 0, 1, 1, 1], "NOT_EVALUATED", 1, 1),
        ([0, 6, 4, 3, 0, 6, 4, 3], [0, 1, 1, 1, 0, 1, 1, 1], "PASS", 2, 0),
        ([0, 6, 4, 3, 0, 1, 1, 0], [0, 1, 1, 1, 0, 1, 1, 0], "NOT_EVALUATED", 1, 1),
        ([0, -6, -4, 3], [0, 1, 1, 1], "PASS", 1, 0),  # magnitude observation, not sign diagnosis
    ],
)
def test_episode_eligibility_and_outcomes(currents, states, status, evaluated, incomplete):
    item = _item(_check(_frame(currents, state=states)))
    assert (item["status"], item["evaluated_samples"], item["incomplete_intervals"]) == (
        status,
        evaluated,
        incomplete,
    )


@pytest.mark.parametrize("missing", ["precharge", "pack_current_a", "both"])
def test_missing_phase_or_current_is_not_evaluated(missing):
    frame = _frame([0, 6, 5, 4.5]).drop(
        columns=["precharge", "pack_current_a"] if missing == "both" else [missing]
    )
    item = _item(_check(frame))
    assert item["status"] == "NOT_EVALUATED" and item["reason"].startswith("Missing")
    assert not item["events"]


@pytest.mark.parametrize("defect", ["gap", "measurement", "state"])
def test_interrupted_phase_cannot_become_pass_after_later_eligible_episode(defect):
    frame = _frame([0, 6, 5, 4.5, 0, 6, 4, 3], state=[0, 1, 1, 1, 0, 1, 1, 1])
    if defect == "gap":
        frame["timestamp_s"] = [0, 1, 4, 5, 6, 7, 8, 9]
    elif defect == "measurement":
        frame.loc[2, "pack_current_a"] = np.nan
    else:
        frame["precharge"] = frame["precharge"].astype(object)
        frame.loc[2, "precharge"] = "unknown"
    models = replace(MODELS, sustained_imbalance=SustainedImbalanceConfig(0.2, 1))
    result = _check(frame, models, data_quality=DataQualityConfig("exclude_invalid_rows"))
    item = _item(result)
    assert (
        item["status"] == "NOT_EVALUATED"
        and item["evaluated_samples"] == 1
        and item["incomplete_intervals"] == 1
    )
    assert result["rows_excluded"] == (1 if defect == "measurement" else 0)
    assert result["failure_models"]["evaluations"][0]["status"] == "PASS"


def test_adjacent_unknown_state_counts_once_and_retains_completed_failures():
    frame = _frame([0, 6, 5, 4.5, 0, 6, 4, 3], state=[0, 1, 1, 1, 0, 1, 1, 1])
    frame["precharge"] = frame["precharge"].astype(object)
    frame.loc[4:6, "precharge"] = "unknown"
    item = _item(_check(frame, data_quality=DataQualityConfig("exclude_invalid_rows")))
    assert (
        item["status"] == "FAIL" and item["incomplete_intervals"] == 1 and len(item["events"]) == 1
    )


@pytest.mark.parametrize("bad", [2, -1, "active", None, np.nan])
def test_strict_status_error_uses_first_global_data_row(bad):
    frame = _frame([0, 6, 5, 4.5, 1])
    frame["precharge"] = frame["precharge"].astype(object)
    frame.loc[2, "precharge"] = bad
    frame.loc[4, "temp_c"] = np.nan
    for size in (1, 2, 10):
        with pytest.raises(ValueError, match="Precharge status.*data row 3"):
            _analyze_battery_chunks(
                (frame.iloc[i : i + size] for i in range(0, 5, size)), failure_models=MODELS
            )


def test_phase_presence_and_source_role_are_checked():
    frame = _frame([0, 6, 4, 3])
    with pytest.raises(ValueError, match="presence changed"):
        _analyze_battery_chunks(
            [frame.iloc[:2], frame.iloc[2:].drop(columns="precharge")], failure_models=MODELS
        )
    for source in ("pack_current_a", "timestamp_s", "cell_1_v"):
        with pytest.raises(ValueError, match="measurement role"):
            _check(frame, replace(MODELS, precharge_current=replace(MODEL, active_source=source)))
    duplicate = pd.concat([frame, frame[["precharge"]]], axis=1)
    with pytest.raises(ValueError, match="Duplicate precharge"):
        _check(duplicate)


def test_duplicate_times_and_binary64_boundaries():
    frame = _frame([0, 6, 5, 4.5, 3, 1], times=[0, 1, 1, 2, 3, 4])
    item = _item(_check(frame))
    assert item["status"] == "PASS" and item["evaluated_samples"] == 1
    # Binary64 guard admits an arithmetically close checkpoint and current reduction.
    frame = _frame([0, 6, 4, 3 + np.spacing(3.0)], times=[0, 1, 2, 3 - np.spacing(3.0)])
    item = _item(_check(frame))
    assert item["status"] == "PASS" and item["evaluated_samples"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"active_source": ""},
        {"active_source": "  "},
        {"active_source": False},
        {"evaluation_s": 0},
        {"evaluation_s": -1},
        {"evaluation_s": float("inf")},
        {"evaluation_s": True},
        {"min_start_abs_current_a": 0},
        {"min_start_abs_current_a": float("nan")},
        {"min_start_abs_current_a": False},
        {"min_drop_a": 0},
        {"min_drop_a": -1},
        {"min_drop_a": 5},
        {"min_drop_a": "3"},
    ],
)
def test_invalid_config_is_rejected(change):
    with pytest.raises((TypeError, ValueError)):
        replace(MODEL, **change)


def test_explicit_yaml_and_previous_payloads():
    data = (ROOT / "examples/precharge_current.example.yaml").read_bytes()
    assert load_validation_config_bytes(data).failure_models == MODELS
    assert parse_failure_models(asdict(MODELS)) == MODELS
    with pytest.raises(ValueError):
        load_validation_config_bytes(data.replace(b"schema_version: 7", b"schema_version: 6"))
    with pytest.raises(ValueError):
        parse_failure_models({"max_gap_s": 1, "precharge_current": {"active_source": "precharge"}})
    with pytest.raises(ValueError):
        parse_failure_models({"max_gap_s": 1, "precharge_current": {**asdict(MODEL), "extra": 1}})
    with pytest.raises(TypeError):
        FailureModelConfig(1, precharge_current={})
    legacy = _analyze_battery_frame(_frame([0, 6, 4, 3]))
    assert legacy["schema_version"] == 8 and "failure_models" not in legacy
    previous = _check(
        _frame([0, 6, 4, 3]),
        FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.2, 1)),
    )
    assert "precharge_current" not in previous["failure_models"]["config"]


@pytest.mark.parametrize(
    "defect",
    ["initial", "current", "drop", "time", "duration", "limit", "source", "state", "checkpoint"],
)
def test_measurement_chain_tampering_is_rejected(defect):
    result = copy.deepcopy(_check(_frame([0, 6, 5, 4.5])))
    event = _item(result)["events"][0]
    if defect == "initial":
        event["evidence"]["initial_current_a"] = 2
    elif defect == "current":
        event["evidence"]["current_a"] = 2
    elif defect == "drop":
        event["evidence"]["current_drop_a"] = 0.5
    elif defect == "time":
        event["evidence"]["previous_time_s"] = -3
    elif defect == "duration":
        event["duration_s"] = 1
    elif defect == "limit":
        event["limit_value"] = 2
    elif defect == "source":
        event["signals"] = ["pack_current_a"]
    elif defect == "state":
        event["evidence"]["previous_precharge_active"] = 1
    else:
        event["evidence"]["required_evaluation_s"] = 1
    with pytest.raises((ValueError, ValidationError)):
        SCHEMA.validate(result)
        validate_result_semantics(result)


@settings(max_examples=70, deadline=None)
@given(
    st.lists(
        st.tuples(st.booleans(), st.sampled_from([-8, -6, -4, -1, 0, 1, 4, 6, 8])),
        min_size=1,
        max_size=45,
    )
)
def test_random_active_episodes_against_independent_reference(samples):
    states, currents = zip(*samples)
    item = _item(_check(_frame(currents, state=states)))
    starts = [i for i in range(1, len(states)) if states[i] and not states[i - 1]]
    failures = []
    evaluated = 0
    incomplete = int(states[0])
    for start in starts:
        end = next((i for i in range(start + 1, len(states)) if not states[i]), len(states))
        if abs(currents[start]) < 4 or end - start < 3:
            incomplete += 1
            continue
        evaluated += 1
        checkpoint = start + 2
        if abs(currents[start]) - abs(currents[checkpoint]) < 3:
            failures.append((start, checkpoint))
    assert [(e["start_time_s"], e["end_time_s"]) for e in item["events"]] == failures
    assert item["evaluated_samples"] == evaluated and item["incomplete_intervals"] == incomplete
    assert item["status"] == (
        "FAIL" if failures else "NOT_EVALUATED" if incomplete or not evaluated else "PASS"
    )


@pytest.mark.parametrize("chunk_rows", [1, 100])
def test_csv_normalization_preserves_phase_and_signed_current(tmp_path, monkeypatch, chunk_rows):
    from batterylog import normalization as module

    monkeypatch.setattr(module, "DEFAULT_CSV_CHUNK_ROWS", chunk_rows)
    frame = _frame([0, -6, -5, -4.5]).rename(
        columns={
            "timestamp_s": "clock",
            "cell_1_v": "U1",
            "cell_2_v": "U2",
            "temp_c": "T1",
            "pack_current_a": "I",
        }
    )
    frame["clock"] *= 1000
    frame[["U1", "U2"]] *= 1000
    frame["I"] *= 1000
    mapping = SignalMapping(
        "clock",
        SignalPattern(r"U(?P<index>\d+)"),
        SignalPattern(r"T(?P<index>\d+)"),
        pack_current="I",
    )
    source = tmp_path / "source.csv"
    frame.to_csv(source, index=False)
    destination = tmp_path / "prepared"
    evidence = normalize_measurement(
        source,
        destination,
        units=SourceUnits("ms", "mV", "degC", "mA"),
        config=ValidationConfig(signals=mapping, failure_models=MODELS),
    )
    normalized = pd.read_csv(destination / "normalized.csv")
    assert normalized["precharge"].tolist() == [0, 1, 1, 1] and normalized[
        "pack_current_a"
    ].tolist() == [0, -6, -5, -4.5]
    assert next(c for c in evidence["conversions"] if c["canonical"] == "precharge") == {
        "source": "precharge",
        "canonical": "precharge",
        "source_unit": "1",
        "target_unit": "1",
        "divisor": 1.0,
        "offset": 0.0,
    }
    assert (
        _item(
            AnalysisService(ValidationConfig(failure_models=MODELS))
            .analyze_path(destination / "normalized.csv")
            .result
        )["status"]
        == "FAIL"
    )


def test_example_cli_json_and_html(tmp_path):
    output = tmp_path / "result.json"
    report = tmp_path / "report.html"
    code = run(
        [
            str(ROOT / "examples/precharge_current_demo.csv"),
            "--config",
            str(ROOT / "examples/precharge_current.example.yaml"),
            "--json-out",
            str(output),
            "--report",
            str(report),
        ]
    )
    assert code == 1
    result = json.loads(output.read_text())
    SCHEMA.validate(result)
    validate_result_semantics(result)
    assert _item(result)["status"] == "FAIL" and len(_item(result)["events"]) == 1
    html = report.read_text(encoding="utf-8")
    assert "PRECHARGE_CURRENT_DECAY_LOW" in html and "initial_current_a" in html
