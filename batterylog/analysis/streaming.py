from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from batterylog.config import (
    DataQualityConfig,
    EventDetectionConfig,
    SignalMapping,
    ValidationLimits,
    validate_failure_current_direction,
)
from batterylog.failure_config import FailureModelConfig
from batterylog.loaders import (
    MeasurementLoader,
    measurement_loader_for_file,
    measurement_loader_for_path,
)
from batterylog.models import AnalysisResult, DataQualityEvent

from .configuration import (
    resolve_data_quality,
    resolve_event_detection,
    resolve_limits,
    validate_signal_mapping,
    warn_legacy_threshold_arguments,
)
from .data_quality import DataQualityCollector
from .evaluation import active_rule_codes, evaluate_rules
from .failure_models import FailureModelCollector
from .input_validation import (
    SignalLayout,
    balance_values_for_frame,
    canonicalize_analysis_frame,
    coerce_required_numeric,
    failure_model_loader,
    raise_first_strict_input_error,
    valid_timestamp_values,
)
from .preparation import PreparedMeasurements, prepare_measurements
from .report_series import (
    DEFAULT_REPORT_SERIES_MAX_POINTS,
    ReportSeries,
    ReportSeriesCollector,
)
from .result_assembly import build_analysis_result
from .streaming_events import StreamingEventAccumulator
from .summary import (
    MeasurementSummary,
    analysis_metrics_from_summary,
    merge_measurement_summaries,
    summarize_prepared_measurements,
)


def _collect_prepared_report_series(
    prepared: PreparedMeasurements,
    collector: ReportSeriesCollector,
    *,
    row_offset: int,
) -> None:
    """Select analyzed measurements for display without re-evaluating rules."""
    valid_numeric = prepared.valid_numeric
    if not len(valid_numeric):
        return

    valid_rows = prepared.valid_rows
    inputs = prepared.rule_inputs
    current_col = inputs.pack_current_col
    voltage_col = inputs.pack_voltage_col
    collector.consume_chunk(
        row_offset=row_offset,
        timestamps=valid_numeric["timestamp_s"].to_numpy(dtype=float, copy=False),
        cell_min=inputs.cell_min.loc[valid_rows].to_numpy(dtype=float, copy=False),
        cell_max=inputs.cell_max.loc[valid_rows].to_numpy(dtype=float, copy=False),
        cell_delta=inputs.delta_v.loc[valid_rows].to_numpy(dtype=float, copy=False),
        temperature_min=inputs.temperature_min.loc[valid_rows].to_numpy(dtype=float, copy=False),
        temperature_max=inputs.temperature_max.loc[valid_rows].to_numpy(dtype=float, copy=False),
        pack_current=(
            valid_numeric[current_col].to_numpy(dtype=float, copy=False)
            if current_col is not None
            else None
        ),
        pack_voltage=(
            valid_numeric[voltage_col].to_numpy(dtype=float, copy=False)
            if voltage_col is not None
            else None
        ),
        cell_sum=(
            inputs.cell_sum.loc[valid_rows].to_numpy(dtype=float, copy=False)
            if inputs.cell_sum is not None
            else None
        ),
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
    failure_models: FailureModelConfig | None = None,
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
    failure_collector = FailureModelCollector(failure_models)
    validate_failure_current_direction(resolved_limits, failure_models)

    rules_evaluated = active_rule_codes(resolved_limits)
    event_accumulator = StreamingEventAccumulator.for_rules(
        rules_evaluated,
        resolved_limits,
    )

    rows_input = 0
    rows_analyzed = 0
    rows_excluded = 0
    data_quality_collector = (
        DataQualityCollector() if resolved_data_quality.mode == "exclude_invalid_rows" else None
    )
    expected_layout: SignalLayout | None = None
    previous_timestamp: float | None = None

    measurement_summary = MeasurementSummary()

    iterator = iter(chunks)
    try:
        for frame in iterator:
            if frame.empty:
                continue

            balance_values = balance_values_for_frame(frame, signal_mapping, failure_models)
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
            numeric = coerce_required_numeric(frame[layout.numeric_cols])
            if data_quality_collector is None:
                raise_first_strict_input_error(
                    frame,
                    numeric,
                    balance_values,
                    row_offset=chunk_row_offset,
                    previous_timestamp=previous_timestamp,
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
            rule_inputs = prepared.rule_inputs
            failure_collector.consume(
                rule_inputs,
                prepared.valid_rows,
                balance_values,
                exclude_invalid=resolved_data_quality.mode == "exclude_invalid_rows",
                row_offset=chunk_row_offset,
            )
            timestamps = rule_inputs.timestamps

            if report_series_collector is not None:
                _collect_prepared_report_series(
                    prepared,
                    report_series_collector,
                    row_offset=rows_analyzed,
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
                event_accumulator.consume(
                    evaluation,
                    timestamps=timestamps,
                    max_gap_s=max_gap_s,
                )

            rows_analyzed += len(prepared.valid_numeric)

    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            close()

    if rows_input == 0:
        raise ValueError("Battery log contains no data rows")

    assert expected_layout is not None

    data_quality_events: list[DataQualityEvent] = (
        data_quality_collector.finish() if data_quality_collector is not None else []
    )
    violations = event_accumulator.finish()

    return build_analysis_result(
        limits=resolved_limits,
        event_detection=resolved_event_detection,
        data_quality=resolved_data_quality,
        signal_mapping=signal_mapping,
        failure_models=failure_collector.finish(),
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
    failure_models: FailureModelConfig | None = None,
) -> AnalysisResult:
    loader = failure_model_loader(loader, failure_models)
    return _analyze_battery_chunks(
        loader.iter_chunks(signal_mapping=signal_mapping),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
        failure_models=failure_models,
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
    failure_models: FailureModelConfig | None = None,
    max_points: int = DEFAULT_REPORT_SERIES_MAX_POINTS,
) -> tuple[AnalysisResult, ReportSeries]:
    collector = ReportSeriesCollector(max_points=max_points)
    loader = failure_model_loader(loader, failure_models)
    result = _analyze_battery_chunks(
        loader.iter_chunks(signal_mapping=signal_mapping),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
        failure_models=failure_models,
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
    failure_models: FailureModelConfig | None = None,
) -> AnalysisResult:
    return analyze_measurement_loader(
        measurement_loader_for_path(path),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
        failure_models=failure_models,
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
    failure_models: FailureModelConfig | None = None,
) -> AnalysisResult:
    return analyze_measurement_loader(
        measurement_loader_for_file(handle, source_name=source_name),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
        failure_models=failure_models,
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
    failure_models: FailureModelConfig | None = None,
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
        failure_models=failure_models,
        max_points=max_points,
    )
