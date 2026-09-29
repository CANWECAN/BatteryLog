from pathlib import Path

import numpy as np
import pandas as pd

from batterylog.config import (
    DataQualityConfig,
    EventDetectionConfig,
    SignalMapping,
    ValidationLimits,
)
from batterylog.loaders import load_battery_csv_bytes
from batterylog.models import AnalysisResult, DataQualityEvent, PackVoltageCellSumPeak

from .configuration import (
    resolve_data_quality,
    resolve_event_detection,
    resolve_limits,
    validate_signal_mapping,
    warn_legacy_threshold_arguments,
)
from .data_quality import DataQualityCollector
from .evaluation import active_rule_codes, evaluate_rules
from .input_validation import (
    canonicalize_analysis_frame,
    raise_invalid_numeric_value,
    valid_timestamp_values,
)
from .preparation import prepare_measurements
from .result_assembly import AnalysisMetrics, build_analysis_result


def _analyze_battery_frame(
    df: pd.DataFrame,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    data_quality: DataQualityConfig | None = None,
    signal_mapping: SignalMapping | None = None,
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

    if df.empty:
        raise ValueError("Battery log contains no data rows")

    df, layout = canonicalize_analysis_frame(df, signal_mapping, resolved_limits)
    cell_cols = layout.cell_cols
    temp_cols = layout.temp_cols
    pack_current_col = layout.pack_current_col
    pack_voltage_col = layout.pack_voltage_col
    pack_cols = layout.pack_cols

    numeric = df[layout.numeric_cols].apply(pd.to_numeric, errors="coerce")
    rows_input = len(df)
    data_quality_events: list[DataQualityEvent] = []

    if resolved_data_quality.mode == "strict":
        raise_invalid_numeric_value(df, numeric)
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
    valid_rows = prepared.valid_rows
    valid_numeric = prepared.valid_numeric
    rule_inputs = prepared.rule_inputs
    rule_numeric = rule_inputs.numeric
    cell_max = rule_inputs.cell_max
    cell_min = rule_inputs.cell_min
    delta_v = rule_inputs.delta_v
    row_max_temp = rule_inputs.temperature_max
    row_min_temp = rule_inputs.temperature_min
    temperature_spread = rule_inputs.temperature_spread
    cell_sum = rule_inputs.cell_sum
    pack_cell_delta = rule_inputs.pack_cell_delta
    rows_analyzed = int(valid_rows.sum())

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

    pack_cell_peak: PackVoltageCellSumPeak | None = None
    if pack_cell_delta is not None and rows_analyzed:
        assert pack_voltage_col is not None
        assert cell_sum is not None
        # Positional argmax selects the earliest sample on a tie, including duplicate timestamps.
        peak_position = int(np.argmax(pack_cell_delta.loc[valid_rows].to_numpy(dtype=float)))
        peak_row = valid_numeric.iloc[peak_position]
        pack = float(peak_row[pack_voltage_col])
        summed = float(cell_sum.loc[valid_rows].iloc[peak_position])
        pack_cell_peak = {
            "timestamp_s": float(peak_row["timestamp_s"]),
            "pack_voltage_v": pack,
            "cell_voltage_sum_v": summed,
            "signed_error_v": pack - summed,
            "absolute_delta_v": float(pack_cell_delta.loc[valid_rows].iloc[peak_position]),
        }

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
        cells_detected=len(cell_cols),
        temperature_sensors_detected=len(temp_cols),
        pack_current_detected=pack_current_col is not None,
        pack_voltage_detected=pack_voltage_col is not None,
        metrics=AnalysisMetrics(
            max_cell_voltage_v=float(cell_max.loc[valid_rows].max()) if rows_analyzed else None,
            min_cell_voltage_v=float(cell_min.loc[valid_rows].min()) if rows_analyzed else None,
            max_delta_v=round(float(delta_v.loc[valid_rows].max()), 12) if rows_analyzed else None,
            max_temperature_c=float(row_max_temp.loc[valid_rows].max()) if rows_analyzed else None,
            min_temperature_c=float(row_min_temp.loc[valid_rows].min()) if rows_analyzed else None,
            max_temperature_spread_c=(
                round(float(temperature_spread.loc[valid_rows].max()), 12)
                if rows_analyzed
                else None
            ),
            max_pack_current_a=(
                float(rule_numeric.loc[valid_rows, pack_current_col].max())
                if rows_analyzed and pack_current_col is not None
                else None
            ),
            min_pack_current_a=(
                float(rule_numeric.loc[valid_rows, pack_current_col].min())
                if rows_analyzed and pack_current_col is not None
                else None
            ),
            max_pack_voltage_v=(
                float(rule_numeric.loc[valid_rows, pack_voltage_col].max())
                if rows_analyzed and pack_voltage_col is not None
                else None
            ),
            min_pack_voltage_v=(
                float(rule_numeric.loc[valid_rows, pack_voltage_col].min())
                if rows_analyzed and pack_voltage_col is not None
                else None
            ),
            pack_voltage_cell_sum_peak=pack_cell_peak,
        ),
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
) -> AnalysisResult:
    return _analyze_battery_frame(
        load_battery_csv_bytes(data),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        data_quality=data_quality,
        signal_mapping=signal_mapping,
    )
