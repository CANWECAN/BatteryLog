"""Deterministic independent episode expectations plus chunk/schema/consumer checks."""

import json
import random
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator

from batterylog import (
    BalancingConfig,
    ContactorResponseConfig,
    DataQualityConfig,
    FailureModelConfig,
    PrechargeCurrentConfig,
    UnloadedCurrentConfig,
    validate_result_semantics,
)
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import _analyze_battery_chunks

rng = random.Random(81026)
models = FailureModelConfig(
    1,
    balancing=BalancingConfig("phase", 2, 0.1, 0.2, 2),
    contactor_response=ContactorResponseConfig("cmd", "feedback", 2),
    precharge_current=PrechargeCurrentConfig("phase", 2, 4, 3),
    unloaded_current=UnloadedCurrentConfig("unloaded", 0.5, 2),
)
schema = Draft202012Validator(json.loads(Path("batterylog/schema/result-v9.json").read_text()))
analyses = 0
independent = 0
for case in range(1000):
    n = rng.randint(2, 45)
    times = [0.0]
    for i in range(1, n):
        times.append(
            times[-1] + rng.choice([0.0, 0.125, 0.5, 1.0])
            if case < 500
            else times[-1] + rng.choice([0.0, 0.5, 1.0, 2.0])
        )
    phase = [rng.randrange(2) for _ in times]
    currents = [rng.choice([-8.0, -6.0, -4.0, -1.0, 0.0, 1.0, 4.0, 6.0, 8.0]) for _ in times]
    frame = pd.DataFrame(
        {
            "timestamp_s": times,
            "cell_1_v": [3.5] * n,
            "cell_2_v": [3.25] * n,
            "temp_c": [25.0] * n,
            "pack_current_a": currents,
            "phase": phase,
            "cmd": [rng.randrange(2) for _ in times],
            "feedback": [rng.randrange(2) for _ in times],
            "unloaded": [rng.randrange(2) for _ in times],
        }
    )
    if case >= 500:
        for col in ("phase", "cmd", "feedback", "unloaded"):
            if rng.random() < 0.7:
                frame.loc[rng.randrange(n), col] = 2
        if rng.random() < 0.5:
            frame.loc[rng.randrange(1, n), "temp_c"] = float("nan")
    kwargs = {"failure_models": models, "data_quality": DataQualityConfig("exclude_invalid_rows")}
    result = _analyze_battery_frame(frame, **kwargs)
    for size in (1, 7, 19):
        other = _analyze_battery_chunks(
            [frame.iloc[i : i + size] for i in range(0, n, size)], **kwargs
        )
        assert other == result, (case, size)
        analyses += 1
    schema.validate(result)
    validate_result_semantics(result)
    analyses += 1
    if case < 500:
        expected = []
        eligible = 0
        incomplete = int(phase[0] == 1)
        for start in range(1, n):
            if phase[start] != 1 or phase[start - 1] != 0:
                continue
            stop = next((i for i in range(start + 1, n) if phase[i] == 0), n)
            # This oracle locates the earliest checkpoint directly on the episode.
            checkpoint = next((i for i in range(start, stop) if times[i] - times[start] >= 2), None)
            if abs(currents[start]) < 4 or checkpoint is None:
                incomplete += 1
                continue
            eligible += 1
            if abs(currents[start]) - abs(currents[checkpoint]) < 3:
                expected.append((times[start], times[checkpoint], checkpoint - start + 1))
        item = next(
            e
            for e in result["failure_models"]["evaluations"]
            if e["code"] == "PRECHARGE_CURRENT_DECAY_LOW"
        )
        actual = [(e["start_time_s"], e["end_time_s"], e["sample_count"]) for e in item["events"]]
        assert actual == expected, (case, actual, expected)
        assert item["evaluated_samples"] == eligible, (case, item, eligible)
        assert item["incomplete_intervals"] == incomplete, (case, item, incomplete)
        assert item["status"] == (
            "FAIL" if expected else "NOT_EVALUATED" if incomplete or not eligible else "PASS"
        )
        independent += 1
print(
    json.dumps(
        {
            "scenarios": 1000,
            "analyses": analyses,
            "independent_precharge_scenarios": independent,
            "seed": 81026,
        }
    )
)
