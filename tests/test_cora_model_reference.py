"""Numeric anchors for the external campaign's independent references."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from batterylog import (
    CellSagConfig,
    FailureModelConfig,
    SustainedImbalanceConfig,
    TemperatureRiseConfig,
)
from scripts.validation.validate_cora_failure_models import compare_models, reference_models


def frame(times=range(6), *, current=None):
    times = list(times)
    data = {"timestamp_s": times}
    data.update({f"cell_{i}_v": [3.5] * len(times) for i in range(1, 13)})
    data.update({f"temp_{i}_c": [25.0] * len(times) for i in range(1, 25)})
    data["pack_current_a"] = current if current is not None else [0.0] * len(times)
    data["pack_voltage_v"] = [42.0] * len(times)
    return pd.DataFrame(data)


def config():
    return FailureModelConfig(
        1,
        sustained_imbalance=SustainedImbalanceConfig(0.25, 2),
        temperature_rise=TemperatureRiseConfig(60, 0.5),
        cell_sag=CellSagConfig("charge", 0, 2, 5, 1, 0.25),
    )


def test_reference_has_independently_known_span_rate_and_sag_chains():
    source = frame(current=[0, -3, -3, -3, 0, 0])
    for i in range(1, 13):
        source.loc[1:3, f"cell_{i}_v"] = 3.375
    source.loc[1:3, "cell_2_v"] = 3.0
    source["temp_4_c"] = [25, 26, 28, 28, 28, 28]
    result = reference_models(source, config())
    imbalance = result["CELL_IMBALANCE_SUSTAINED"]
    assert imbalance["evaluated_samples"] == 4
    assert imbalance["events"][0] == {
        "start_time_s": 1.0,
        "end_time_s": 3.0,
        "peak_time_s": 1.0,
        "measured_value": 0.375,
        "sample_count": 3,
        "evidence": {"cell_min_v": 3.0, "cell_max_v": 3.375, "required_duration_s": 2},
    }
    temperature = result["TEMPERATURE_RISE_HIGH"]
    assert temperature["evaluated_samples"] == 5
    assert len(temperature["events"]) == 1
    assert temperature["events"][0]["peak_time_s"] == 2
    assert temperature["events"][0]["measured_value"] == 120
    assert temperature["events"][0]["evidence"]["previous_temperature_c"] == 26
    sag = result["CELL_SAG_UNDER_LOAD"]
    assert sag["evaluated_samples"] == 2
    assert sag["incomplete_intervals"] == 0
    assert sag["events"][0]["start_time_s"] == 2
    assert sag["events"][0]["end_time_s"] == 3
    assert sag["events"][0]["measured_value"] == 0.375
    assert sag["events"][0]["evidence"] == {
        "baseline_time_s": 0.0,
        "load_start_time_s": 1.0,
        "baseline_current_a": 0.0,
        "current_a": -3.0,
        "baseline_cell_v": 3.5,
        "cell_v": 3.0,
        "cell_sag_v": 0.5,
        "median_sag_v": 0.125,
    }


def test_acquisition_gap_does_not_accumulate_sustained_duration():
    source = frame([0, 1, 5, 6])
    source["cell_2_v"] = 3.0
    result = reference_models(source, config())["CELL_IMBALANCE_SUSTAINED"]
    assert result["events"] == []
    assert result["status"] == "NOT_EVALUATED"


@pytest.mark.parametrize("times", [[0, 0, 1], [0, 2, 1], [0, np.nan, 1]])
def test_unsupported_timestamp_contract_is_rejected(times):
    with pytest.raises(ValueError, match="strictly increasing"):
        reference_models(frame(times), config())


def test_no_resting_reference_keeps_load_not_evaluated():
    result = reference_models(frame(current=[-3] * 6), config())["CELL_SAG_UNDER_LOAD"]
    assert result["evaluated_samples"] == 0
    assert result["incomplete_intervals"] == 1
    assert result["status"] == "NOT_EVALUATED"


def test_one_resting_reference_cannot_be_reused_for_a_later_load():
    source = frame(range(7), current=[0, -3, -3, -1, -3, -3, 0])
    result = reference_models(source, config())["CELL_SAG_UNDER_LOAD"]
    assert result["evaluated_samples"] == 1
    assert result["incomplete_intervals"] == 1
    assert result["status"] == "NOT_EVALUATED"


def test_numeric_audit_rejects_tampered_event_peak():
    source = frame()
    source["temp_1_c"] = [25, 27, 27, 27, 27, 27]
    reference = reference_models(source, config())
    actual = {
        "failure_models": {
            "evaluations": [deepcopy(value) | {"code": code} for code, value in reference.items()]
        }
    }
    assert compare_models(actual, reference) == 1
    actual["failure_models"]["evaluations"][1]["events"][0]["measured_value"] += 1
    with pytest.raises(AssertionError, match="measured_value"):
        compare_models(actual, reference)
