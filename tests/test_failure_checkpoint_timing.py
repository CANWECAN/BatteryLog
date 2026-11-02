"""First observations must be reachable without skipping an eligible checkpoint."""

import copy
import json
import math
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft202012Validator

from batterylog import (
    BalancingConfig,
    ContactorResponseConfig,
    FailureModelConfig,
    PrechargeCurrentConfig,
    validate_result_semantics,
)
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import _analyze_battery_chunks
from batterylog.desktop_job import _validate_published_result

SCHEMA = Draft202012Validator(
    json.loads((Path(__file__).parents[1] / "batterylog/schema/result-v9.json").read_text())
)
CODES = (
    "BALANCING_INEFFECTIVE",
    "BALANCING_ACTIVE_TOO_LONG",
    "CONTACTOR_FEEDBACK_TIMEOUT",
    "PRECHARGE_CURRENT_DECAY_LOW",
)
MODELS = FailureModelConfig(
    1,
    balancing=BalancingConfig("phase", 2, 0.1, 0.2, 2),
    contactor_response=ContactorResponseConfig("phase", "feedback", 2),
    precharge_current=PrechargeCurrentConfig("phase", 2, 4, 3),
)


def _frame(times):
    count = len(times)
    return pd.DataFrame(
        {
            "timestamp_s": times,
            "cell_1_v": [3.5] * count,
            "cell_2_v": [3.25] * count,
            "temp_c": [25.0] * count,
            "pack_current_a": [0] + [6] * (count - 1),
            "phase": [0] + [1] * (count - 1),
            "feedback": [0] * count,
        }
    )


@pytest.mark.parametrize("code", CODES)
def test_delayed_first_checkpoint_is_rejected_by_semantics_and_desktop(tmp_path, code):
    result = copy.deepcopy(_analyze_battery_frame(_frame(list(range(12))), failure_models=MODELS))
    event = next(e for e in result["failure_models"]["evaluations"] if e["code"] == code)["events"][
        0
    ]
    event.update(end_time_s=8, peak_time_s=8, duration_s=7, sample_count=8)
    if code in ("BALANCING_ACTIVE_TOO_LONG", "CONTACTOR_FEEDBACK_TIMEOUT"):
        event.update(measured_value=7, peak_excursion=5)
    if code.startswith("BALANCING"):
        event["evidence"]["active_duration_s"] = 7
    SCHEMA.validate(result)
    with pytest.raises(ValueError, match="first checkpoint"):
        validate_result_semantics(result)
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(OSError, match="first checkpoint"):
        _validate_published_result(path, 1)


def test_first_timeout_bound_preserves_composed_binary64_guards():
    # Both the last pre-deadline observation and the last gap are guard-close.
    # Comparing only against deadline + gap would reject this producer result.
    deadline, gap = 16.1457415354046, 3.226120166196443
    previous, end = 16.14574153540463, 19.371861701601077
    intervals = math.ceil(previous / gap)
    times = [0.0, 0.0] + [previous * i / intervals for i in range(1, intervals + 1)] + [end]
    models = FailureModelConfig(
        gap,
        balancing=BalancingConfig("phase", deadline, 0.1, 0.2, deadline),
        contactor_response=ContactorResponseConfig("phase", "feedback", deadline),
        precharge_current=PrechargeCurrentConfig("phase", deadline, 4, 3),
    )
    frame = _frame(times)
    result = _analyze_battery_frame(frame, failure_models=models)
    for size in (1, 3, 19):
        assert (
            _analyze_battery_chunks(
                [frame.iloc[i : i + size] for i in range(0, len(frame), size)],
                failure_models=models,
            )
            == result
        )
    SCHEMA.validate(result)
    validate_result_semantics(result)
    events = {e["code"]: e["events"][0] for e in result["failure_models"]["evaluations"]}
    assert events["CONTACTOR_FEEDBACK_TIMEOUT"]["end_time_s"] == end
    assert events["BALANCING_ACTIVE_TOO_LONG"]["end_time_s"] == end
    assert events["PRECHARGE_CURRENT_DECAY_LOW"]["end_time_s"] == previous
    assert events["BALANCING_INEFFECTIVE"]["end_time_s"] == previous


@pytest.mark.parametrize("required", [10**308, 1e308])
def test_finite_configuration_with_overflowing_bound_sum_remains_valid(required):
    models = FailureModelConfig(
        required,
        balancing=BalancingConfig("phase", required, 0.1, 0.2, required),
        contactor_response=ContactorResponseConfig("phase", "feedback", required),
        precharge_current=PrechargeCurrentConfig("phase", required, 4, 3),
    )
    result = _analyze_battery_frame(
        _frame([-5e307, 0.0, 5e307, 1e308, 1.1e308]), failure_models=models
    )
    SCHEMA.validate(result)
    validate_result_semantics(result)
    assert all(e["status"] == "FAIL" for e in result["failure_models"]["evaluations"])
