"""Reject structurally valid results whose observation counts cannot support their events."""

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from jsonschema import Draft202012Validator

from batterylog import (
    AnalysisService,
    FailureModelConfig,
    UnloadedCurrentConfig,
    validate_result_semantics,
)
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import _analyze_battery_chunks
from batterylog.config import load_validation_config_bytes
from batterylog.desktop_job import _validate_published_result

ROOT = Path(__file__).parents[1]
SCHEMA = Draft202012Validator(json.loads((ROOT / "batterylog/schema/result-v9.json").read_text()))
CODES = [
    "CELL_IMBALANCE_SUSTAINED",
    "TEMPERATURE_RISE_HIGH",
    "CELL_SAG_UNDER_LOAD",
    "BALANCING_INEFFECTIVE",
    "BALANCING_ACTIVE_TOO_LONG",
    "CURRENT_WHILE_UNLOADED",
]


def _example(code):
    name = "unloaded_current" if code == "CURRENT_WHILE_UNLOADED" else "failure_models"
    config = load_validation_config_bytes((ROOT / f"examples/{name}.example.yaml").read_bytes())
    result = AnalysisService(config).analyze_path(ROOT / f"examples/{name}_demo.csv").result
    evaluation = next(e for e in result["failure_models"]["evaluations"] if e["code"] == code)
    return result, evaluation


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize(
    "mutation",
    [
        "single_sample_duration",
        "too_few_samples_for_gap",
        "excess_event_samples",
        "events_without_evaluations",
        "excess_evaluated_samples",
    ],
)
def test_impossible_observation_counts_rejected_by_semantics_and_desktop(tmp_path, code, mutation):
    result, evaluation = _example(code)
    event = evaluation["events"][0]
    assert event["duration_s"] > result["failure_models"]["config"]["max_gap_s"]
    if mutation == "single_sample_duration":
        event["sample_count"] = 1
    elif mutation == "too_few_samples_for_gap":
        event["sample_count"] = 2
    elif mutation == "excess_event_samples":
        event["sample_count"] = result["rows_analyzed"] + 1
    elif mutation == "events_without_evaluations":
        evaluation["evaluated_samples"] = 0
    else:
        evaluation["evaluated_samples"] = result["rows_analyzed"] + 1
    # These payloads satisfy the JSON shape contract; their cross-field evidence is impossible.
    SCHEMA.validate(result)
    with pytest.raises(ValueError, match="Failure-model evidence"):
        validate_result_semantics(result)
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(OSError, match="invalid result payload"):
        _validate_published_result(path, 1)


@pytest.mark.parametrize("code", CODES)
def test_events_cannot_reuse_more_source_rows_than_were_analyzed(code):
    result, evaluation = _example(code)
    event = evaluation["events"][0]
    # Preserve len(events) <= evaluated_samples so only source-row accounting rejects this.
    evaluation["events"] = [copy.deepcopy(event), copy.deepcopy(event)]
    evaluation["evaluated_samples"] = 2
    event_rows = 2 * event["sample_count"]
    result["rows_analyzed"] = event_rows - 1
    result["rows_input"] = result["rows_analyzed"] + result["rows_excluded"]
    SCHEMA.validate(result)
    with pytest.raises(ValueError, match="Failure-model evidence"):
        validate_result_semantics(result)


@pytest.mark.parametrize("times", [[0, 1, 2], [0, 1, 1, 2], [0, np.nextafter(1.0, np.inf), 2]])
def test_valid_gap_boundaries_and_duplicate_timestamps_are_preserved(times):
    frame = pd.DataFrame(
        {
            "timestamp_s": times,
            "cell_1_v": [3.5] * len(times),
            "cell_2_v": [3.5] * len(times),
            "temp_c": [25.0] * len(times),
            "pack_current_a": [1.0] * len(times),
            "unloaded": [True] * len(times),
        }
    )
    models = FailureModelConfig(1, unloaded_current=UnloadedCurrentConfig("unloaded", 0.5, 2))
    result = _analyze_battery_frame(frame, failure_models=models)
    event = result["failure_models"]["evaluations"][0]["events"][0]
    assert event["sample_count"] == len(times)
    assert event["duration_s"] == 2
    for size in (1, 2, 3):
        chunks = (frame.iloc[i : i + size] for i in range(0, len(frame), size))
        assert _analyze_battery_chunks(chunks, failure_models=models) == result
    SCHEMA.validate(result)
    validate_result_semantics(result)
