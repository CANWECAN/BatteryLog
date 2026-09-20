from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from batterylog.config import EventDetectionConfig, SignalMapping, ValidationLimits
from batterylog.loaders import iter_battery_csv, iter_battery_csv_file
from batterylog.models import RESULT_SCHEMA_VERSION, AnalysisResult, RuleCode, ViolationEvent
from batterylog.signals import canonicalize_battery_signals

from .comparison import below_limit, exceeds_limit, exceeds_limit_scalar
from .core import (
    _active_rule_codes,
    _analysis_options_snapshot,
    _comparison_policy_snapshot,
    _find_signal_columns,
    _limits_snapshot,
    _raise_invalid_numeric_value,
    _resolve_event_detection,
    _resolve_limits,
    _signal_mapping_snapshot,
    _warn_legacy_threshold_arguments,
)
from .rules import (
    build_high_events,
    build_imbalance_events,
    build_low_events,
    contiguous_true_ranges,
)

DEFAULT_CSV_CHUNK_ROWS = 50_000


def _merge_streaming_events(
    previous: ViolationEvent,
    current: ViolationEvent,
    *,
    prefer_lower: bool,
) -> ViolationEvent:
    previous_value = previous["measured_value"]
    current_value = current["measured_value"]
    current_is_more_severe = (
        current_value < previous_value if prefer_lower else current_value > previous_value
    )

    merged: ViolationEvent = {
        **previous,
        "end_time_s": current["end_time_s"],
    }
    if current_is_more_severe:
        merged["peak_time_s"] = current["peak_time_s"]
        merged["measured_value"] = current_value
        merged["signals"] = current["signals"]

    return merged


@dataclass
class _StreamingRuleState:
    prefer_lower: bool
    completed: list[ViolationEvent] = field(default_factory=list)
    pending: ViolationEvent | None = None
    last_active_time_s: float | None = None

    def consume(
        self,
        *,
        ranges: list[tuple[int, int]],
        events: list[ViolationEvent],
        timestamps: pd.Series,
        max_gap_s: float | None,
    ) -> None:
        if len(ranges) != len(events):
            raise RuntimeError("Streaming event/range count mismatch")
        if len(timestamps) == 0:
            return

        timestamp_values = timestamps.to_numpy(dtype=float, copy=False)
        chunk_events = list(events)

        if self.pending is not None:
            joins_previous = bool(ranges and ranges[0][0] == 0)
            if joins_previous and max_gap_s is not None and self.last_active_time_s is not None:
                gap_s = float(timestamp_values[0] - self.last_active_time_s)
                joins_previous = not exceeds_limit_scalar(gap_s, max_gap_s)

            if joins_previous:
                chunk_events[0] = _merge_streaming_events(
                    self.pending,
                    chunk_events[0],
                    prefer_lower=self.prefer_lower,
                )
            else:
                self.completed.append(self.pending)

            self.pending = None
            self.last_active_time_s = None

        last_position = len(timestamps) - 1
        for (_, end), event in zip(ranges, chunk_events, strict=True):
            if end == last_position:
                self.pending = event
                self.last_active_time_s = float(timestamp_values[end])
            else:
                self.completed.append(event)

    def finish(self) -> list[ViolationEvent]:
        if self.pending is not None:
            self.completed.append(self.pending)
            self.pending = None
            self.last_active_time_s = None
        return self.completed


def _consume_streaming_rule(
    state: _StreamingRuleState,
    *,
    mask: pd.Series,
    events: list[ViolationEvent],
    timestamps: pd.Series,
    max_gap_s: float | None,
) -> None:
    ranges = contiguous_true_ranges(
        mask,
        timestamps=timestamps,
        max_gap_s=max_gap_s,
    )
    state.consume(
        ranges=ranges,
        events=events,
        timestamps=timestamps,
        max_gap_s=max_gap_s,
    )


def _analyze_battery_chunks(
    chunks: Iterable[pd.DataFrame],
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    signal_mapping: SignalMapping | None = None,
) -> AnalysisResult:
    _warn_legacy_threshold_arguments(
        imbalance_limit_v,
        temp_warning_c,
    )
    resolved_limits = _resolve_limits(
        limits,
        imbalance_limit_v,
        temp_warning_c,
    )
    resolved_event_detection = _resolve_event_detection(event_detection)
    if signal_mapping is not None and not isinstance(signal_mapping, SignalMapping):
        raise TypeError("signal_mapping must be a SignalMapping instance or null")

    rules_evaluated = _active_rule_codes(resolved_limits)
    states: dict[RuleCode, _StreamingRuleState] = {
        code: _StreamingRuleState(prefer_lower=code in {"CELL_UNDERVOLTAGE", "TEMPERATURE_LOW"})
        for code in rules_evaluated
    }

    rows_analyzed = 0
    expected_cell_cols: list[str] | None = None
    expected_temp_cols: list[str] | None = None
    previous_timestamp: float | None = None

    max_cell_voltage_v: float | None = None
    min_cell_voltage_v: float | None = None
    max_delta_v: float | None = None
    max_temperature_c: float | None = None
    min_temperature_c: float | None = None

    for frame in chunks:
        if frame.empty:
            continue

        frame = canonicalize_battery_signals(frame, signal_mapping)
        if "timestamp_s" not in frame.columns:
            raise ValueError("Required column 'timestamp_s' is missing")

        cell_cols, temp_cols = _find_signal_columns(frame.columns)
        if not cell_cols:
            raise ValueError("No cell voltage columns found")
        if not temp_cols:
            raise ValueError("No temperature columns found")

        if expected_cell_cols is None:
            expected_cell_cols = cell_cols
            expected_temp_cols = temp_cols
        elif cell_cols != expected_cell_cols or temp_cols != expected_temp_cols:
            raise ValueError("Canonical signal columns changed between CSV chunks")

        numeric_cols = ["timestamp_s", *cell_cols, *temp_cols]
        numeric = frame[numeric_cols].apply(pd.to_numeric, errors="coerce")
        _raise_invalid_numeric_value(
            frame,
            numeric,
            row_offset=rows_analyzed,
        )

        timestamps = numeric["timestamp_s"]
        if not timestamps.is_monotonic_increasing:
            raise ValueError("timestamp_s must be non-decreasing")
        first_timestamp = float(timestamps.iloc[0])
        if previous_timestamp is not None and first_timestamp < previous_timestamp:
            raise ValueError("timestamp_s must be non-decreasing")
        previous_timestamp = float(timestamps.iloc[-1])

        cell_max = numeric[cell_cols].max(axis=1)
        cell_min = numeric[cell_cols].min(axis=1)
        delta_v = cell_max - cell_min
        row_max_temp = numeric[temp_cols].max(axis=1)
        row_min_temp = numeric[temp_cols].min(axis=1)

        chunk_max_cell = float(cell_max.max())
        chunk_min_cell = float(cell_min.min())
        chunk_max_delta = float(delta_v.max())
        chunk_max_temp = float(row_max_temp.max())
        chunk_min_temp = float(row_min_temp.min())

        max_cell_voltage_v = (
            chunk_max_cell
            if max_cell_voltage_v is None
            else max(max_cell_voltage_v, chunk_max_cell)
        )
        min_cell_voltage_v = (
            chunk_min_cell
            if min_cell_voltage_v is None
            else min(min_cell_voltage_v, chunk_min_cell)
        )
        max_delta_v = chunk_max_delta if max_delta_v is None else max(max_delta_v, chunk_max_delta)
        max_temperature_c = (
            chunk_max_temp if max_temperature_c is None else max(max_temperature_c, chunk_max_temp)
        )
        min_temperature_c = (
            chunk_min_temp if min_temperature_c is None else min(min_temperature_c, chunk_min_temp)
        )

        max_gap_s = resolved_event_detection.max_gap_s

        if resolved_limits.imbalance_max_v is not None:
            limit = resolved_limits.imbalance_max_v
            _consume_streaming_rule(
                states["CELL_IMBALANCE_HIGH"],
                mask=exceeds_limit(delta_v, limit),
                events=build_imbalance_events(
                    numeric,
                    timestamps,
                    cell_cols,
                    delta_v,
                    limit,
                    max_gap_s=max_gap_s,
                ),
                timestamps=timestamps,
                max_gap_s=max_gap_s,
            )

        if resolved_limits.cell_max_v is not None:
            limit = resolved_limits.cell_max_v
            _consume_streaming_rule(
                states["CELL_OVERVOLTAGE"],
                mask=exceeds_limit(cell_max, limit),
                events=build_high_events(
                    numeric=numeric,
                    timestamps=timestamps,
                    signal_cols=cell_cols,
                    row_max=cell_max,
                    limit=limit,
                    code="CELL_OVERVOLTAGE",
                    unit="V",
                    max_gap_s=max_gap_s,
                ),
                timestamps=timestamps,
                max_gap_s=max_gap_s,
            )

        if resolved_limits.cell_min_v is not None:
            limit = resolved_limits.cell_min_v
            _consume_streaming_rule(
                states["CELL_UNDERVOLTAGE"],
                mask=below_limit(cell_min, limit),
                events=build_low_events(
                    numeric=numeric,
                    timestamps=timestamps,
                    signal_cols=cell_cols,
                    row_min=cell_min,
                    limit=limit,
                    code="CELL_UNDERVOLTAGE",
                    unit="V",
                    max_gap_s=max_gap_s,
                ),
                timestamps=timestamps,
                max_gap_s=max_gap_s,
            )

        if resolved_limits.temperature_max_c is not None:
            limit = resolved_limits.temperature_max_c
            _consume_streaming_rule(
                states["TEMPERATURE_HIGH"],
                mask=exceeds_limit(row_max_temp, limit),
                events=build_high_events(
                    numeric=numeric,
                    timestamps=timestamps,
                    signal_cols=temp_cols,
                    row_max=row_max_temp,
                    limit=limit,
                    code="TEMPERATURE_HIGH",
                    unit="degC",
                    max_gap_s=max_gap_s,
                ),
                timestamps=timestamps,
                max_gap_s=max_gap_s,
            )

        if resolved_limits.temperature_min_c is not None:
            limit = resolved_limits.temperature_min_c
            _consume_streaming_rule(
                states["TEMPERATURE_LOW"],
                mask=below_limit(row_min_temp, limit),
                events=build_low_events(
                    numeric=numeric,
                    timestamps=timestamps,
                    signal_cols=temp_cols,
                    row_min=row_min_temp,
                    limit=limit,
                    code="TEMPERATURE_LOW",
                    unit="degC",
                    max_gap_s=max_gap_s,
                ),
                timestamps=timestamps,
                max_gap_s=max_gap_s,
            )

        rows_analyzed += len(frame)

    if rows_analyzed == 0:
        raise ValueError("Battery log contains no data rows")

    assert expected_cell_cols is not None
    assert expected_temp_cols is not None
    assert max_cell_voltage_v is not None
    assert min_cell_voltage_v is not None
    assert max_delta_v is not None
    assert max_temperature_c is not None
    assert min_temperature_c is not None

    violations = [event for code in rules_evaluated for event in states[code].finish()]
    violations.sort(key=lambda event: (event["start_time_s"], event["code"]))

    if violations:
        validation_status = "FAIL"
    elif rules_evaluated:
        validation_status = "PASS"
    else:
        validation_status = "NOT_EVALUATED"

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "validation_status": validation_status,
        "rules_evaluated": rules_evaluated,
        "limits_applied": _limits_snapshot(resolved_limits),
        "analysis_options": _analysis_options_snapshot(resolved_event_detection),
        "comparison_policy": _comparison_policy_snapshot(),
        "signal_mapping": _signal_mapping_snapshot(signal_mapping),
        "rows_analyzed": rows_analyzed,
        "cells_detected": len(expected_cell_cols),
        "temperature_sensors_detected": len(expected_temp_cols),
        "max_cell_voltage_v": max_cell_voltage_v,
        "min_cell_voltage_v": min_cell_voltage_v,
        "max_delta_v": round(max_delta_v, 12),
        "max_temperature_c": max_temperature_c,
        "min_temperature_c": min_temperature_c,
        "violations": violations,
    }


def analyze_battery_log_streaming(
    path: str | Path,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    signal_mapping: SignalMapping | None = None,
) -> AnalysisResult:
    return _analyze_battery_chunks(
        iter_battery_csv(path, chunk_rows=DEFAULT_CSV_CHUNK_ROWS),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        signal_mapping=signal_mapping,
    )


def analyze_battery_file_streaming(
    handle: BinaryIO,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    signal_mapping: SignalMapping | None = None,
) -> AnalysisResult:
    return _analyze_battery_chunks(
        iter_battery_csv_file(handle, chunk_rows=DEFAULT_CSV_CHUNK_ROWS),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        signal_mapping=signal_mapping,
    )
