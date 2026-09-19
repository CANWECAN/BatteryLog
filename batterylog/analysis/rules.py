from collections.abc import Callable

import numpy as np
import pandas as pd

from batterylog.models import RuleCode, ViolationEvent

from .comparison import below_limit, exceeds_limit, exceeds_limit_scalar


def contiguous_true_ranges(
    mask: pd.Series,
    *,
    timestamps: pd.Series | None = None,
    max_gap_s: float | None = None,
) -> list[tuple[int, int]]:
    if max_gap_s is not None:
        if timestamps is None:
            raise ValueError("timestamps are required when max_gap_s is configured")
        if len(timestamps) != len(mask):
            raise ValueError("timestamps and mask must have the same length")

    ranges: list[tuple[int, int]] = []
    start: int | None = None
    previous_active_position: int | None = None
    timestamp_values = (
        timestamps.to_numpy(dtype=float, copy=False) if timestamps is not None else None
    )

    for position, active in enumerate(mask.to_numpy(dtype=bool)):
        if active:
            if start is None:
                start = position
            elif max_gap_s is not None and previous_active_position is not None:
                assert timestamp_values is not None
                gap_s = float(
                    timestamp_values[position] - timestamp_values[previous_active_position]
                )
                if exceeds_limit_scalar(gap_s, max_gap_s):
                    ranges.append((start, position - 1))
                    start = position

            previous_active_position = position
        elif start is not None:
            ranges.append((start, position - 1))
            start = None
            previous_active_position = None

    if start is not None:
        ranges.append((start, len(mask) - 1))

    return ranges


def build_imbalance_events(
    numeric: pd.DataFrame,
    timestamps: pd.Series,
    cell_cols: list[str],
    delta_v: pd.Series,
    limit_v: float,
    *,
    max_gap_s: float | None = None,
) -> list[ViolationEvent]:
    events: list[ViolationEvent] = []
    cell_values = numeric.loc[:, cell_cols].to_numpy(dtype=float, copy=False)
    delta_values = delta_v.to_numpy(dtype=float, copy=False)
    timestamp_values = timestamps.to_numpy(dtype=float, copy=False)

    for start, end in contiguous_true_ranges(
        exceeds_limit(delta_v, limit_v),
        timestamps=timestamps,
        max_gap_s=max_gap_s,
    ):
        segment = delta_values[start : end + 1]
        peak_pos = start + int(np.argmax(segment))
        peak_cells = cell_values[peak_pos]
        max_value = float(np.max(peak_cells))
        min_value = float(np.min(peak_cells))
        max_signals = [cell_cols[index] for index in np.flatnonzero(peak_cells == max_value)]
        min_signals = [cell_cols[index] for index in np.flatnonzero(peak_cells == min_value)]

        events.append(
            {
                "code": "CELL_IMBALANCE_HIGH",
                "start_time_s": float(timestamp_values[start]),
                "end_time_s": float(timestamp_values[end]),
                "peak_time_s": float(timestamp_values[peak_pos]),
                "measured_value": round(float(delta_values[peak_pos]), 12),
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
    code: RuleCode,
    unit: str,
    violates: Callable[[pd.Series, float], pd.Series],
    peak_offset: Callable[[np.ndarray], int],
    max_gap_s: float | None = None,
) -> list[ViolationEvent]:
    events: list[ViolationEvent] = []
    signal_values = numeric.loc[:, signal_cols].to_numpy(dtype=float, copy=False)
    extreme_values = row_extreme.to_numpy(dtype=float, copy=False)
    timestamp_values = timestamps.to_numpy(dtype=float, copy=False)

    for start, end in contiguous_true_ranges(
        violates(row_extreme, limit),
        timestamps=timestamps,
        max_gap_s=max_gap_s,
    ):
        segment = extreme_values[start : end + 1]
        peak_pos = start + peak_offset(segment)
        measured = float(extreme_values[peak_pos])
        peak_signals = signal_values[peak_pos]
        implicated = [signal_cols[index] for index in np.flatnonzero(peak_signals == measured)]

        events.append(
            {
                "code": code,
                "start_time_s": float(timestamp_values[start]),
                "end_time_s": float(timestamp_values[end]),
                "peak_time_s": float(timestamp_values[peak_pos]),
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
    code: RuleCode,
    unit: str,
    max_gap_s: float | None = None,
) -> list[ViolationEvent]:
    return _build_extreme_events(
        numeric=numeric,
        timestamps=timestamps,
        signal_cols=signal_cols,
        row_extreme=row_max,
        limit=limit,
        code=code,
        unit=unit,
        violates=exceeds_limit,
        peak_offset=lambda values: int(np.argmax(values)),
        max_gap_s=max_gap_s,
    )


def build_low_events(
    *,
    numeric: pd.DataFrame,
    timestamps: pd.Series,
    signal_cols: list[str],
    row_min: pd.Series,
    limit: float,
    code: RuleCode,
    unit: str,
    max_gap_s: float | None = None,
) -> list[ViolationEvent]:
    return _build_extreme_events(
        numeric=numeric,
        timestamps=timestamps,
        signal_cols=signal_cols,
        row_extreme=row_min,
        limit=limit,
        code=code,
        unit=unit,
        violates=below_limit,
        peak_offset=lambda values: int(np.argmin(values)),
        max_gap_s=max_gap_s,
    )
