import pandas as pd
import pytest

from batterylog.analysis.preparation import prepare_measurements
from batterylog.analysis.summary import (
    MeasurementSummary,
    analysis_metrics_from_summary,
    merge_measurement_summaries,
    summarize_prepared_measurements,
)


def _prepared(frame: pd.DataFrame):
    invalid_rows = pd.Series(False, index=frame.index, dtype=bool)
    return prepare_measurements(
        frame,
        invalid_rows,
        pack_cols=["pack_current_a", "pack_voltage_v"],
        cell_cols=["cell_1_v", "cell_2_v"],
        temp_cols=["temp_1_c", "temp_2_c"],
        pack_current_col="pack_current_a",
        pack_voltage_col="pack_voltage_v",
    )


def test_summary_uses_same_extrema_and_earliest_pack_peak_semantics() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0],
            "pack_current_a": [-5.0, 7.0],
            "pack_voltage_v": [7.9, 7.5],
            "cell_1_v": [3.7, 3.6],
            "cell_2_v": [3.7, 3.4],
            "temp_1_c": [20.0, 30.0],
            "temp_2_c": [25.0, 35.0],
        }
    )
    summary = summarize_prepared_measurements(_prepared(frame))

    assert summary.max_cell_voltage_v == 3.7
    assert summary.min_cell_voltage_v == 3.4
    assert summary.max_delta_v == pytest.approx(0.2)
    assert summary.max_temperature_c == 35.0
    assert summary.min_temperature_c == 20.0
    assert summary.max_temperature_spread_c == 5.0
    assert summary.max_pack_current_a == 7.0
    assert summary.min_pack_current_a == -5.0
    assert summary.max_pack_voltage_v == 7.9
    assert summary.min_pack_voltage_v == 7.5
    assert summary.pack_voltage_cell_sum_peak is not None
    assert summary.pack_voltage_cell_sum_peak["timestamp_s"] == 0.0
    assert summary.pack_voltage_cell_sum_peak["absolute_delta_v"] == 0.5


def test_summary_merge_preserves_first_equal_pack_peak() -> None:
    first_peak = {
        "timestamp_s": 1.0,
        "pack_voltage_v": 8.0,
        "cell_voltage_sum_v": 7.5,
        "signed_error_v": 0.5,
        "absolute_delta_v": 0.5,
    }
    second_peak = {
        "timestamp_s": 2.0,
        "pack_voltage_v": 8.1,
        "cell_voltage_sum_v": 7.6,
        "signed_error_v": 0.5,
        "absolute_delta_v": 0.5,
    }
    merged = merge_measurement_summaries(
        MeasurementSummary(max_delta_v=0.1, pack_voltage_cell_sum_peak=first_peak),
        MeasurementSummary(max_delta_v=0.2, pack_voltage_cell_sum_peak=second_peak),
    )

    assert merged.max_delta_v == 0.2
    assert merged.pack_voltage_cell_sum_peak is first_peak


def test_summary_merge_replaces_pack_peak_only_when_strictly_larger() -> None:
    first_peak = {
        "timestamp_s": 1.0,
        "pack_voltage_v": 8.0,
        "cell_voltage_sum_v": 7.5,
        "signed_error_v": 0.5,
        "absolute_delta_v": 0.5,
    }
    larger_peak = {
        "timestamp_s": 2.0,
        "pack_voltage_v": 8.3,
        "cell_voltage_sum_v": 7.6,
        "signed_error_v": 0.7,
        "absolute_delta_v": 0.7,
    }

    merged = merge_measurement_summaries(
        MeasurementSummary(pack_voltage_cell_sum_peak=first_peak),
        MeasurementSummary(pack_voltage_cell_sum_peak=larger_peak),
    )

    assert merged.pack_voltage_cell_sum_peak is larger_peak


def test_analysis_metrics_round_only_public_delta_summaries() -> None:
    metrics = analysis_metrics_from_summary(
        MeasurementSummary(
            max_cell_voltage_v=4.20000000000049,
            max_delta_v=0.10000000000049,
            max_temperature_spread_c=10.00000000000049,
        )
    )

    assert metrics.max_cell_voltage_v == 4.20000000000049
    assert metrics.max_delta_v == 0.1
    assert metrics.max_temperature_spread_c == 10.0
