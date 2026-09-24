from dataclasses import FrozenInstanceError
from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from batterylog import ValidationLimits
from batterylog.analysis.report_series import (
    ReportSeriesCollector,
    ReportSeriesPoint,
)
from batterylog.analysis.streaming import (
    analyze_battery_file_with_report_series,
    analyze_measurement_loader,
    analyze_measurement_loader_with_report_series,
)


def _point(index: int, **overrides: float) -> ReportSeriesPoint:
    values = {
        "timestamp_s": float(index),
        "cell_min_v": 3.5,
        "cell_max_v": 4.0,
        "cell_delta_v": 0.5,
        "temperature_min_c": 20.0,
        "temperature_max_c": 30.0,
    }
    values.update(overrides)
    return ReportSeriesPoint(row_index=index, **values)


def test_report_series_keeps_small_inputs_lossless() -> None:
    collector = ReportSeriesCollector(max_points=24)
    original = tuple(_point(index) for index in range(10))

    for point in original:
        collector.consume(point)

    series = collector.finish()

    assert series.points == original
    assert series.source_rows == 10
    assert series.max_points == 24
    assert series.strategy == "extrema-preserving-v1"
    assert series.is_downsampled is False


def test_report_series_is_immutable() -> None:
    point = _point(0)
    collector = ReportSeriesCollector(max_points=14)
    collector.consume(point)
    series = collector.finish()

    with pytest.raises(FrozenInstanceError):
        point.timestamp_s = 2.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        series.source_rows = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    ("value", "error", "message"),
    [
        (True, TypeError, "max_points must be an integer"),
        (12.5, TypeError, "max_points must be an integer"),
        (13, ValueError, "max_points must be at least 14"),
    ],
)
def test_report_series_rejects_invalid_point_budget(value, error, message) -> None:
    with pytest.raises(error, match=message):
        ReportSeriesCollector(max_points=value)


def test_report_series_rejects_non_contiguous_row_order() -> None:
    collector = ReportSeriesCollector(max_points=14)

    with pytest.raises(ValueError, match="expected 0, got 1"):
        collector.consume(_point(1))


def test_report_series_finish_is_idempotent_and_terminal() -> None:
    collector = ReportSeriesCollector(max_points=14)
    collector.consume(_point(0))

    first = collector.finish()
    second = collector.finish()

    assert second is first
    with pytest.raises(RuntimeError, match=r"after finish\(\)"):
        collector.consume(_point(1))


def test_report_series_chunk_rejects_mismatched_array_lengths() -> None:
    collector = ReportSeriesCollector(max_points=14)
    one = np.array([1.0])
    two = np.array([1.0, 2.0])

    with pytest.raises(ValueError, match="chunk arrays must have equal lengths"):
        collector.consume_chunk(
            row_offset=0,
            timestamps=two,
            cell_min=one,
            cell_max=two,
            cell_delta=two,
            temperature_min=two,
            temperature_max=two,
        )


def test_report_series_chunk_order_empty_chunk_and_terminal_contract() -> None:
    collector = ReportSeriesCollector(max_points=14)
    empty = np.array([], dtype=float)
    one = np.array([1.0])

    collector.consume_chunk(
        row_offset=0,
        timestamps=empty,
        cell_min=empty,
        cell_max=empty,
        cell_delta=empty,
        temperature_min=empty,
        temperature_max=empty,
    )
    assert collector.source_rows == 0

    with pytest.raises(ValueError, match="expected 0, got 1"):
        collector.consume_chunk(
            row_offset=1,
            timestamps=one,
            cell_min=one,
            cell_max=one,
            cell_delta=one,
            temperature_min=one,
            temperature_max=one,
        )

    collector.finish()
    with pytest.raises(RuntimeError, match=r"after finish\(\)"):
        collector.consume_chunk(
            row_offset=0,
            timestamps=empty,
            cell_min=empty,
            cell_max=empty,
            cell_delta=empty,
            temperature_min=empty,
            temperature_max=empty,
        )


def test_large_array_hot_path_preserves_extrema_within_budget() -> None:
    rows = 200
    timestamps = np.arange(rows, dtype=float)
    cell_min = np.full(rows, 3.5)
    cell_max = np.full(rows, 4.0)
    cell_delta = np.full(rows, 0.5)
    temperature_min = np.full(rows, 20.0)
    temperature_max = np.full(rows, 30.0)
    cell_min[70] = 1.0
    cell_max[80] = 8.0
    cell_delta[90] = 3.0
    temperature_min[100] = -40.0
    temperature_max[110] = 120.0

    collector = ReportSeriesCollector(max_points=24)
    collector.consume_chunk(
        row_offset=0,
        timestamps=timestamps,
        cell_min=cell_min,
        cell_max=cell_max,
        cell_delta=cell_delta,
        temperature_min=temperature_min,
        temperature_max=temperature_max,
    )
    series = collector.finish()
    retained_rows = {point.row_index for point in series.points}

    assert len(series.points) <= 24
    assert {0, rows - 1, 70, 80, 90, 100, 110}.issubset(retained_rows)


def test_extrema_reducer_respects_budget_and_preserves_required_points() -> None:
    collector = ReportSeriesCollector(max_points=24)
    overrides = {
        10: {"cell_min_v": 1.0},
        11: {"cell_min_v": 6.0},
        12: {"cell_max_v": 1.5},
        13: {"cell_max_v": 7.0},
        14: {"cell_delta_v": 0.01},
        15: {"cell_delta_v": 2.0},
        16: {"temperature_min_c": -50.0},
        17: {"temperature_min_c": 90.0},
        18: {"temperature_max_c": -40.0},
        19: {"temperature_max_c": 120.0},
    }

    for index in range(100):
        collector.consume(_point(index, **overrides.get(index, {})))

    series = collector.finish()
    retained_rows = {point.row_index for point in series.points}

    assert series.source_rows == 100
    assert series.is_downsampled is True
    assert len(series.points) <= 24
    assert {0, 99, *overrides}.issubset(retained_rows)


def test_extrema_reducer_uses_earliest_row_for_equal_extrema() -> None:
    collector = ReportSeriesCollector(max_points=14)
    for index in range(40):
        cell_max = 9.0 if index in {5, 6} else 4.0
        collector.consume(_point(index, cell_max_v=cell_max))

    rows = {point.row_index for point in collector.finish().points}

    assert 5 in rows


FINITE_VALUE = st.floats(
    min_value=-1000.0,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
    width=32,
)


@given(
    rows=st.lists(
        st.tuples(FINITE_VALUE, FINITE_VALUE, FINITE_VALUE, FINITE_VALUE, FINITE_VALUE),
        min_size=1,
        max_size=250,
    ),
    max_points=st.sampled_from([14, 28, 42, 56]),
)
def test_chunk_optimized_reducer_matches_pointwise_reference(
    rows: list[tuple[float, float, float, float, float]],
    max_points: int,
) -> None:
    pointwise = ReportSeriesCollector(max_points=max_points)
    chunked = ReportSeriesCollector(max_points=max_points)

    for index, values in enumerate(rows):
        pointwise.consume(
            ReportSeriesPoint(
                row_index=index,
                timestamp_s=float(index),
                cell_min_v=values[0],
                cell_max_v=values[1],
                cell_delta_v=values[2],
                temperature_min_c=values[3],
                temperature_max_c=values[4],
            )
        )

    metrics = list(zip(*rows, strict=True))
    timestamps = np.arange(len(rows), dtype=float)
    arrays = [np.asarray(values, dtype=float) for values in metrics]
    split = max(1, len(rows) // 3)
    for start in range(0, len(rows), split):
        end = min(len(rows), start + split)
        chunked.consume_chunk(
            row_offset=start,
            timestamps=timestamps[start:end],
            cell_min=arrays[0][start:end],
            cell_max=arrays[1][start:end],
            cell_delta=arrays[2][start:end],
            temperature_min=arrays[3][start:end],
            temperature_max=arrays[4][start:end],
        )

    assert chunked.finish() == pointwise.finish()


@given(
    rows=st.lists(
        st.tuples(FINITE_VALUE, FINITE_VALUE, FINITE_VALUE, FINITE_VALUE, FINITE_VALUE),
        min_size=1,
        max_size=250,
    ),
    max_points=st.sampled_from([14, 28, 42, 56]),
)
def test_extrema_reducer_property_preserves_global_metric_extrema(
    rows: list[tuple[float, float, float, float, float]],
    max_points: int,
) -> None:
    collector = ReportSeriesCollector(max_points=max_points)
    original: list[ReportSeriesPoint] = []
    for index, values in enumerate(rows):
        point = ReportSeriesPoint(
            row_index=index,
            timestamp_s=float(index),
            cell_min_v=values[0],
            cell_max_v=values[1],
            cell_delta_v=values[2],
            temperature_min_c=values[3],
            temperature_max_c=values[4],
        )
        original.append(point)
        collector.consume(point)

    series = collector.finish()

    assert len(series.points) <= max_points
    assert series.source_rows == len(original)
    assert series.points[0] == original[0]
    assert series.points[-1] == original[-1]
    for metric in (
        "cell_min_v",
        "cell_max_v",
        "cell_delta_v",
        "temperature_min_c",
        "temperature_max_c",
    ):
        expected_values = [getattr(point, metric) for point in original]
        retained_values = [getattr(point, metric) for point in series.points]
        assert min(retained_values) == min(expected_values)
        assert max(retained_values) == max(expected_values)


class _ChunkedLoader:
    source_format = "fake"

    def __init__(self, frame: pd.DataFrame, chunk_rows: int) -> None:
        self._frame = frame
        self._chunk_rows = chunk_rows

    def iter_chunks(self, *, signal_mapping):
        assert signal_mapping is None
        for start in range(0, len(self._frame), self._chunk_rows):
            yield self._frame.iloc[start : start + self._chunk_rows].copy()


def _analysis_frame(rows: int = 80) -> pd.DataFrame:
    indexes = list(range(rows))
    return pd.DataFrame(
        {
            "timestamp_s": [index * 0.5 for index in indexes],
            "cell_1_v": [3.7 + (0.7 if index == 37 else 0.0) for index in indexes],
            "cell_2_v": [3.6 - (0.5 if index == 42 else 0.0) for index in indexes],
            "temp_1_c": [25.0 + (40.0 if index == 51 else 0.0) for index in indexes],
            "temp_2_c": [24.0 - (30.0 if index == 61 else 0.0) for index in indexes],
        }
    )


def test_report_series_is_chunk_boundary_invariant_and_does_not_change_result() -> None:
    frame = _analysis_frame()
    limits = ValidationLimits(
        cell_min_v=2.8,
        cell_max_v=4.2,
        imbalance_max_v=0.08,
        temperature_min_c=-20.0,
        temperature_max_c=55.0,
    )

    expected_result = analyze_measurement_loader(_ChunkedLoader(frame, 9), limits=limits)
    result_a, series_a = analyze_measurement_loader_with_report_series(
        _ChunkedLoader(frame, 1),
        limits=limits,
        max_points=24,
    )
    result_b, series_b = analyze_measurement_loader_with_report_series(
        _ChunkedLoader(frame, 17),
        limits=limits,
        max_points=24,
    )

    assert result_a == expected_result
    assert result_b == expected_result
    assert series_a == series_b
    assert series_a.source_rows == len(frame)
    assert len(series_a.points) <= 24
    assert series_a.points[0].row_index == 0
    assert series_a.points[-1].row_index == len(frame) - 1

    retained_rows = {point.row_index for point in series_a.points}
    assert {37, 42, 51, 61}.issubset(retained_rows)


def test_file_backed_report_series_wrapper_uses_loader_factory() -> None:
    source = BytesIO(
        b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.8,3.7,25\n1,4.3,3.8,56\n2,3.9,3.8,25\n"
    )

    result, series = analyze_battery_file_with_report_series(
        source,
        source_name="capture.csv",
        limits=ValidationLimits(cell_max_v=4.2, temperature_max_c=55.0),
        max_points=14,
    )

    assert result["validation_status"] == "FAIL"
    assert result["rows_analyzed"] == 3
    assert series.source_rows == 3
    assert [point.timestamp_s for point in series.points] == [0.0, 1.0, 2.0]

def test_report_series_temperature_spread_is_derived_without_expanding_point_contract() -> None:
    point = _point(0, temperature_min_c=21.0, temperature_max_c=34.5)
    assert point.temperature_spread_c == pytest.approx(13.5)
