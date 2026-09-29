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
    AnalysisResult,
    DataQualityEvent,
    RuleCode,
    ViolationEvent,
)

from .comparison import exceeds_limit_scalar
from .configuration import (
    resolve_data_quality,
    resolve_event_detection,
    resolve_limits,
    validate_signal_mapping,
    warn_legacy_threshold_arguments,
)
from .data_quality import DataQualityCollector
from .evaluation import active_rule_codes, evaluate_rules, rule_prefers_lower
from .input_validation import (
    SignalLayout,
    canonicalize_analysis_frame,
    raise_invalid_numeric_value,
    valid_timestamp_values,
)
from .preparation import prepare_measurements
from .report_series import (
    DEFAULT_REPORT_SERIES_MAX_POINTS,
    ReportSeries,
    ReportSeriesCollector,
)
from .result_assembly import build_analysis_result
from .rules import contiguous_true_ranges
from .summary import (
    MeasurementSummary,
    analysis_metrics_from_summary,
    merge_measurement_summaries,
    summarize_prepared_measurements,
)


def _merge_streaming_events(
    previous: ViolationEvent,
    current: ViolationEvent,
    *,
    prefer_lower: bool,
    previous_peak_value: float | None = None,
    current_peak_value: float | None = None,
) -> tuple[ViolationEvent, float]:
    previous_comparison_value = (
        previous["measured_value"] if previous_peak_value is None else previous_peak_value
    )
    current_comparison_value = (
        current["measured_value"] if current_peak_value is None else current_peak_value
    )
    current_is_more_severe = (
        current_comparison_value < previous_comparison_value
        if prefer_lower
        else current_comparison_value > previous_comparison_value
    )

    merged: ViolationEvent = {
        **previous,
        "end_time_s": current["end_time_s"],
        "sample_count": previous["sample_count"] + current["sample_count"],
        "duration_s": round(current["end_time_s"] - previous["start_time_s"], 12),
    }
    if current_is_more_severe:
        merged["peak_time_s"] = current["peak_time_s"]
        merged["measured_value"] = current["measured_value"]
        merged["peak_excursion"] = current["peak_excursion"]
        merged["signals"] = current["signals"]
        if current["code"] == "PACK_VOLTAGE_CELL_SUM_MISMATCH":
            merged["pack_voltage_v"] = current["pack_voltage_v"]
            merged["cell_voltage_sum_v"] = current["cell_voltage_sum_v"]
            merged["signed_error_v"] = current["signed_error_v"]

    merged_peak_value = (
        current_comparison_value if current_is_more_severe else previous_comparison_value
    )
    return merged, merged_peak_value


@dataclass
class _StreamingRuleState:
    prefer_lower: bool
    completed: list[ViolationEvent] = field(default_factory=list)
    pending: ViolationEvent | None = None
    pending_peak_value: float | None = None
    last_active_time_s: float | None = None

    def consume(
        self,
        *,
        ranges: list[tuple[int, int]],
        events: list[ViolationEvent],
        timestamps: pd.Series,
        max_gap_s: float | None,
        peak_values: pd.Series | None = None,
    ) -> None:
        if len(ranges) != len(events):
            raise RuntimeError("Streaming event/range count mismatch")
        if peak_values is not None and len(peak_values) != len(timestamps):
            raise RuntimeError("Streaming peak/timestamp count mismatch")
        if len(timestamps) == 0:
            return

        timestamp_values = timestamps.to_numpy(dtype=float, copy=False)
        chunk_events = list(events)
        if peak_values is None:
            chunk_peak_values = [event["measured_value"] for event in events]
        else:
            raw_peak_values = peak_values.to_numpy(dtype=float, copy=False)
            chunk_peak_values = [
                float(
                    np.min(raw_peak_values[start : end + 1])
                    if self.prefer_lower
                    else np.max(raw_peak_values[start : end + 1])
                )
                for start, end in ranges
            ]

        if self.pending is not None:
            joins_previous = bool(ranges and ranges[0][0] == 0)
            if joins_previous and max_gap_s is not None and self.last_active_time_s is not None:
                gap_s = float(timestamp_values[0] - self.last_active_time_s)
                joins_previous = not exceeds_limit_scalar(gap_s, max_gap_s)

            if joins_previous:
                previous_peak_value = (
                    self.pending["measured_value"]
                    if self.pending_peak_value is None
                    else self.pending_peak_value
                )
                chunk_events[0], chunk_peak_values[0] = _merge_streaming_events(
                    self.pending,
                    chunk_events[0],
                    prefer_lower=self.prefer_lower,
                    previous_peak_value=previous_peak_value,
                    current_peak_value=chunk_peak_values[0],
                )
            else:
                self.completed.append(self.pending)

            self.pending = None
            self.pending_peak_value = None
            self.last_active_time_s = None

        last_position = len(timestamps) - 1
        for (_, end), event, peak_value in zip(
            ranges,
            chunk_events,
            chunk_peak_values,
            strict=True,
        ):
            if end == last_position:
                self.pending = event
                self.pending_peak_value = peak_value
                self.last_active_time_s = float(timestamp_values[end])
            else:
                self.completed.append(event)

    def finish(self) -> list[ViolationEvent]:
        if self.pending is not None:
            self.completed.append(self.pending)
            self.pending = None
            self.pending_peak_value = None
            self.last_active_time_s = None
        return self.completed


def _consume_streaming_rule(
    state: _StreamingRuleState,
    *,
    mask: pd.Series,
    events: list[ViolationEvent],
    timestamps: pd.Series,
    max_gap_s: float | None,
    peak_values: pd.Series | None = None,
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
        peak_values=peak_values,
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
    warn_legacy_threshold_arguments(
        imbalance_limit_v,
        temp_warning_c,
    )
    resolved_limits = resolve_limits(
        limits,
        imbalance_limit_v,
        temp_warning_c,
    )
    resolved_event_detection = resolve_event_detection(event_detection)
    resolved_data_quality = resolve_data_quality(data_quality)
    validate_signal_mapping(signal_mapping)

    rules_evaluated = active_rule_codes(resolved_limits)
    states: dict[RuleCode, _StreamingRuleState] = {
        code: _StreamingRuleState(prefer_lower=rule_prefers_lower(code, resolved_limits))
        for code in rules_evaluated
    }

    rows_input = 0
    rows_analyzed = 0
    rows_excluded = 0
    data_quality_collector = (
        DataQualityCollector() if resolved_data_quality.mode == "exclude_invalid_rows" else None
    )
    expected_layout: SignalLayout | None = None
    previous_timestamp: float | None = None

    measurement_summary = MeasurementSummary()

    for frame in chunks:
        if frame.empty:
            continue

        frame, layout = canonicalize_analysis_frame(frame, signal_mapping, resolved_limits)
        cell_cols = layout.cell_cols
        temp_cols = layout.temp_cols
        pack_current_col = layout.pack_current_col
        pack_voltage_col = layout.pack_voltage_col
        pack_cols = layout.pack_cols

        if expected_layout is None:
            expected_layout = layout
        elif layout != expected_layout:
            raise ValueError("Canonical signal columns changed between measurement chunks")

        chunk_row_offset = rows_input
        numeric = frame[layout.numeric_cols].apply(pd.to_numeric, errors="coerce")
        if data_quality_collector is None:
            raise_invalid_numeric_value(
                frame,
                numeric,
                row_offset=chunk_row_offset,
            )
            invalid_rows = pd.Series(False, index=numeric.index, dtype=bool)
        else:
            invalid_values = data_quality_collector.consume_chunk(
                frame,
                numeric,
                row_offset=chunk_row_offset,
            )
            invalid_rows = pd.Series(invalid_values, index=numeric.index, dtype=bool)

        ordering_timestamps = valid_timestamp_values(frame, numeric)
        if not ordering_timestamps.is_monotonic_increasing:
            raise ValueError("timestamp_s must be non-decreasing")
        if len(ordering_timestamps):
            first_timestamp = float(ordering_timestamps.iloc[0])
            if previous_timestamp is not None and first_timestamp < previous_timestamp:
                raise ValueError("timestamp_s must be non-decreasing")
            previous_timestamp = float(ordering_timestamps.iloc[-1])

        rows_input += len(frame)
        chunk_rows_excluded = int(invalid_rows.sum())
        rows_excluded += chunk_rows_excluded
        prepared = prepare_measurements(
            numeric,
            invalid_rows,
            pack_cols=pack_cols,
            cell_cols=cell_cols,
            temp_cols=temp_cols,
            pack_current_col=pack_current_col,
            pack_voltage_col=pack_voltage_col,
            row_offset=chunk_row_offset,
        )
        valid_rows = prepared.valid_rows
        valid_numeric = prepared.valid_numeric
        rule_inputs = prepared.rule_inputs
        timestamps = rule_inputs.timestamps
        cell_max = rule_inputs.cell_max
        cell_min = rule_inputs.cell_min
        delta_v = rule_inputs.delta_v
        row_max_temp = rule_inputs.temperature_max
        row_min_temp = rule_inputs.temperature_min
        cell_sum = rule_inputs.cell_sum
        valid_timestamps = valid_numeric["timestamp_s"]

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
                pack_voltage=(
                    valid_numeric[pack_voltage_col].to_numpy(dtype=float, copy=False)
                    if pack_voltage_col is not None
                    else None
                ),
                cell_sum=(
                    cell_sum.loc[valid_rows].to_numpy(dtype=float, copy=False)
                    if cell_sum is not None
                    else None
                ),
            )

        measurement_summary = merge_measurement_summaries(
            measurement_summary,
            summarize_prepared_measurements(prepared),
        )

        max_gap_s = resolved_event_detection.max_gap_s
        for evaluation in evaluate_rules(
            rule_inputs,
            resolved_limits,
            max_gap_s=max_gap_s,
        ):
            _consume_streaming_rule(
                states[evaluation.code],
                mask=evaluation.mask,
                events=evaluation.events,
                timestamps=timestamps,
                max_gap_s=max_gap_s,
                peak_values=evaluation.peak_values,
            )

        rows_analyzed += len(valid_numeric)

    if rows_input == 0:
        raise ValueError("Battery log contains no data rows")

    assert expected_layout is not None

    data_quality_events: list[DataQualityEvent] = (
        data_quality_collector.finish() if data_quality_collector is not None else []
    )
    violations = [event for code in rules_evaluated for event in states[code].finish()]
    violations.sort(key=lambda event: (event["start_time_s"], event["code"]))

    return build_analysis_result(
        limits=resolved_limits,
        event_detection=resolved_event_detection,
        data_quality=resolved_data_quality,
        signal_mapping=signal_mapping,
        rules_evaluated=rules_evaluated,
        data_quality_events=data_quality_events,
        violations=violations,
        rows_input=rows_input,
        rows_analyzed=rows_analyzed,
        rows_excluded=rows_excluded,
        cells_detected=len(expected_layout.cell_cols),
        temperature_sensors_detected=len(expected_layout.temp_cols),
        pack_current_detected=expected_layout.pack_current_col is not None,
        pack_voltage_detected=expected_layout.pack_voltage_col is not None,
        metrics=analysis_metrics_from_summary(measurement_summary),
    )


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
