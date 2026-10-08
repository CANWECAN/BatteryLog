from pathlib import Path

import pandas as pd

from batterylog.config import (
    DataQualityConfig,
    EventDetectionConfig,
    SignalMapping,
    ValidationLimits,
    validate_failure_current_direction,
)
from batterylog.failure_config import FailureModelConfig
from batterylog.loaders import load_battery_csv_bytes
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
    balance_values_for_frame,
    canonicalize_analysis_frame,
    coerce_required_numeric,
    raise_first_strict_input_error,
    unloaded_values_for_frame,
    valid_timestamp_values,
)
from .preparation import prepare_measurements
from .result_assembly import build_analysis_result
from .summary import analysis_metrics_from_summary, summarize_prepared_measurements


def _analyze_battery_frame(
    df: pd.DataFrame,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    data_quality: DataQualityConfig | None = None,
    signal_mapping: SignalMapping | None = None,
    failure_models: FailureModelConfig | None = None,
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

    if df.empty:
        raise ValueError("Battery log contains no data rows")

    balance_values = balance_values_for_frame(df, signal_mapping, failure_models)
    unloaded_values = unloaded_values_for_frame(df, signal_mapping, failure_models)
    df, layout = canonicalize_analysis_frame(df, signal_mapping, resolved_limits)
    cell_cols = layout.cell_cols
    temp_cols = layout.temp_cols
    pack_current_col = layout.pack_current_col
    pack_voltage_col = layout.pack_voltage_col
    pack_cols = layout.pack_cols

    numeric = coerce_required_numeric(df[layout.numeric_cols])
    rows_input = len(df)
    data_quality_events: list[DataQualityEvent] = []

    if resolved_data_quality.mode == "strict":
        raise_first_strict_input_error(df, numeric, balance_values, unloaded_values=unloaded_values)
        invalid_rows = pd.Series(False, index=numeric.index, dtype=bool)
    else:
        collector = DataQualityCollector()
        invalid_values = collector.consume_chunk(df, numeric, row_offset=0)
        invalid_rows = pd.Series(invalid_values, index=numeric.index, dtype=bool)
        data_quality_events = collector.finish()

    ordering_timestamps = valid_timestamp_values(df, numeric)
    if not ordering_timestamps.is_monotonic_increasing:
        raise ValueError("timestamp_s must be non-decreasing")

    rows_excluded = int(invalid_rows.sum())
    prepared = prepare_measurements(
        numeric,
        invalid_rows,
        pack_cols=pack_cols,
        cell_cols=cell_cols,
        temp_cols=temp_cols,
        pack_current_col=pack_current_col,
        pack_voltage_col=pack_voltage_col,
    )
    rule_inputs = prepared.rule_inputs
    failure_collector.consume(
        rule_inputs,
        prepared.valid_rows,
        balance_values,
        unloaded_values=unloaded_values,
        exclude_invalid=resolved_data_quality.mode == "exclude_invalid_rows",
    )
    rows_analyzed = len(prepared.valid_numeric)
    summary = summarize_prepared_measurements(prepared)

    rules_evaluated = active_rule_codes(resolved_limits)
    violations = [
        event
        for evaluation in evaluate_rules(
            rule_inputs,
            resolved_limits,
            max_gap_s=resolved_event_detection.max_gap_s,
        )
        for event in evaluation.events
    ]

    violations.sort(key=lambda event: (event["start_time_s"], event["code"]))

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
        cells_detected=len(cell_cols),
        temperature_sensors_detected=len(temp_cols),
        pack_current_detected=pack_current_col is not None,
        pack_voltage_detected=pack_voltage_col is not None,
        metrics=analysis_metrics_from_summary(summary),
    )


def analyze_battery_log(
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
    from .streaming import analyze_battery_log_streaming

    return analyze_battery_log_streaming(
        path,
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
        failure_models=failure_models,
    )


def analyze_battery_bytes(
    data: bytes,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    data_quality: DataQualityConfig | None = None,
    signal_mapping: SignalMapping | None = None,
    failure_models: FailureModelConfig | None = None,
) -> AnalysisResult:
    return _analyze_battery_frame(
        load_battery_csv_bytes(data),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
        failure_models=failure_models,
    )
