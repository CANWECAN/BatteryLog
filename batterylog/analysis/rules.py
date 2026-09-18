from collections.abc import Callable

import numpy as np
import pandas as pd

from batterylog.models import ViolationEvent


def contiguous_true_ranges(mask: pd.Series) -> list[tuple[int, int]]:
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


def build_imbalance_events(
    numeric: pd.DataFrame,
    timestamps: pd.Series,
    cell_cols: list[str],
    delta_v: pd.Series,
    limit_v: float,
) -> list[ViolationEvent]:
    events: list[ViolationEvent] = []

    for start, end in contiguous_true_ranges(delta_v > limit_v):
        segment = delta_v.iloc[start : end + 1]
        peak_pos = start + int(np.argmax(segment.to_numpy()))
        peak_cells = numeric.iloc[peak_pos][cell_cols]
        max_value = float(peak_cells.max())
        min_value = float(peak_cells.min())
        max_signals = [
            str(signal) for signal, value in peak_cells.items() if float(value) == max_value
        ]
        min_signals = [
            str(signal) for signal, value in peak_cells.items() if float(value) == min_value
        ]

        events.append(
            {
                "code": "CELL_IMBALANCE_HIGH",
                "start_time_s": float(timestamps.iloc[start]),
                "end_time_s": float(timestamps.iloc[end]),
                "peak_time_s": float(timestamps.iloc[peak_pos]),
                "measured_value": round(float(delta_v.iloc[peak_pos]), 12),
                "limit_value": limit_v,
                "unit": "V",
                "signals": [*max_signals, *min_signals],
            }
        )

    return events


def _build_extreme_events(
    *,
    numeric: pd.DataFrame,
    timestamps: pd.Series,
    signal_cols: list[str],
    row_extreme: pd.Series,
    limit: float,
    code: str,
    unit: str,
    violates: Callable[[pd.Series, float], pd.Series],
    peak_offset: Callable[[np.ndarray], int],
) -> list[ViolationEvent]:
    events: list[ViolationEvent] = []

    for start, end in contiguous_true_ranges(violates(row_extreme, limit)):
        segment = row_extreme.iloc[start : end + 1]
        peak_pos = start + peak_offset(segment.to_numpy())
        measured = float(row_extreme.iloc[peak_pos])
        peak_signals = numeric.iloc[peak_pos][signal_cols]
        implicated = [
            str(signal) for signal, value in peak_signals.items() if float(value) == measured
        ]

        events.append(
            {
                "code": code,
                "start_time_s": float(timestamps.iloc[start]),
                "end_time_s": float(timestamps.iloc[end]),
                "peak_time_s": float(timestamps.iloc[peak_pos]),
                "measured_value": measured,
                "limit_value": limit,
                "unit": unit,
                "signals": implicated,
            }
        )

    return events


def build_high_events(
    *,
    numeric: pd.DataFrame,
    timestamps: pd.Series,
    signal_cols: list[str],
    row_max: pd.Series,
    limit: float,
    code: str,
    unit: str,
) -> list[ViolationEvent]:
    return _build_extreme_events(
        numeric=numeric,
        timestamps=timestamps,
        signal_cols=signal_cols,
        row_extreme=row_max,
        limit=limit,
        code=code,
        unit=unit,
        violates=lambda values, threshold: values > threshold,
        peak_offset=lambda values: int(np.argmax(values)),
    )


def build_low_events(
    *,
    numeric: pd.DataFrame,
    timestamps: pd.Series,
    signal_cols: list[str],
    row_min: pd.Series,
    limit: float,
    code: str,
    unit: str,
) -> list[ViolationEvent]:
    return _build_extreme_events(
        numeric=numeric,
        timestamps=timestamps,
        signal_cols=signal_cols,
        row_extreme=row_min,
        limit=limit,
        code=code,
        unit=unit,
        violates=lambda values, threshold: values < threshold,
        peak_offset=lambda values: int(np.argmin(values)),
    )
