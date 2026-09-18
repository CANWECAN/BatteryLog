from pathlib import Path

import numpy as np
import pandas as pd

from batterylog.config import ValidationLimits, override_validation_limits
from batterylog.models import AnalysisResult, ViolationEvent

from .rules import build_high_events, build_imbalance_events, build_low_events


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
