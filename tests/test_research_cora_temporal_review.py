"""Prepared CORA source integrity and independent temporal context checks."""

import json

import numpy as np
import pandas as pd
import pytest

from batterylog_research.cora_temporal_review import COLUMNS, main, review_branch


def _branch(times=(0, 1, 2, 3, 4, 5), current=(0, 0, 0, -3, -3, -3)):
    values = {"timestamp_s": times, "pack_current_a": current, "pack_voltage_v": [42.0] * 6}
    values.update({f"cell_{i}_v": [3.5] * 6 for i in range(1, 13)})
    values.update({f"temp_{i}_c": [25.0] * 6 for i in range(1, 25)})
    return pd.DataFrame(values)[COLUMNS]


def test_rest_span_and_core_eligibility_are_traceable_without_mutating_source():
    frame = _branch()
    original = frame.copy(deep=True)
    report = review_branch(frame)
    pd.testing.assert_frame_equal(frame, original)
    sag = report["sag_context"]
    assert sag["reference_reason_counts"] == {"reference_available": 1}
    assert sag["episodes"][0]["observed_low_current_span_s"] == 2
    assert sag["episodes"][0]["reference_age_at_onset_s"] == 1
    assert sag["episodes"][0]["eligible_samples"] == 2
    assert report["core"]["CELL_SAG_UNDER_LOAD"]["evaluated_samples"] == 2
    assert report["temperature"]["adjacent"]["eligible_observations"] == 5
    json.dumps(report, allow_nan=False)


def test_gaps_break_value_change_intervals_and_sag_references():
    frame = _branch(times=(0, 1, 2, 10, 11, 12))
    frame["temp_1_c"] = [25, 26, 27, 28, 29, 30]
    report = review_branch(frame)
    assert report["gap_count"] == 1
    changes = report["temperature"]["per_sensor_changes"][0]
    assert changes["between_observed_changes_s"] == {
        "count": 2,
        "min": 1.0,
        "median": 1.0,
        "p95": 1.0,
        "max": 1.0,
    }
    assert report["sag_context"]["reference_reason_counts"] == {"missing_rest_reference": 1}
    assert report["core"]["CELL_SAG_UNDER_LOAD"]["status"] == "NOT_EVALUATED"


def test_recorded_extreme_is_preserved_and_windows_are_not_silent_filters():
    frame = _branch()
    frame.loc[3, "temp_10_c"] = 655.28
    report = review_branch(frame)
    maximum = report["temperature"]["recorded_maximum"]
    assert maximum == {
        "value_c": 655.28,
        "sensor": "temp_10_c",
        "row_index": 3,
        "timestamp_s": 3.0,
    }
    assert report["core"]["TEMPERATURE_RISE_HIGH"]["status"] == "FAIL"
    assert report["temperature"]["endpoint_windows_s"]["1"]["exceeding_observations"] == 1
    assert frame.loc[3, "temp_10_c"] == 655.28


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "extra",
        "duplicate",
        "object",
        "boolean",
        "nan",
        "infinite",
        "descending",
        "equal",
        "short",
    ],
)
def test_bad_prepared_source_is_rejected_without_repair(bad):
    frame = _branch()
    if bad == "missing":
        frame = frame.drop(columns="temp_24_c")
    elif bad == "extra":
        frame["invented_phase"] = 0
    elif bad == "duplicate":
        frame = pd.concat([frame, frame[["temp_1_c"]]], axis=1)
    elif bad == "object":
        frame["temp_1_c"] = frame["temp_1_c"].astype(str)
    elif bad == "boolean":
        frame["temp_1_c"] = True
    elif bad == "nan":
        frame.loc[1, "temp_1_c"] = np.nan
    elif bad == "infinite":
        frame.loc[1, "temp_1_c"] = np.inf
    elif bad == "descending":
        frame.loc[1, "timestamp_s"] = -1
    elif bad == "equal":
        frame.loc[1, "timestamp_s"] = 0
    else:
        frame = frame.iloc[:1]
    with pytest.raises(ValueError):
        review_branch(frame)


def test_cli_preserves_csv_and_refuses_to_overwrite_report(tmp_path):
    csv = tmp_path / "branch.csv"
    output = tmp_path / "review.json"
    _branch().to_csv(csv, index=False)
    original = csv.read_bytes()
    assert main([str(csv), "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["branches"][0]["rows"] == 6
    assert report["production_decisions_changed"] is False
    assert csv.read_bytes() == original
    first_report = output.read_bytes()
    with pytest.raises(FileExistsError):
        main([str(csv), "--output", str(output)])
    assert output.read_bytes() == first_report


@pytest.mark.parametrize("values", [[1.5e308, 1.5e308], [-1.5e308, 1.5e308]])
def test_finite_inputs_cannot_return_nonfinite_descriptive_statistics(values):
    from batterylog_research.cora_temporal_review import _stats

    with pytest.raises(ValueError, match="statistic overflowed"):
        _stats(values)


def test_finite_temperature_grid_overflow_is_rejected_without_source_mutation():
    frame = _branch()
    for name in [f"temp_{i}_c" for i in range(1, 25)]:
        frame[name] = 1e307
    original = frame.copy(deep=True)
    with pytest.raises(ValueError, match="descriptor calculation overflowed"):
        review_branch(frame)
    pd.testing.assert_frame_equal(frame, original)


def test_finite_intervals_cannot_hide_overflowing_total_capture_duration():
    frame = _branch(times=(-1e308, -6e307, -2e307, 2e307, 6e307, 1e308))
    original = frame.copy(deep=True)
    assert np.isfinite(np.diff(frame["timestamp_s"].to_numpy())).all()
    with pytest.raises(ValueError, match="finite duration"):
        review_branch(frame)
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
@pytest.mark.parametrize("existing", [False, True])
def test_json_encoding_failure_neither_creates_nor_overwrites_output(
    tmp_path, monkeypatch, bad, existing
):
    from batterylog_research import cora_temporal_review as module

    csv = tmp_path / "branch.csv"
    output = tmp_path / "review.json"
    _branch().to_csv(csv, index=False)
    original_source = csv.read_bytes()
    if existing:
        output.write_bytes(b"existing report")
    monkeypatch.setattr(module, "review_branch", lambda frame: {"derived": bad})
    with pytest.raises(ValueError, match="JSON compliant"):
        module.main([str(csv), "--output", str(output)])
    assert csv.read_bytes() == original_source
    if existing:
        assert output.read_bytes() == b"existing report"
    else:
        assert not output.exists()
