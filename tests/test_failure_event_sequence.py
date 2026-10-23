"""Reject impossible event sequences without rejecting equal timestamp boundaries."""

import copy
import json
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft202012Validator

from batterylog import FailureModelConfig, UnloadedCurrentConfig, validate_result_semantics
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import _analyze_battery_chunks
from batterylog.config import load_validation_config_bytes
from batterylog.desktop_job import _validate_published_result

ROOT = Path(__file__).parents[1]
SCHEMA = Draft202012Validator(json.loads((ROOT / "batterylog/schema/result-v9.json").read_text()))
CODES = (
    "CELL_IMBALANCE_SUSTAINED",
    "TEMPERATURE_RISE_HIGH",
    "CELL_SAG_UNDER_LOAD",
    "BALANCING_INEFFECTIVE",
    "BALANCING_ACTIVE_TOO_LONG",
    "CURRENT_WHILE_UNLOADED",
    "CONTACTOR_FEEDBACK_TIMEOUT",
    "PRECHARGE_CURRENT_DECAY_LOW",
)
EXAMPLES = {
    "CURRENT_WHILE_UNLOADED": "unloaded_current",
    "CONTACTOR_FEEDBACK_TIMEOUT": "contactor_response",
    "PRECHARGE_CURRENT_DECAY_LOW": "precharge_current",
}


def _two_episodes(code):
    name = EXAMPLES.get(code, "failure_models")
    config = load_validation_config_bytes((ROOT / f"examples/{name}.example.yaml").read_bytes())
    first = pd.read_csv(ROOT / f"examples/{name}_demo.csv")
    second = first.copy()
    second["timestamp_s"] += first["timestamp_s"].max() + 2 * config.failure_models.max_gap_s
    frame = pd.concat([first, second], ignore_index=True)
    kwargs = {
        "limits": config.limits,
        "event_detection": config.event_detection,
        "data_quality": config.data_quality,
        "signal_mapping": config.signals,
        "failure_models": config.failure_models,
    }
    result = _analyze_battery_frame(frame, **kwargs)
    item = next(e for e in result["failure_models"]["evaluations"] if e["code"] == code)
    assert len(item["events"]) == 2
    assert item["events"][0]["duration_s"] > 0
    return frame, kwargs, result, item


@pytest.mark.parametrize("code", CODES)
def test_produced_sequences_validate_and_match_chunks(code):
    frame, kwargs, result, _ = _two_episodes(code)
    for size in (1, 3, 19):
        chunks = (frame.iloc[i : i + size] for i in range(0, len(frame), size))
        assert _analyze_battery_chunks(chunks, **kwargs) == result
    SCHEMA.validate(result)
    validate_result_semantics(result)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("mutation", ["duplicate", "overlap", "reverse"])
def test_impossible_sequences_rejected_by_semantics_and_desktop(tmp_path, code, mutation):
    _, _, result, item = _two_episodes(code)
    if mutation == "reverse":
        item["events"].reverse()
    else:
        first = item["events"][0]
        second = copy.deepcopy(first)
        if mutation == "overlap":
            shift = first["duration_s"] / 2
            for field in ("start_time_s", "end_time_s", "peak_time_s"):
                second[field] += shift
            for field in second["evidence"]:
                if field.endswith("_time_s"):
                    second["evidence"][field] += shift
        item["events"] = [first, second]
    # Every individual event still has consistent arithmetic and supported counts.
    SCHEMA.validate(result)
    with pytest.raises(ValueError, match="event sequence"):
        validate_result_semantics(result)
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(OSError, match="event sequence"):
        _validate_published_result(path, 1)


@pytest.mark.parametrize("code", ["BALANCING_INEFFECTIVE", "BALANCING_ACTIVE_TOO_LONG"])
def test_balancing_evidence_time_is_the_checkpoint(tmp_path, code):
    _, _, result, item = _two_episodes(code)
    item["events"][0]["peak_time_s"] = item["events"][0]["start_time_s"]
    SCHEMA.validate(result)
    with pytest.raises(ValueError, match="balancing checkpoint"):
        validate_result_semantics(result)
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(OSError, match="balancing checkpoint"):
        _validate_published_result(path, 1)


def test_separate_events_may_share_an_observed_timestamp_boundary():
    frame = pd.DataFrame(
        {
            "timestamp_s": [0, 1, 2, 2, 2, 3, 4],
            "cell_1_v": [3.5] * 7,
            "temp_c": [25.0] * 7,
            "pack_current_a": [1, 1, 1, 0, 1, 1, 1],
            "unloaded": [1] * 7,
        }
    )
    models = FailureModelConfig(1, unloaded_current=UnloadedCurrentConfig("unloaded", 0.5, 2))
    result = _analyze_battery_frame(frame, failure_models=models)
    events = result["failure_models"]["evaluations"][0]["events"]
    assert len(events) == 2 and events[0]["end_time_s"] == events[1]["start_time_s"] == 2
    for size in (1, 3, 19):
        assert (
            _analyze_battery_chunks(
                (frame.iloc[i : i + size] for i in range(0, len(frame), size)),
                failure_models=models,
            )
            == result
        )
    SCHEMA.validate(result)
    validate_result_semantics(result)
