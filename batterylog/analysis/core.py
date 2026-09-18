from math import isfinite
from pathlib import Path
from typing import TypedDict

import numpy as np
import pandas as pd


class ViolationEvent(TypedDict):
    code: str
    start_time_s: float
    end_time_s: float
    peak_time_s: float
    measured_value: float
    limit_value: float
    unit: str
    signals: list[str]


class AnalysisResult(TypedDict):
    rows_analyzed: int
    cells_detected: int
    temperature_sensors_detected: int
    max_cell_voltage_v: float
    min_cell_voltage_v: float
    max_delta_v: float
    max_temperature_c: float
    violations: list[ViolationEvent]


def _validate_limit(name: str, value: float) -> None:
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite, non-negative number")


def _contiguous_true_ranges(mask: pd.Series) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start: int | None = None

    for position, active in enumerate(mask.to_numpy(dtype=bool)):
        if active and start is None:
            start = position
        elif not active and start is not None:
            ranges.append((start, position - 1))
            start = None

    if start is not None:
        ranges.append((start, len(mask) - 1))

    return ranges


def _find_signal_columns(columns: pd.Index) -> tuple[list[str], list[str]]:
    cell_cols = sorted(
        (c for c in columns if c.startswith("cell_") and c.endswith("_v")),
        key=str.casefold,
    )
    temp_cols = sorted(
        (c for c in columns if c.startswith("temp_") and c.endswith("_c")),
        key=str.casefold,
    )
    return cell_cols, temp_cols


def _build_imbalance_events(
    numeric: pd.DataFrame,
    timestamps: pd.Series,
    cell_cols: list[str],
    delta_v: pd.Series,
    limit_v: float,
) -> list[ViolationEvent]:
    events: list[ViolationEvent] = []

    for start, end in _contiguous_true_ranges(delta_v > limit_v):
        segment = delta_v.iloc[start : end + 1]
        peak_pos = start + int(np.argmax(segment.to_numpy()))
        peak_cells = numeric.iloc[peak_pos][cell_cols]
        max_signal = str(peak_cells.idxmax())
        min_signal = str(peak_cells.idxmin())

        events.append(
            {
                "code": "CELL_IMBALANCE_HIGH",
                "start_time_s": float(timestamps.iloc[start]),
                "end_time_s": float(timestamps.iloc[end]),
                "peak_time_s": float(timestamps.iloc[peak_pos]),
                "measured_value": round(float(delta_v.iloc[peak_pos]), 12),
                "limit_value": limit_v,
                "unit": "V",
                "signals": [max_signal, min_signal],
            }
        )

    return events


def _build_temperature_events(
    numeric: pd.DataFrame,
    timestamps: pd.Series,
    temp_cols: list[str],
    row_max_temp: pd.Series,
    limit_c: float,
) -> list[ViolationEvent]:
    events: list[ViolationEvent] = []

    for start, end in _contiguous_true_ranges(row_max_temp > limit_c):
        segment = row_max_temp.iloc[start : end + 1]
        peak_pos = start + int(np.argmax(segment.to_numpy()))
        peak_value = float(row_max_temp.iloc[peak_pos])
        peak_temperatures = numeric.iloc[peak_pos][temp_cols]
        hottest_signals = [
            str(signal) for signal, value in peak_temperatures.items() if float(value) == peak_value
        ]

        events.append(
            {
                "code": "TEMPERATURE_HIGH",
                "start_time_s": float(timestamps.iloc[start]),
                "end_time_s": float(timestamps.iloc[end]),
                "peak_time_s": float(timestamps.iloc[peak_pos]),
                "measured_value": peak_value,
                "limit_value": limit_c,
                "unit": "degC",
                "signals": hottest_signals,
            }
        )

    return events


def analyze_battery_log(
    path: str | Path,
    imbalance_limit_v: float = 0.08,
    temp_warning_c: float = 45.0,
) -> AnalysisResult:
    _validate_limit("imbalance_limit_v", imbalance_limit_v)
    _validate_limit("temp_warning_c", temp_warning_c)

    df = pd.read_csv(path)
    if df.empty:
        raise ValueError("Battery log contains no data rows")
    if "timestamp_s" not in df.columns:
        raise ValueError("Required column 'timestamp_s' is missing")

    cell_cols, temp_cols = _find_signal_columns(df.columns)
    if not cell_cols:
        raise ValueError("No cell voltage columns found")
    if not temp_cols:
        raise ValueError("No temperature columns found")

    numeric_cols = ["timestamp_s", *cell_cols, *temp_cols]
    numeric = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("Required numeric columns contain missing or non-numeric values")

    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Required numeric columns contain non-finite values")

    timestamps = numeric["timestamp_s"]
    if not timestamps.is_monotonic_increasing:
        raise ValueError("timestamp_s must be non-decreasing")

    cell_max = numeric[cell_cols].max(axis=1)
    cell_min = numeric[cell_cols].min(axis=1)
    delta_v = cell_max - cell_min
    row_max_temp = numeric[temp_cols].max(axis=1)

    violations = _build_imbalance_events(
        numeric,
        timestamps,
        cell_cols,
        delta_v,
        imbalance_limit_v,
    )
    violations.extend(
        _build_temperature_events(
            numeric,
            timestamps,
            temp_cols,
            row_max_temp,
            temp_warning_c,
        )
    )
    violations.sort(key=lambda event: (event["start_time_s"], event["code"]))

    return {
        "rows_analyzed": len(df),
        "cells_detected": len(cell_cols),
        "temperature_sensors_detected": len(temp_cols),
        "max_cell_voltage_v": float(cell_max.max()),
        "min_cell_voltage_v": float(cell_min.min()),
        "max_delta_v": round(float(delta_v.max()), 12),
        "max_temperature_c": float(row_max_temp.max()),
        "violations": violations,
    }
