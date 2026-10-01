import warnings
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from batterylog import AnalysisService, DataQualityConfig, ValidationConfig
from batterylog.analysis.core import _analyze_battery_frame

SIGNALS = ["timestamp_s", "cell_1_v", "temp_c", "pack_current_a", "pack_voltage_v"]
ENTRYPOINTS = [("frame", 3), ("service", 1), ("service", 3)]


class FrameLoader:
    source_format = "custom"

    def __init__(self, frame: pd.DataFrame, chunk_rows: int):
        self.frame = frame
        self.chunk_rows = chunk_rows

    def iter_chunks(self, *, signal_mapping) -> Iterator[pd.DataFrame]:
        for start in range(0, len(self.frame), self.chunk_rows):
            yield self.frame.iloc[start : start + self.chunk_rows]


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0],
            "cell_1_v": [3.5] * 3,
            "temp_c": [25.0] * 3,
            "pack_current_a": [0.0] * 3,
            "pack_voltage_v": [3.5] * 3,
        }
    )


def _analyze(frame, mode, entrypoint, chunk_rows):
    config = ValidationConfig(data_quality=DataQualityConfig(mode))
    if entrypoint == "frame":
        return _analyze_battery_frame(frame, data_quality=config.data_quality), None
    output = AnalysisService(config).analyze_loader(
        FrameLoader(frame, chunk_rows), report_max_points=20
    )
    return output.result, output.report_series


def _assert_defects(result, signal, analyzed_rows, invalid_end):
    assert result["validation_status"] == "FAIL"
    assert result["rows_input"] == 3
    assert result["rows_analyzed"] == analyzed_rows
    assert result["rows_excluded"] == 3 - analyzed_rows
    assert result["violations"] == []
    assert result["data_quality"]["events"] == [
        {
            "code": "NON_NUMERIC_REQUIRED_VALUE",
            "start_row": 1,
            "end_row": invalid_end,
            "signals": [signal],
            "affected_values": invalid_end,
        },
        {
            "code": "MISSING_REQUIRED_VALUE",
            "start_row": 3,
            "end_row": 3,
            "signals": [signal],
            "affected_values": 1,
        },
    ]


@pytest.mark.parametrize(
    "kind", ["complex64", "complex128", "datetime", "datetime_tz", "timedelta"]
)
@pytest.mark.parametrize("signal", SIGNALS)
@pytest.mark.parametrize("mode", ["strict", "exclude_invalid_rows"])
@pytest.mark.parametrize("entrypoint,chunk_rows", ENTRYPOINTS)
def test_native_non_real_measurements_are_never_coerced_to_valid_numbers(
    kind, signal, mode, entrypoint, chunk_rows
):
    frame = _frame()
    if kind.startswith("complex"):
        values = pd.Series([25 + 9j, 30 + 1j, np.nan], dtype=kind)
    elif kind == "timedelta":
        values = pd.Series(pd.to_timedelta([25, 30, None], unit="ns"))
    else:
        values = pd.Series(pd.to_datetime([25, 30, None], unit="ns", utc=kind.endswith("_tz")))
    frame[signal] = values
    before = frame.copy(deep=True)
    with warnings.catch_warnings():
        warnings.simplefilter("error", np.exceptions.ComplexWarning)
        if mode == "strict":
            with pytest.raises(ValueError, match=rf"data row 1 .*column '{signal}'"):
                _analyze(frame, mode, entrypoint, chunk_rows)
        else:
            result, series = _analyze(frame, mode, entrypoint, chunk_rows)
            _assert_defects(result, signal, analyzed_rows=0, invalid_end=2)
            if entrypoint == "service":
                assert series is not None
                assert series.source_rows == 0
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize("dtype", ["object", "category"])
@pytest.mark.parametrize("signal", SIGNALS)
@pytest.mark.parametrize("mode", ["strict", "exclude_invalid_rows"])
@pytest.mark.parametrize("entrypoint,chunk_rows", ENTRYPOINTS)
def test_mixed_complex_measurements_preserve_real_and_missing_rows(
    dtype, signal, mode, entrypoint, chunk_rows
):
    frame = _frame()
    normal = frame.loc[1, signal]
    frame[signal] = pd.Series([25 + 9j, str(normal), None], dtype=dtype)
    before = frame.copy(deep=True)
    with warnings.catch_warnings():
        warnings.simplefilter("error", np.exceptions.ComplexWarning)
        if mode == "strict":
            with pytest.raises(ValueError, match=rf"data row 1 .*column '{signal}'"):
                _analyze(frame, mode, entrypoint, chunk_rows)
        else:
            result, series = _analyze(frame, mode, entrypoint, chunk_rows)
            _assert_defects(result, signal, analyzed_rows=1, invalid_end=1)
            if entrypoint == "service":
                assert series is not None
                assert series.source_rows == 1
                assert [point.timestamp_s for point in series.points] == [1.0]
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize("dtype", ["float64", "Float64", "object", "category", "decimal"])
@pytest.mark.parametrize("entrypoint,chunk_rows", ENTRYPOINTS)
def test_supported_real_measurements_keep_existing_results(dtype, entrypoint, chunk_rows):
    frame = _frame()
    if dtype == "decimal":
        frame = frame.map(lambda value: Decimal(str(value)))
    elif dtype in {"object", "category"}:
        frame = frame.astype(str).astype(dtype)
    else:
        frame = frame.astype(dtype)
    result, _ = _analyze(frame, "strict", entrypoint, chunk_rows)
    assert result["validation_status"] == "NOT_EVALUATED"
    assert (result["rows_input"], result["rows_analyzed"], result["rows_excluded"]) == (3, 3, 0)
    assert result["data_quality"]["events"] == []
    assert result["max_cell_voltage_v"] == 3.5
    assert result["max_temperature_c"] == 25.0
    assert result["min_pack_current_a"] == result["max_pack_current_a"] == 0.0
    assert result["min_pack_voltage_v"] == result["max_pack_voltage_v"] == 3.5


@pytest.mark.parametrize("dtype", ["object", "category"])
@pytest.mark.parametrize(
    "value",
    [
        np.timedelta64(1, "h"),
        np.timedelta64(1000, "ms"),
        np.datetime64("2026-01-01"),
        pd.Timedelta(hours=1),
        pd.Timestamp("2026-01-01"),
        timedelta(hours=1),
        datetime(2026, 1, 1, tzinfo=UTC),
    ],
)
@pytest.mark.parametrize("mode", ["strict", "exclude_invalid_rows"])
def test_mixed_temporal_measurements_remain_defects_across_chunks(dtype, value, mode):
    frame = _frame()
    frame["cell_1_v"] = pd.Series([value, "3.5", None], dtype=dtype)
    before = frame.copy(deep=True)
    if mode == "strict":
        with pytest.raises(ValueError, match=r"data row 1 .*column 'cell_1_v'"):
            _analyze(frame, mode, "service", 1)
    else:
        result, series = _analyze(frame, mode, "service", 1)
        _assert_defects(result, "cell_1_v", analyzed_rows=1, invalid_end=1)
        assert series is not None and series.source_rows == 1
        assert [point.timestamp_s for point in series.points] == [1.0]
    pd.testing.assert_frame_equal(frame, before)
