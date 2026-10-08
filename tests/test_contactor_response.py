"""Observed command edges and conservative sampled-response deadlines."""

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
    ContactorResponseConfig,
    DataQualityConfig,
    FailureModelConfig,
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
MODEL = ContactorResponseConfig("cmd", "feedback", 2)
MODELS = FailureModelConfig(1, contactor_response=MODEL)


def _frame(commands, feedback, times=None):
    count = len(commands)
    return pd.DataFrame(
        {
            "timestamp_s": list(range(count)) if times is None else times,
            "cell_1_v": [3.5] * count,
            "cell_2_v": [3.5] * count,
            "temp_c": [25.0] * count,
            "cmd": commands,
            "feedback": feedback,
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
        if e["code"] == "CONTACTOR_FEEDBACK_TIMEOUT"
    )


@pytest.mark.parametrize("closed", [0, 1])
def test_opening_and_closing_timeout_emit_once_with_observed_edge(closed):
    frame = _frame([1 - closed] + [closed] * 5, [1 - closed] * 6)
    item = _item(_check(frame))
    assert item["status"] == "FAIL" and item["evaluated_samples"] == 1
    assert item["incomplete_intervals"] == 0 and len(item["events"]) == 1
    event = item["events"][0]
    assert (
        event["start_time_s"],
        event["end_time_s"],
        event["peak_time_s"],
        event["duration_s"],
        event["measured_value"],
        event["sample_count"],
    ) == (1, 4, 4, 3, 3, 4)
    assert event["limit_value"] == 2 and event["unit"] == "s"
    assert event["signals"] == ["cmd", "feedback"]
    assert event["evidence"] == {
        "previous_command_time_s": 0,
        "previous_command_closed": 1 - closed,
        "command_time_s": 1,
        "command_closed": closed,
        "feedback_closed": 1 - closed,
        "required_response_s": 2,
    }


@pytest.mark.parametrize(
    "commands,feedback,status,evaluated,incomplete",
    [
        ([0, 1, 1, 1], [0, 1, 1, 1], "PASS", 1, 0),
        ([0, 1, 1, 1], [0, 0, 0, 1], "PASS", 1, 0),  # equality is allowed
        ([0, 1, 1, 1], [0, 0, 0, 0], "NOT_EVALUATED", 0, 1),  # EOF at deadline
        ([0, 1, 1, 1, 1], [0, 0, 0, 0, 1], "NOT_EVALUATED", 0, 1),  # first match late
        ([0, 0, 0], [0, 0, 0], "NOT_EVALUATED", 0, 0),  # no edges
        ([1, 1, 1, 1], [0, 0, 0, 0], "NOT_EVALUATED", 0, 1),  # left censored
        ([1, 1, 0], [0, 0, 0], "NOT_EVALUATED", 1, 1),  # later pass cannot erase unknown
        ([0, 1, 0], [0, 0, 0], "NOT_EVALUATED", 1, 1),  # command reversed while pending
        ([0, 1, 1, 0, 0], [0, 1, 1, 0, 0], "PASS", 2, 0),
        (
            [0, 1, 1, 1, 1, 1],
            [0, 1, 0, 0, 0, 0],
            "PASS",
            1,
            0,
        ),  # response check, not continuous supervision
    ],
)
def test_response_outcomes(commands, feedback, status, evaluated, incomplete):
    item = _item(_check(_frame(commands, feedback)))
    assert (item["status"], item["evaluated_samples"], item["incomplete_intervals"]) == (
        status,
        evaluated,
        incomplete,
    )
    assert item["events"] == []


def test_duplicate_timestamps_do_not_advance_deadline():
    item = _item(_check(_frame([0, 1, 1, 1, 1, 1], [0] * 6, [0, 0, 0, 1, 2, 3])))
    assert item["events"][0]["sample_count"] == 5
    assert item["events"][0]["duration_s"] == 3


@pytest.mark.parametrize("defect", ["gap", "measurement", "command", "feedback"])
def test_unknown_observations_prevent_pass_and_preserve_numeric_rows(defect):
    frame = _frame([0, 1, 1, 1, 0, 0], [0, 0, 0, 1, 0, 0])
    if defect == "gap":
        frame["timestamp_s"] = [0, 1, 4, 5, 6, 7]
    elif defect == "measurement":
        frame.loc[2, "temp_c"] = np.nan
    else:
        frame[("cmd" if defect == "command" else "feedback")] = frame[
            ("cmd" if defect == "command" else "feedback")
        ].astype(object)
        frame.loc[2, ("cmd" if defect == "command" else "feedback")] = "unknown"
    models = replace(MODELS, sustained_imbalance=SustainedImbalanceConfig(0.2, 1))
    result = _check(frame, models, data_quality=DataQualityConfig("exclude_invalid_rows"))
    item = _item(result)
    assert item["status"] == "NOT_EVALUATED" and item["incomplete_intervals"] == 1
    assert item["evaluated_samples"] == 1
    assert result["rows_excluded"] == (1 if defect == "measurement" else 0)
    assert result["failure_models"]["evaluations"][0]["status"] == "PASS"


@pytest.mark.parametrize("missing", ["cmd", "feedback", "both"])
def test_missing_channels_are_not_evaluated(missing):
    frame = _frame([0, 1, 1, 1, 1], [0] * 5).drop(
        columns=["cmd", "feedback"] if missing == "both" else [missing]
    )
    item = _item(_check(frame))
    assert item["status"] == "NOT_EVALUATED" and "Missing contactor" in item["reason"]
    assert not item["events"]


@pytest.mark.parametrize("source", ["cmd", "feedback"])
@pytest.mark.parametrize("bad", [2, -1, np.nan, "open", None])
def test_strict_status_errors_have_global_row_number(source, bad):
    frame = _frame([0, 1, 1, 1, 1], [0] * 5)
    frame[source] = frame[source].astype(object)
    frame.loc[2, source] = bad
    for size in (1, 2, 10):
        with pytest.raises(ValueError, match="Contactor .*status.*data row 3"):
            _analyze_battery_chunks(
                (frame.iloc[i : i + size] for i in range(0, len(frame), size)),
                failure_models=MODELS,
            )


def test_strict_earliest_defect_and_changed_presence():
    frame = _frame([0, 1, 1, 1, 1], [0] * 5)
    frame["feedback"] = frame["feedback"].astype(object)
    frame.loc[1, "feedback"] = "invalid"
    frame.loc[3, "temp_c"] = np.nan
    for size in (1, 2, 10):
        with pytest.raises(ValueError, match="Contactor feedback.*data row 2"):
            _analyze_battery_chunks(
                (frame.iloc[i : i + size] for i in range(0, 5, size)), failure_models=MODELS
            )
    frame = _frame([0, 1, 1, 1, 1], [0] * 5)
    with pytest.raises(ValueError, match="presence changed"):
        _analyze_battery_chunks(
            [frame.iloc[:1], frame.iloc[1:].drop(columns="cmd")], failure_models=MODELS
        )


@pytest.mark.parametrize(
    "change",
    [
        {"command_source": ""},
        {"feedback_source": "  "},
        {"command_source": False},
        {"feedback_source": 3},
        {"feedback_source": "cmd"},
        {"response_timeout_s": 0},
        {"response_timeout_s": -1},
        {"response_timeout_s": float("inf")},
        {"response_timeout_s": float("nan")},
        {"response_timeout_s": True},
    ],
)
def test_config_parameters_are_explicit_and_valid(change):
    with pytest.raises((ValueError, TypeError)):
        replace(MODEL, **change)


def test_yaml_and_legacy_contracts():
    data = (ROOT / "examples/contactor_response.example.yaml").read_bytes()
    assert load_validation_config_bytes(data).failure_models == MODELS
    assert parse_failure_models(asdict(MODELS)) == MODELS
    with pytest.raises(ValueError):
        load_validation_config_bytes(data.replace(b"schema_version: 7", b"schema_version: 6"))
    for raw in ({"extra": 1}, {"command_source": "cmd"}):
        with pytest.raises(ValueError):
            parse_failure_models({"max_gap_s": 1, "contactor_response": raw})
    with pytest.raises(TypeError):
        FailureModelConfig(1, contactor_response={})
    legacy = _analyze_battery_frame(_frame([0, 1], [0, 1]))
    assert legacy["schema_version"] == 8 and "failure_models" not in legacy
    prior = _check(
        _frame([0, 1, 1], [0, 1, 1]),
        FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.2, 1)),
    )
    assert "contactor_response" not in prior["failure_models"]["config"]


@pytest.mark.parametrize("source", ["timestamp_s", "cell_1_v", "temp_c"])
def test_state_channel_cannot_share_measurement_role(source):
    with pytest.raises(ValueError, match="measurement role"):
        _check(
            _frame([0, 1], [0, 1]),
            replace(MODELS, contactor_response=replace(MODEL, command_source=source)),
        )


@pytest.mark.parametrize(
    "defect", ["edge", "feedback", "time", "limit", "sources", "deadline", "code"]
)
def test_recorded_chain_rejects_tampering(defect):
    result = copy.deepcopy(_check(_frame([0, 1, 1, 1, 1], [0] * 5)))
    event = _item(result)["events"][0]
    if defect == "edge":
        event["evidence"]["previous_command_closed"] = 1
    elif defect == "feedback":
        event["evidence"]["feedback_closed"] = 1
    elif defect == "time":
        event["evidence"]["previous_command_time_s"] = -3
    elif defect == "limit":
        event["limit_value"] = 1
    elif defect == "sources":
        event["signals"] = ["cmd"]
    elif defect == "deadline":
        event["evidence"]["required_response_s"] = 1
    else:
        event["code"] = "BALANCING_ACTIVE_TOO_LONG"
    with pytest.raises((ValueError, ValidationError)):
        SCHEMA.validate(result)
        validate_result_semantics(result)


@settings(max_examples=70, deadline=None)
@given(st.lists(st.tuples(st.booleans(), st.booleans()), min_size=1, max_size=40))
def test_random_command_episodes_against_independent_reference(samples):
    commands, feedback = zip(*samples)
    item = _item(_check(_frame(commands, feedback)))
    edges = [i for i in range(1, len(samples)) if commands[i] != commands[i - 1]]
    failures = []
    evaluated = 0
    incomplete = int(commands[0] != feedback[0])
    for start, end in zip(edges, (edges + [len(samples)])[1:], strict=True):
        resolved = False
        for i in range(start, end):
            if feedback[i] == commands[start]:
                if i - start <= 2:
                    evaluated += 1
                else:
                    incomplete += 1
                resolved = True
                break
            if i - start > 2:
                failures.append((start, i))
                evaluated += 1
                resolved = True
                break
        if not resolved:
            incomplete += 1
    assert [(e["start_time_s"], e["end_time_s"]) for e in item["events"]] == failures
    assert item["evaluated_samples"] == evaluated and item["incomplete_intervals"] == incomplete
    assert item["status"] == (
        "FAIL" if failures else "NOT_EVALUATED" if incomplete or not evaluated else "PASS"
    )


@pytest.mark.parametrize("chunk_rows", [1, 100])
def test_normalization_preserves_named_statuses_with_identity_chain(
    tmp_path, monkeypatch, chunk_rows
):
    from batterylog import normalization as module

    monkeypatch.setattr(module, "DEFAULT_CSV_CHUNK_ROWS", chunk_rows)
    frame = _frame([0, 1, 1, 1, 1], [0] * 5).rename(
        columns={"timestamp_s": "clock", "cell_1_v": "U1", "cell_2_v": "U2", "temp_c": "T1"}
    )
    frame["clock"] *= 1000
    frame[["U1", "U2"]] *= 1000
    mapping = SignalMapping(
        "clock", SignalPattern(r"U(?P<index>\d+)"), SignalPattern(r"T(?P<index>\d+)")
    )
    source = tmp_path / "source.csv"
    frame.to_csv(source, index=False)
    destination = tmp_path / "prepared"
    evidence = normalize_measurement(
        source,
        destination,
        units=SourceUnits("ms", "mV", "degC"),
        config=ValidationConfig(signals=mapping, failure_models=MODELS),
    )
    normalized = pd.read_csv(destination / "normalized.csv")
    for name in ("cmd", "feedback"):
        assert normalized[name].tolist() == frame[name].tolist()
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
            str(ROOT / "examples/contactor_response_demo.csv"),
            "--config",
            str(ROOT / "examples/contactor_response.example.yaml"),
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
    assert "CONTACTOR_FEEDBACK_TIMEOUT" in html and "previous_command_closed" in html
