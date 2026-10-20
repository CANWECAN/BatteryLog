"""Reject source-clock regressions hidden by binary64 conversion."""

from decimal import Decimal
from io import BytesIO

import pandas as pd
import pytest

from batterylog import ValidationLimits
from batterylog.analysis.core import _analyze_battery_frame, analyze_battery_bytes
from batterylog.analysis.streaming import _analyze_battery_chunks, analyze_measurement_loader
from batterylog.config import DataQualityConfig, SignalMapping, SignalPattern
from batterylog.loaders import CsvFileLoader

REGRESSIONS = [
    ("9007199254740993", "9007199254740992"),
    ("1700000000.0000001", "1700000000.0000000"),
    ("1.0000000000000001", "1.0000000000000000"),
    ("18446744073709551615", "18446744073709551614"),
    ("-9007199254740992", "-9007199254740993"),
]


def _frame(timestamps):
    return pd.DataFrame(
        {
            "timestamp_s": pd.Series(timestamps, dtype=object),
            "cell_1_v": [3.7] * len(timestamps),
            "temp_c": [25.0] * len(timestamps),
        }
    )


@pytest.mark.parametrize("first,second", REGRESSIONS)
@pytest.mark.parametrize("chunk_rows", [1, 2, 3])
@pytest.mark.parametrize("mode", ["strict", "exclude_invalid_rows"])
def test_csv_clock_order_survives_numeric_rounding(first, second, chunk_rows, mode):
    assert Decimal(first) > Decimal(second)
    assert float(first) == float(second)
    data = f"timestamp_s,cell_1_v,temp_c\n{first},3.7,25\n{second},3.7,25\n".encode()
    options = {
        "limits": ValidationLimits(cell_max_v=4.2),
        "data_quality": DataQualityConfig(mode=mode),
    }
    with pytest.raises(ValueError, match="timestamp_s must be non-decreasing"):
        analyze_battery_bytes(data, **options)
    with pytest.raises(ValueError, match="timestamp_s must be non-decreasing"):
        analyze_measurement_loader(CsvFileLoader(BytesIO(data), chunk_rows=chunk_rows), **options)


@pytest.mark.parametrize(
    "timestamps",
    [
        [9007199254740993, 9007199254740992],
        [2**64 - 1, 2**64 - 2],
        [Decimal("1.0000000000000001"), Decimal(1)],
        [2**63 - 1, -(2**63)],
    ],
)
@pytest.mark.parametrize("chunk_rows", [1, 2])
def test_frame_clock_order_preserves_integer_decimal_and_signed_range(timestamps, chunk_rows):
    frame = _frame(timestamps)
    with pytest.raises(ValueError, match="timestamp_s must be non-decreasing"):
        _analyze_battery_frame(frame)
    with pytest.raises(ValueError, match="timestamp_s must be non-decreasing"):
        _analyze_battery_chunks(
            [frame.iloc[i : i + chunk_rows] for i in range(0, len(frame), chunk_rows)]
        )


@pytest.mark.parametrize("chunk_rows", [1, 2])
def test_mapped_csv_clock_keeps_original_decimal_order(chunk_rows):
    mapping = SignalMapping(
        timestamp="clock",
        cell_voltage=SignalPattern(pattern=r"V(?P<index>\d+)"),
        temperature=SignalPattern(pattern=r"T(?P<index>\d+)"),
    )
    data = b"clock,V1,T1\n1700000000.0000001,3.7,25\n1700000000.0000000,3.7,25\n"
    with pytest.raises(ValueError, match="timestamp_s must be non-decreasing"):
        analyze_battery_bytes(data, signal_mapping=mapping)
    with pytest.raises(ValueError, match="timestamp_s must be non-decreasing"):
        analyze_measurement_loader(
            CsvFileLoader(BytesIO(data), chunk_rows=chunk_rows), signal_mapping=mapping
        )


@pytest.mark.parametrize("chunk_rows", [1, 2, 3])
def test_valid_neighbouring_times_and_duplicates_still_pass(chunk_rows):
    data = (
        b"timestamp_s,cell_1_v,temp_c\n"
        b"1700000000.0000000,3.7,25\n"
        b"1700000000.0000001,3.7,25\n"
        b"1700000000.0000001,3.7,25\n"
    )
    limits = ValidationLimits(cell_max_v=4.2)
    expected = analyze_battery_bytes(data, limits=limits)
    actual = analyze_measurement_loader(
        CsvFileLoader(BytesIO(data), chunk_rows=chunk_rows), limits=limits
    )
    assert expected == actual
    assert actual["validation_status"] == "PASS"


@pytest.mark.parametrize("chunk_rows", [1, 2, 3])
def test_clock_regression_precedes_later_numeric_defect(chunk_rows):
    data = (
        b"timestamp_s,cell_1_v,temp_c\n"
        b"9007199254740993,3.7,25\n"
        b"9007199254740992,3.7,25\n"
        b"9007199254740994,bad,25\n"
    )
    with pytest.raises(ValueError, match="timestamp_s must be non-decreasing"):
        analyze_measurement_loader(CsvFileLoader(BytesIO(data), chunk_rows=chunk_rows))
