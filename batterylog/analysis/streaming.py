from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd

from batterylog.config import (
    DataQualityConfig,
    EventDetectionConfig,
    SignalMapping,
    ValidationLimits,
)
from batterylog.loaders import (
    MeasurementLoader,
    measurement_loader_for_file,
    measurement_loader_for_path,
)
from batterylog.models import (
    RESULT_SCHEMA_VERSION,
    AnalysisResult,
    DataQualityEvent,
    RuleCode,
    ViolationEvent,
)
from batterylog.signals import (
    canonicalize_battery_signals,
    find_canonical_pack_signal_columns,
)

from .comparison import below_limit, exceeds_limit, exceeds_limit_scalar
from .core import (
    _active_rule_codes,
    _analysis_options_snapshot,
    _comparison_policy_snapshot,
    _data_quality_snapshot,
    _find_signal_columns,
    _limits_snapshot,
    _pack_current_rule_parameters,
    _raise_invalid_numeric_value,
    _resolve_data_quality,
    _resolve_event_detection,
    _resolve_limits,
    _rule_prefers_lower,
    _signal_mapping_snapshot,
    _warn_legacy_threshold_arguments,
)
from .data_quality import DataQualityCollector
from .report_series import (
    DEFAULT_REPORT_SERIES_MAX_POINTS,
    ReportSeries,
    ReportSeriesCollector,
)
from .rules import (
    build_high_events,
    build_imbalance_events,
    build_low_events,
    contiguous_true_ranges,
)


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
    data_quality: DataQualityConfig | None = None,
    signal_mapping: SignalMapping | None = None,
    report_series_collector: ReportSeriesCollector | None = None,
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
    resolved_data_quality = _resolve_data_quality(data_quality)
    if signal_mapping is not None and not isinstance(signal_mapping, SignalMapping):
        raise TypeError("signal_mapping must be a SignalMapping instance or null")

    rules_evaluated = _active_rule_codes(resolved_limits)
    states: dict[RuleCode, _StreamingRuleState] = {
        code: _StreamingRuleState(prefer_lower=_rule_prefers_lower(code, resolved_limits))
        for code in rules_evaluated
    }

    rows_input = 0
    rows_analyzed = 0
    rows_excluded = 0
    data_quality_collector = (
        DataQualityCollector() if resolved_data_quality.mode == "exclude_invalid_rows" else None
    )
    expected_cell_cols: list[str] | None = None
    expected_temp_cols: list[str] | None = None
    expected_pack_cols: tuple[str | None, str | None] | None = None
    previous_timestamp: float | None = None

    max_cell_voltage_v: float | None = None
    min_cell_voltage_v: float | None = None
    max_delta_v: float | None = None
    max_temperature_c: float | None = None
    min_temperature_c: float | None = None
    max_pack_current_a: float | None = None
    min_pack_current_a: float | None = None
    max_pack_voltage_v: float | None = None
    min_pack_voltage_v: float | None = None

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
        pack_current_col, pack_voltage_col = find_canonical_pack_signal_columns(frame.columns)
        if (
            resolved_limits.pack_charge_max_a is not None
            or resolved_limits.pack_discharge_max_a is not None
        ) and pack_current_col is None:
            raise ValueError("Pack-current validation requires column 'pack_current_a'")
        pack_cols = [
            column for column in (pack_current_col, pack_voltage_col) if column is not None
        ]

        if expected_cell_cols is None:
            expected_cell_cols = cell_cols
            expected_temp_cols = temp_cols
            expected_pack_cols = (pack_current_col, pack_voltage_col)
        elif (
            cell_cols != expected_cell_cols
            or temp_cols != expected_temp_cols
            or (pack_current_col, pack_voltage_col) != expected_pack_cols
        ):
            raise ValueError("Canonical signal columns changed between measurement chunks")

        numeric_cols = ["timestamp_s", *pack_cols, *cell_cols, *temp_cols]
        numeric = frame[numeric_cols].apply(pd.to_numeric, errors="coerce")
        if data_quality_collector is None:
            _raise_invalid_numeric_value(
                frame,
                numeric,
                row_offset=rows_input,
            )
            invalid_rows = pd.Series(False, index=numeric.index, dtype=bool)
        else:
            invalid_values = data_quality_collector.consume_chunk(
                frame,
                numeric,
                row_offset=rows_input,
            )
            invalid_rows = pd.Series(invalid_values, index=numeric.index, dtype=bool)

        rows_input += len(frame)
        chunk_rows_excluded = int(invalid_rows.sum())
        rows_excluded += chunk_rows_excluded
        valid_rows = ~invalid_rows
        valid_numeric = numeric.loc[valid_rows]
        valid_timestamps = valid_numeric["timestamp_s"]

        if not valid_timestamps.is_monotonic_increasing:
            raise ValueError("timestamp_s must be non-decreasing")
        if len(valid_timestamps):
            first_timestamp = float(valid_timestamps.iloc[0])
            if previous_timestamp is not None and first_timestamp < previous_timestamp:
                raise ValueError("timestamp_s must be non-decreasing")
            previous_timestamp = float(valid_timestamps.iloc[-1])

        rule_numeric = pd.DataFrame(
            numeric.to_numpy(dtype=float, na_value=np.nan),
            index=numeric.index,
            columns=numeric.columns,
        )
        if chunk_rows_excluded:
            rule_numeric.loc[
                invalid_rows,
                [*pack_cols, *cell_cols, *temp_cols],
            ] = float("nan")
        timestamps = rule_numeric["timestamp_s"]
        cell_max = rule_numeric[cell_cols].max(axis=1)
        cell_min = rule_numeric[cell_cols].min(axis=1)
        delta_v = cell_max - cell_min
        row_max_temp = rule_numeric[temp_cols].max(axis=1)
        row_min_temp = rule_numeric[temp_cols].min(axis=1)

        valid_cell_max = cell_max.loc[valid_rows]
        valid_cell_min = cell_min.loc[valid_rows]
        valid_delta_v = delta_v.loc[valid_rows]
        valid_row_max_temp = row_max_temp.loc[valid_rows]
        valid_row_min_temp = row_min_temp.loc[valid_rows]

        if report_series_collector is not None and len(valid_numeric):
            report_series_collector.consume_chunk(
                row_offset=rows_analyzed,
                timestamps=valid_timestamps.to_numpy(dtype=float, copy=False),
                cell_min=valid_cell_min.to_numpy(dtype=float, copy=False),
                cell_max=valid_cell_max.to_numpy(dtype=float, copy=False),
                cell_delta=valid_delta_v.to_numpy(dtype=float, copy=False),
                temperature_min=valid_row_min_temp.to_numpy(dtype=float, copy=False),
                temperature_max=valid_row_max_temp.to_numpy(dtype=float, copy=False),
                pack_current=(
                    valid_numeric[pack_current_col].to_numpy(dtype=float, copy=False)
                    if pack_current_col is not None
                    else None
                ),
            )

        if len(valid_numeric):
            chunk_max_cell = float(valid_cell_max.max())
            chunk_min_cell = float(valid_cell_min.min())
            chunk_max_delta = float(valid_delta_v.max())
            chunk_max_temp = float(valid_row_max_temp.max())
            chunk_min_temp = float(valid_row_min_temp.min())

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
            max_delta_v = (
                chunk_max_delta if max_delta_v is None else max(max_delta_v, chunk_max_delta)
            )
            max_temperature_c = (
                chunk_max_temp
                if max_temperature_c is None
                else max(max_temperature_c, chunk_max_temp)
            )
            min_temperature_c = (
                chunk_min_temp
                if min_temperature_c is None
                else min(min_temperature_c, chunk_min_temp)
            )

            if pack_current_col is not None:
                valid_pack_current = valid_numeric[pack_current_col]
                chunk_max_current = float(valid_pack_current.max())
                chunk_min_current = float(valid_pack_current.min())
                max_pack_current_a = (
                    chunk_max_current
                    if max_pack_current_a is None
                    else max(max_pack_current_a, chunk_max_current)
                )
                min_pack_current_a = (
                    chunk_min_current
                    if min_pack_current_a is None
                    else min(min_pack_current_a, chunk_min_current)
                )

            if pack_voltage_col is not None:
                valid_pack_voltage = valid_numeric[pack_voltage_col]
                chunk_max_voltage = float(valid_pack_voltage.max())
                chunk_min_voltage = float(valid_pack_voltage.min())
                max_pack_voltage_v = (
                    chunk_max_voltage
                    if max_pack_voltage_v is None
                    else max(max_pack_voltage_v, chunk_max_voltage)
                )
                min_pack_voltage_v = (
                    chunk_min_voltage
                    if min_pack_voltage_v is None
                    else min(min_pack_voltage_v, chunk_min_voltage)
                )

        max_gap_s = resolved_event_detection.max_gap_s

        if resolved_limits.imbalance_max_v is not None:
            limit = resolved_limits.imbalance_max_v
            _consume_streaming_rule(
                states["CELL_IMBALANCE_HIGH"],
                mask=exceeds_limit(delta_v, limit),
                events=build_imbalance_events(
                    rule_numeric,
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
                    numeric=rule_numeric,
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
                    numeric=rule_numeric,
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
                    numeric=rule_numeric,
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
                    numeric=rule_numeric,
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

        if pack_current_col is not None:
            pack_current = rule_numeric[pack_current_col]
            for direction, code in (
                ("charge", "PACK_CHARGE_OVERCURRENT"),
                ("discharge", "PACK_DISCHARGE_OVERCURRENT"),
            ):
                parameters = _pack_current_rule_parameters(resolved_limits, direction)
                if parameters is None:
                    continue
                signed_limit, prefer_lower = parameters
                if prefer_lower:
                    mask = below_limit(pack_current, signed_limit)
                    events = build_low_events(
                        numeric=rule_numeric,
                        timestamps=timestamps,
                        signal_cols=[pack_current_col],
                        row_min=pack_current,
                        limit=signed_limit,
                        code=code,
                        unit="A",
                        max_gap_s=max_gap_s,
                    )
                else:
                    mask = exceeds_limit(pack_current, signed_limit)
                    events = build_high_events(
                        numeric=rule_numeric,
                        timestamps=timestamps,
                        signal_cols=[pack_current_col],
                        row_max=pack_current,
                        limit=signed_limit,
                        code=code,
                        unit="A",
                        max_gap_s=max_gap_s,
                    )
                _consume_streaming_rule(
                    states[code],
                    mask=mask,
                    events=events,
                    timestamps=timestamps,
                    max_gap_s=max_gap_s,
                )

        rows_analyzed += len(valid_numeric)

    if rows_input == 0:
        raise ValueError("Battery log contains no data rows")

    assert expected_cell_cols is not None
    assert expected_temp_cols is not None
    assert expected_pack_cols is not None
    if rows_analyzed:
        assert max_cell_voltage_v is not None
        assert min_cell_voltage_v is not None
        assert max_delta_v is not None
        assert max_temperature_c is not None
        assert min_temperature_c is not None
        if expected_pack_cols[0] is not None:
            assert max_pack_current_a is not None
            assert min_pack_current_a is not None
        if expected_pack_cols[1] is not None:
            assert max_pack_voltage_v is not None
            assert min_pack_voltage_v is not None

    data_quality_events: list[DataQualityEvent] = (
        data_quality_collector.finish() if data_quality_collector is not None else []
    )
    violations = [event for code in rules_evaluated for event in states[code].finish()]
    violations.sort(key=lambda event: (event["start_time_s"], event["code"]))

    if violations or data_quality_events:
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
        "signal_mapping": _signal_mapping_snapshot(
            signal_mapping,
            pack_current_detected=expected_pack_cols[0] is not None,
            pack_voltage_detected=expected_pack_cols[1] is not None,
        ),
        "data_quality": _data_quality_snapshot(resolved_data_quality, data_quality_events),
        "rows_input": rows_input,
        "rows_analyzed": rows_analyzed,
        "rows_excluded": rows_excluded,
        "cells_detected": len(expected_cell_cols),
        "temperature_sensors_detected": len(expected_temp_cols),
        "max_cell_voltage_v": max_cell_voltage_v,
        "min_cell_voltage_v": min_cell_voltage_v,
        "max_delta_v": round(max_delta_v, 12) if max_delta_v is not None else None,
        "max_temperature_c": max_temperature_c,
        "min_temperature_c": min_temperature_c,
        "max_pack_current_a": max_pack_current_a,
        "min_pack_current_a": min_pack_current_a,
        "max_pack_voltage_v": max_pack_voltage_v,
        "min_pack_voltage_v": min_pack_voltage_v,
        "violations": violations,
    }


def analyze_measurement_loader(
    loader: MeasurementLoader,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    data_quality: DataQualityConfig | None = None,
    signal_mapping: SignalMapping | None = None,
) -> AnalysisResult:
    return _analyze_battery_chunks(
        loader.iter_chunks(signal_mapping=signal_mapping),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
    )


def analyze_measurement_loader_with_report_series(
    loader: MeasurementLoader,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    data_quality: DataQualityConfig | None = None,
    signal_mapping: SignalMapping | None = None,
    max_points: int = DEFAULT_REPORT_SERIES_MAX_POINTS,
) -> tuple[AnalysisResult, ReportSeries]:
    collector = ReportSeriesCollector(max_points=max_points)
    result = _analyze_battery_chunks(
        loader.iter_chunks(signal_mapping=signal_mapping),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
        report_series_collector=collector,
    )
    return result, collector.finish()


def analyze_battery_log_streaming(
    path: str | Path,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    data_quality: DataQualityConfig | None = None,
    signal_mapping: SignalMapping | None = None,
) -> AnalysisResult:
    return analyze_measurement_loader(
        measurement_loader_for_path(path),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
    )


def analyze_battery_file_streaming(
    handle: BinaryIO,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    source_name: str | Path | None = None,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    data_quality: DataQualityConfig | None = None,
    signal_mapping: SignalMapping | None = None,
) -> AnalysisResult:
    return analyze_measurement_loader(
        measurement_loader_for_file(handle, source_name=source_name),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
    )


def analyze_battery_file_with_report_series(
    handle: BinaryIO,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    source_name: str | Path | None = None,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    data_quality: DataQualityConfig | None = None,
    signal_mapping: SignalMapping | None = None,
    max_points: int = DEFAULT_REPORT_SERIES_MAX_POINTS,
) -> tuple[AnalysisResult, ReportSeries]:
    return analyze_measurement_loader_with_report_series(
        measurement_loader_for_file(handle, source_name=source_name),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
        max_points=max_points,
    )
