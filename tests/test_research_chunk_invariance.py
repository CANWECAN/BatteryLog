"""Adversarial chunk boundaries must preserve the complete result-v9 evidence."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from jsonschema import Draft202012Validator

from batterylog import (
    BalancingConfig,
    CellSagConfig,
    ContactorResponseConfig,
    DataQualityConfig,
    FailureModelConfig,
    PrechargeCurrentConfig,
    SustainedImbalanceConfig,
    TemperatureRiseConfig,
    UnloadedCurrentConfig,
    validate_result_semantics,
)
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import _analyze_battery_chunks

CONFIG = FailureModelConfig(
    max_gap_s=2,
    sustained_imbalance=SustainedImbalanceConfig(0.125, 2),
    temperature_rise=TemperatureRiseConfig(10, 0.1),
    cell_sag=CellSagConfig("discharge", 2, 20, 5, 1, 0.125),
    balancing=BalancingConfig("balance", 2, 0.03125, 0.125, 4),
    unloaded_current=UnloadedCurrentConfig("unloaded", 0.5, 2),
    contactor_response=ContactorResponseConfig("command", "feedback", 2),
    precharge_current=PrechargeCurrentConfig("precharge", 2, 4, 3),
)
SCHEMA = json.loads((Path(__file__).parents[1] / "batterylog/schema/result-v9.json").read_text())


def frame_for_boundary(count, boundary):
    """Seven active models with evidence spanning a chosen partition edge."""
    frame = pd.DataFrame(
        {
            "timestamp_s": np.arange(count, dtype=float),
            "cell_1_v": np.full(count, 3.5),
            "cell_2_v": np.full(count, 3.5),
            "cell_3_v": np.full(count, 3.5),
            "temp_c": np.full(count, 25.0),
            "pack_current_a": np.zeros(count),
            "balance": np.zeros(count, dtype=int),
            "unloaded": np.ones(count, dtype=int),
            "command": np.zeros(count, dtype=int),
            "feedback": np.zeros(count, dtype=int),
            "precharge": np.zeros(count, dtype=int),
        }
    )
    start = boundary - 2
    stop = boundary + 4
    frame.loc[start:stop, "cell_3_v"] = 3.25
    frame.loc[boundary:stop, "cell_3_v"] = 3.0
    frame.loc[start:stop, "balance"] = 1
    frame.loc[start:stop, "precharge"] = 1
    frame.loc[start:stop, "pack_current_a"] = 20
    frame.loc[start:, "command"] = 1
    frame.loc[boundary, "temp_c"] = 26.0
    return frame


def compare(frame, sizes, *, quality=None):
    kwargs = {"failure_models": CONFIG, "data_quality": quality}
    expected = _analyze_battery_frame(frame, **kwargs)
    Draft202012Validator(SCHEMA).validate(expected)
    validate_result_semantics(expected)
    for size in sizes:
        chunks = (frame.iloc[i : i + size] for i in range(0, len(frame), size))
        observed = _analyze_battery_chunks(chunks, **kwargs)
        # Equality includes status, source samples, times, peaks and all counters.
        assert observed == expected, f"result changed at chunk size {size}"
        validate_result_semantics(observed)
    return expected


@pytest.mark.parametrize("boundary", [6, 7, 8, 13, 14, 15])
@pytest.mark.parametrize("mode", ["clean", "duplicate", "gap", "invalid"])
def test_all_models_at_small_chunk_boundaries(boundary, mode):
    frame = frame_for_boundary(24, boundary)
    quality = None
    if mode == "duplicate":
        frame.loc[boundary, "timestamp_s"] = frame.loc[boundary - 1, "timestamp_s"]
    elif mode == "gap":
        frame.loc[boundary:, "timestamp_s"] += 3
    elif mode == "invalid":
        frame.loc[boundary, "temp_c"] = np.nan
        quality = DataQualityConfig("exclude_invalid_rows")
    result = compare(frame, (1, 7, 1024, 65536), quality=quality)
    assert result["rows_input"] == 24
    assert {item["code"] for item in result["failure_models"]["evaluations"]} == {
        "CELL_IMBALANCE_SUSTAINED",
        "TEMPERATURE_RISE_HIGH",
        "CELL_SAG_UNDER_LOAD",
        "BALANCING_INEFFECTIVE",
        "BALANCING_ACTIVE_TOO_LONG",
        "CURRENT_WHILE_UNLOADED",
        "CONTACTOR_FEEDBACK_TIMEOUT",
        "PRECHARGE_CURRENT_DECAY_LOW",
    }
    assert result["validation_status"] == "FAIL"
    if mode == "invalid":
        assert result["rows_excluded"] == 1


def test_real_65536_row_partition_crosses_active_events():
    frame = frame_for_boundary(65542, 65536)
    result = compare(frame, (1024, 65536))
    assert result["rows_input"] == 65542
    by_code = {
        evaluation["code"]: evaluation for evaluation in result["failure_models"]["evaluations"]
    }
    assert by_code["CELL_IMBALANCE_SUSTAINED"]["status"] == "FAIL"
    assert by_code["CELL_IMBALANCE_SUSTAINED"]["events"][0]["peak_time_s"] == 65536
