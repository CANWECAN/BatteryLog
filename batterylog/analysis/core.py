import re
from pathlib import Path

import numpy as np
import pandas as pd

from batterylog.config import ValidationLimits, override_validation_limits
from batterylog.loaders import load_battery_csv
from batterylog.models import AnalysisResult, ViolationEvent

from .rules import build_high_events, build_imbalance_events, build_low_events

CELL_SIGNAL_RE = re.compile(r"^cell_(\d+)_v$")
TEMP_SIGNAL_RE = re.compile(r"^temp_(\d+)_c$")


def _indexed_signal_columns(
    columns: pd.Index,
    pattern: re.Pattern[str],
    kind: str,
) -> list[str]:
    indexed: list[tuple[int, str]] = []
    seen_indexes: dict[int, str] = {}

    for column in columns:
        match = pattern.fullmatch(str(column))
        if match is None:
            continue

        index = int(match.group(1))
        if index in seen_indexes:
            previous = seen_indexes[index]
            raise ValueError(f"Duplicate {kind} signal index {index}: {previous!r} and {column!r}")
        seen_indexes[index] = str(column)
        indexed.append((index, str(column)))

    indexed.sort(key=lambda item: (item[0], item[1]))
    return [column for _, column in indexed]


def _find_signal_columns(columns: pd.Index) -> tuple[list[str], list[str]]:
    cell_cols = _indexed_signal_columns(columns, CELL_SIGNAL_RE, "cell")
    indexed_temp_cols = _indexed_signal_columns(columns, TEMP_SIGNAL_RE, "temperature")

    if "temp_c" in columns and indexed_temp_cols:
        raise ValueError("Legacy temp_c cannot be combined with indexed temp_<n>_c signals")

    temp_cols = ["temp_c"] if "temp_c" in columns else indexed_temp_cols
    return cell_cols, temp_cols


def _resolve_limits(
    limits: ValidationLimits | None,
    imbalance_limit_v: float | None,
    temp_warning_c: float | None,
) -> ValidationLimits:
    resolved = limits or ValidationLimits()
    return override_validation_limits(
        resolved,
        imbalance_max_v=imbalance_limit_v,
        temperature_max_c=temp_warning_c,
    )


def analyze_battery_log(
    path: str | Path,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
) -> AnalysisResult:
    resolved_limits = _resolve_limits(
        limits,
        imbalance_limit_v,
        temp_warning_c,
    )

    df = load_battery_csv(path)
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
    # Normalize subtraction noise so values exactly on a configured boundary
    # are not misclassified by binary floating-point representation.
    delta_v = (cell_max - cell_min).round(12)
    row_max_temp = numeric[temp_cols].max(axis=1)
    row_min_temp = numeric[temp_cols].min(axis=1)

    violations: list[ViolationEvent] = []

    if resolved_limits.imbalance_max_v is not None:
        violations.extend(
            build_imbalance_events(
                numeric,
                timestamps,
                cell_cols,
                delta_v,
                resolved_limits.imbalance_max_v,
            )
        )
    if resolved_limits.cell_max_v is not None:
        violations.extend(
            build_high_events(
                numeric=numeric,
                timestamps=timestamps,
                signal_cols=cell_cols,
                row_max=cell_max,
                limit=resolved_limits.cell_max_v,
                code="CELL_OVERVOLTAGE",
                unit="V",
            )
        )
    if resolved_limits.cell_min_v is not None:
        violations.extend(
            build_low_events(
                numeric=numeric,
                timestamps=timestamps,
                signal_cols=cell_cols,
                row_min=cell_min,
                limit=resolved_limits.cell_min_v,
                code="CELL_UNDERVOLTAGE",
                unit="V",
            )
        )
    if resolved_limits.temperature_max_c is not None:
        violations.extend(
            build_high_events(
                numeric=numeric,
                timestamps=timestamps,
                signal_cols=temp_cols,
                row_max=row_max_temp,
                limit=resolved_limits.temperature_max_c,
                code="TEMPERATURE_HIGH",
                unit="degC",
            )
        )
    if resolved_limits.temperature_min_c is not None:
        violations.extend(
            build_low_events(
                numeric=numeric,
                timestamps=timestamps,
                signal_cols=temp_cols,
                row_min=row_min_temp,
                limit=resolved_limits.temperature_min_c,
                code="TEMPERATURE_LOW",
                unit="degC",
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
        "min_temperature_c": float(row_min_temp.min()),
        "violations": violations,
    }
