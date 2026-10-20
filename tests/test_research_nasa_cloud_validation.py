"""Anchor the independent NASA array reference before external-data comparison."""

import copy

import numpy as np
import pandas as pd
import pytest

from batterylog_research.nasa_cloud_validation import (
    canonical_operation,
    compare_temperature,
    temperature_reference,
    verify_source,
)


def frame(times, temperatures):
    return pd.DataFrame(
        {
            "timestamp_s": times,
            "cell_1_v": [3.5] * len(times),
            "temp_1_c": temperatures,
            "pack_current_a": [0.0] * len(times),
        }
    )


def test_reference_rate_units_earliest_peak_and_sample_chain():
    reference = temperature_reference(frame([0, 10, 20], [25, 26, 27]))
    assert reference["status"] == "FAIL"
    assert reference["evaluated_samples"] == 2
    assert reference["events"] == [
        {
            "start_time_s": 10.0,
            "end_time_s": 20.0,
            "peak_time_s": 10.0,
            "measured_value": 6.0,
            "sample_count": 2,
            "evidence": {
                "previous_time_s": 0.0,
                "interval_s": 10.0,
                "previous_temperature_c": 25.0,
                "temperature_c": 26.0,
            },
        }
    ]
    corrupted = copy.deepcopy(reference)
    corrupted["events"][0]["evidence"]["temperature_c"] += 1
    with pytest.raises(AssertionError, match="temperature_c"):
        compare_temperature(corrupted, reference)


def test_invalid_source_and_large_gap_break_reference_continuity():
    reference = temperature_reference(frame([0, 1, 2, 3, 4], [25, 26, np.nan, 28, 29]))
    assert reference["evaluated_samples"] == 2
    assert [event["start_time_s"] for event in reference["events"]] == [1, 4]
    gap = temperature_reference(frame([0, 61, 62], [25, 30, 31]))
    assert gap["evaluated_samples"] == 1
    assert gap["events"][0]["evidence"]["previous_time_s"] == 61


def test_adapter_preserves_nan_and_rejects_time_regression():
    data = {
        "Time": [0, 1, 2],
        "Voltage_measured": [3.5, np.nan, 3.4],
        "Temperature_measured": [25, 26, 27],
        "Current_measured": [0, -2, -2],
    }
    canonical = canonical_operation(data)
    assert len(canonical) == 3
    assert np.isnan(canonical["cell_1_v"].iloc[1])
    assert canonical["pack_current_a"].tolist() == [0, -2, -2]
    data["Time"] = [0, 2, 1]
    with pytest.raises(ValueError, match="strictly increasing"):
        canonical_operation(data)


def test_source_identity_rejects_unverified_bytes(tmp_path):
    path = tmp_path / "B0005.mat"
    path.write_bytes(b"unexpected source")
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_source(path, {"bytes": 17, "git_blob": "invalid", "sha256": "invalid"})
