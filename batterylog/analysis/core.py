from math import isfinite
from pathlib import Path
from typing import TypedDict

import numpy as np
import pandas as pd


class AnalysisResult(TypedDict):
    rows_analyzed: int
    cells_detected: int
    max_cell_voltage_v: float
    min_cell_voltage_v: float
    max_delta_v: float
    max_temperature_c: float
    violations: list[str]


def _validate_limit(name: str, value: float) -> None:
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite, non-negative number")


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
    if "temp_c" not in df.columns:
        raise ValueError("Required column 'temp_c' is missing")

    cell_cols = sorted(
        (c for c in df.columns if c.startswith("cell_") and c.endswith("_v")),
        key=str.casefold,
    )
    if not cell_cols:
        raise ValueError("No cell voltage columns found")

    sensor_cols = [*cell_cols, "temp_c"]
    numeric = df[sensor_cols].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("Sensor columns contain missing or non-numeric values")

    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Sensor columns contain non-finite values")

    cell_max = numeric[cell_cols].max(axis=1)
    cell_min = numeric[cell_cols].min(axis=1)
    max_delta = float((cell_max - cell_min).max())
    max_temp = float(numeric["temp_c"].max())

    violations: list[str] = []
    if max_delta > imbalance_limit_v:
        violations.append("CELL_IMBALANCE_HIGH")
    if max_temp > temp_warning_c:
        violations.append("TEMPERATURE_WARNING")

    return {
        "rows_analyzed": len(df),
        "cells_detected": len(cell_cols),
        "max_cell_voltage_v": float(numeric[cell_cols].max().max()),
        "min_cell_voltage_v": float(numeric[cell_cols].min().min()),
        "max_delta_v": round(max_delta, 12),
        "max_temperature_c": max_temp,
        "violations": violations,
    }
