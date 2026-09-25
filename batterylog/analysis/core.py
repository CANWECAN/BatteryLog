import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from batterylog.config import (
    DataQualityConfig,
    EventDetectionConfig,
    SignalMapping,
    ValidationLimits,
    override_validation_limits,
)
from batterylog.loaders import load_battery_csv_bytes
from batterylog.models import (
    RESULT_SCHEMA_VERSION,
    AnalysisOptions,
    AnalysisResult,
    AppliedLimits,
    ComparisonPolicyInfo,
    CurrentDirection,
    DataQualityEvent,
    DataQualityInfo,
    RuleCode,
    SignalMappingInfo,
    ValidationStatus,
    ViolationEvent,
)
from batterylog.signals import (
    CANONICAL_PACK_CURRENT,
    CANONICAL_PACK_VOLTAGE,
    canonicalize_battery_signals,
    find_canonical_pack_signal_columns,
    find_canonical_signal_columns,
)

from .comparison import BINARY64_ABS_TOL, BINARY64_REL_TOL
from .data_quality import DataQualityCollector, _required_boolean_mask
from .rules import (
    build_high_events,
    build_imbalance_events,
    build_low_events,
    build_temperature_spread_events,
)


def _find_signal_columns(columns: pd.Index) -> tuple[list[str], list[str]]:
    return find_canonical_signal_columns(columns)


def _warn_legacy_threshold_arguments(
    imbalance_limit_v: float | None,
    temp_warning_c: float | None,
) -> None:
    if imbalance_limit_v is None and temp_warning_c is None:
        return

    warnings.warn(
        "imbalance_limit_v and temp_warning_c are deprecated; "
        "pass a ValidationLimits instance via limits=. "
        "Legacy values currently override the corresponding limits fields.",
        DeprecationWarning,
        stacklevel=3,
    )


def _first_true_position(mask: np.ndarray) -> tuple[int, int] | None:
    if not mask.any():
        return None

    flat_position = int(np.argmax(mask))
    row_pos, column_pos = divmod(flat_position, mask.shape[1])
    return row_pos, column_pos


def _raise_invalid_numeric_value(
    frame: pd.DataFrame,
    numeric: pd.DataFrame,
    *,
    row_offset: int = 0,
) -> None:
    columns = list(numeric.columns)
    invalid_numeric = numeric.isna().to_numpy() | _required_boolean_mask(frame, columns)
    invalid_position = _first_true_position(invalid_numeric)
    if invalid_position is not None:
        row_pos, column_pos = invalid_position
        column = numeric.columns[column_pos]
        raw_value = frame.iloc[row_pos][column]
        row_index = frame.index[row_pos]
        raise ValueError(
            "Required numeric value is missing or non-numeric at "
            f"data row {row_offset + row_pos + 1} (index {row_index!r}), "
            f"column {column!r}: {raw_value!r}"
        )

    values = numeric.to_numpy(dtype=float)
    non_finite_position = _first_true_position(~np.isfinite(values))
    if non_finite_position is not None:
        row_pos, column_pos = non_finite_position
        column = numeric.columns[column_pos]
        value = values[row_pos, column_pos]
        row_index = frame.index[row_pos]
        raise ValueError(
            "Required numeric value is non-finite at "
            f"data row {row_offset + row_pos + 1} (index {row_index!r}), "
            f"column {column!r}: {value!r}"
        )


def _resolve_limits(
    limits: ValidationLimits | None,
    imbalance_limit_v: float | None,
    temp_warning_c: float | None,
) -> ValidationLimits:
    if limits is not None and not isinstance(limits, ValidationLimits):
        raise TypeError("limits must be a ValidationLimits instance or null")

    resolved = limits if limits is not None else ValidationLimits()
    return override_validation_limits(
        resolved,
        imbalance_max_v=imbalance_limit_v,
        temperature_max_c=temp_warning_c,
    )


def _resolve_event_detection(
    event_detection: EventDetectionConfig | None,
) -> EventDetectionConfig:
    if event_detection is not None and not isinstance(
        event_detection,
        EventDetectionConfig,
    ):
        raise TypeError("event_detection must be an EventDetectionConfig instance or null")
    return event_detection if event_detection is not None else EventDetectionConfig()


def _resolve_data_quality(data_quality: DataQualityConfig | None) -> DataQualityConfig:
    if data_quality is not None and not isinstance(data_quality, DataQualityConfig):
        raise TypeError("data_quality must be a DataQualityConfig instance or null")
    return data_quality if data_quality is not None else DataQualityConfig()


def _data_quality_snapshot(
    config: DataQualityConfig,
    events: list[DataQualityEvent],
) -> DataQualityInfo:
    return {"mode": config.mode, "events": events}


def _limits_snapshot(limits: ValidationLimits) -> AppliedLimits:
    return {
        "cell_min_v": limits.cell_min_v,
        "cell_max_v": limits.cell_max_v,
        "imbalance_max_v": limits.imbalance_max_v,
        "temperature_min_c": limits.temperature_min_c,
        "temperature_max_c": limits.temperature_max_c,
        "temperature_spread_max_c": limits.temperature_spread_max_c,
        "pack_charge_max_a": limits.pack_charge_max_a,
        "pack_discharge_max_a": limits.pack_discharge_max_a,
        "pack_current_positive_direction": limits.pack_current_positive_direction,
    }


def _analysis_options_snapshot(config: EventDetectionConfig) -> AnalysisOptions:
    return {"max_event_gap_s": config.max_gap_s}


def _comparison_policy_snapshot() -> ComparisonPolicyInfo:
    return {
        "mode": "strict_with_binary64_guard",
        "relative_tolerance": BINARY64_REL_TOL,
        "absolute_tolerance": BINARY64_ABS_TOL,
    }


def _signal_mapping_snapshot(
    mapping: SignalMapping | None,
    *,
    pack_current_detected: bool,
    pack_voltage_detected: bool,
) -> SignalMappingInfo:
    if mapping is None:
        return {
            "mode": "canonical",
            "timestamp_source": "timestamp_s",
            "cell_voltage_pattern": None,
            "temperature_pattern": None,
            "pack_current_source": (CANONICAL_PACK_CURRENT if pack_current_detected else None),
            "pack_voltage_source": (CANONICAL_PACK_VOLTAGE if pack_voltage_detected else None),
        }

    return {
        "mode": "explicit",
        "timestamp_source": mapping.timestamp,
        "cell_voltage_pattern": mapping.cell_voltage.pattern,
        "temperature_pattern": mapping.temperature.pattern,
        "pack_current_source": mapping.pack_current,
        "pack_voltage_source": mapping.pack_voltage,
    }


def _pack_current_rule_parameters(
    limits: ValidationLimits,
    direction: CurrentDirection,
) -> tuple[float, bool] | None:
    magnitude = limits.pack_charge_max_a if direction == "charge" else limits.pack_discharge_max_a
    if magnitude is None:
        return None
    assert limits.pack_current_positive_direction is not None
    prefer_lower = limits.pack_current_positive_direction != direction
    signed_limit = -magnitude if prefer_lower else magnitude
    return signed_limit, prefer_lower


_PACK_CURRENT_RULES: tuple[tuple[CurrentDirection, RuleCode], ...] = (
    ("charge", "PACK_CHARGE_OVERCURRENT"),
    ("discharge", "PACK_DISCHARGE_OVERCURRENT"),
)


def _rule_prefers_lower(code: RuleCode, limits: ValidationLimits) -> bool:
    if code in {"CELL_UNDERVOLTAGE", "TEMPERATURE_LOW"}:
        return True
    if code == "PACK_CHARGE_OVERCURRENT":
        parameters = _pack_current_rule_parameters(limits, "charge")
        assert parameters is not None
        return parameters[1]
    if code == "PACK_DISCHARGE_OVERCURRENT":
        parameters = _pack_current_rule_parameters(limits, "discharge")
        assert parameters is not None
        return parameters[1]
    return False


def _active_rule_codes(limits: ValidationLimits) -> list[RuleCode]:
    codes: list[RuleCode] = []
    if limits.imbalance_max_v is not None:
        codes.append("CELL_IMBALANCE_HIGH")
    if limits.cell_max_v is not None:
        codes.append("CELL_OVERVOLTAGE")
    if limits.cell_min_v is not None:
        codes.append("CELL_UNDERVOLTAGE")
    if limits.temperature_max_c is not None:
        codes.append("TEMPERATURE_HIGH")
    if limits.temperature_min_c is not None:
        codes.append("TEMPERATURE_LOW")
    if limits.temperature_spread_max_c is not None:
        codes.append("TEMPERATURE_SPREAD_HIGH")
    if limits.pack_charge_max_a is not None:
        codes.append("PACK_CHARGE_OVERCURRENT")
    if limits.pack_discharge_max_a is not None:
        codes.append("PACK_DISCHARGE_OVERCURRENT")
    return codes


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

    if df.empty:
        raise ValueError("Battery log contains no data rows")

    df = canonicalize_battery_signals(df, signal_mapping)
    if "timestamp_s" not in df.columns:
        raise ValueError("Required column 'timestamp_s' is missing")

    cell_cols, temp_cols = _find_signal_columns(df.columns)
    if not cell_cols:
        raise ValueError("No cell voltage columns found")
    if not temp_cols:
        raise ValueError("No temperature columns found")
    pack_current_col, pack_voltage_col = find_canonical_pack_signal_columns(df.columns)
    if (
        resolved_limits.pack_charge_max_a is not None
        or resolved_limits.pack_discharge_max_a is not None
    ) and pack_current_col is None:
        raise ValueError("Pack-current validation requires column 'pack_current_a'")
    pack_cols = [column for column in (pack_current_col, pack_voltage_col) if column is not None]

    numeric_cols = ["timestamp_s", *pack_cols, *cell_cols, *temp_cols]
    numeric = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    rows_input = len(df)
    data_quality_events: list[DataQualityEvent] = []

    if resolved_data_quality.mode == "strict":
        _raise_invalid_numeric_value(df, numeric)
        invalid_rows = pd.Series(False, index=numeric.index, dtype=bool)
    else:
        collector = DataQualityCollector()
        invalid_values = collector.consume_chunk(df, numeric, row_offset=0)
        invalid_rows = pd.Series(invalid_values, index=numeric.index, dtype=bool)
        data_quality_events = collector.finish()

    valid_rows = ~invalid_rows
    rows_excluded = int(invalid_rows.sum())
    rows_analyzed = int(valid_rows.sum())
    valid_numeric = numeric.loc[valid_rows]
    valid_timestamps = valid_numeric["timestamp_s"]
    if not valid_timestamps.is_monotonic_increasing:
        raise ValueError("timestamp_s must be non-decreasing")

    rule_numeric = pd.DataFrame(
        numeric.to_numpy(dtype=float, na_value=np.nan),
        index=numeric.index,
        columns=numeric.columns,
    )
    if rows_excluded:
        rule_numeric.loc[invalid_rows, [*pack_cols, *cell_cols, *temp_cols]] = np.nan
    timestamps = rule_numeric["timestamp_s"]
    cell_max = rule_numeric[cell_cols].max(axis=1)
    cell_min = rule_numeric[cell_cols].min(axis=1)
    delta_v = cell_max - cell_min
    row_max_temp = rule_numeric[temp_cols].max(axis=1)
    row_min_temp = rule_numeric[temp_cols].min(axis=1)
    temperature_spread = row_max_temp - row_min_temp

    rules_evaluated = _active_rule_codes(resolved_limits)
    violations: list[ViolationEvent] = []

    if resolved_limits.imbalance_max_v is not None:
        violations.extend(
            build_imbalance_events(
                rule_numeric,
                timestamps,
                cell_cols,
                delta_v,
                resolved_limits.imbalance_max_v,
                max_gap_s=resolved_event_detection.max_gap_s,
            )
        )
    if resolved_limits.cell_max_v is not None:
        violations.extend(
            build_high_events(
                numeric=rule_numeric,
                timestamps=timestamps,
                signal_cols=cell_cols,
                row_max=cell_max,
                limit=resolved_limits.cell_max_v,
                code="CELL_OVERVOLTAGE",
                unit="V",
                max_gap_s=resolved_event_detection.max_gap_s,
            )
        )
    if resolved_limits.cell_min_v is not None:
        violations.extend(
            build_low_events(
                numeric=rule_numeric,
                timestamps=timestamps,
                signal_cols=cell_cols,
                row_min=cell_min,
                limit=resolved_limits.cell_min_v,
                code="CELL_UNDERVOLTAGE",
                unit="V",
                max_gap_s=resolved_event_detection.max_gap_s,
            )
        )
    if resolved_limits.temperature_max_c is not None:
        violations.extend(
            build_high_events(
                numeric=rule_numeric,
                timestamps=timestamps,
                signal_cols=temp_cols,
                row_max=row_max_temp,
                limit=resolved_limits.temperature_max_c,
                code="TEMPERATURE_HIGH",
                unit="degC",
                max_gap_s=resolved_event_detection.max_gap_s,
            )
        )
    if resolved_limits.temperature_min_c is not None:
        violations.extend(
            build_low_events(
                numeric=rule_numeric,
                timestamps=timestamps,
                signal_cols=temp_cols,
                row_min=row_min_temp,
                limit=resolved_limits.temperature_min_c,
                code="TEMPERATURE_LOW",
                unit="degC",
                max_gap_s=resolved_event_detection.max_gap_s,
            )
        )

    if resolved_limits.temperature_spread_max_c is not None:
        violations.extend(
            build_temperature_spread_events(
                rule_numeric,
                timestamps,
                temp_cols,
                temperature_spread,
                resolved_limits.temperature_spread_max_c,
                max_gap_s=resolved_event_detection.max_gap_s,
            )
        )
    if pack_current_col is not None:
        pack_current = rule_numeric[pack_current_col]
        for direction, code in _PACK_CURRENT_RULES:
            parameters = _pack_current_rule_parameters(resolved_limits, direction)
            if parameters is None:
                continue
            signed_limit, prefer_lower = parameters
            if prefer_lower:
                events = build_low_events(
                    numeric=rule_numeric,
                    timestamps=timestamps,
                    signal_cols=[pack_current_col],
                    row_min=pack_current,
                    limit=signed_limit,
                    code=code,
                    unit="A",
                    max_gap_s=resolved_event_detection.max_gap_s,
                )
            else:
                events = build_high_events(
                    numeric=rule_numeric,
                    timestamps=timestamps,
                    signal_cols=[pack_current_col],
                    row_max=pack_current,
                    limit=signed_limit,
                    code=code,
                    unit="A",
                    max_gap_s=resolved_event_detection.max_gap_s,
                )
            violations.extend(events)

    violations.sort(key=lambda event: (event["start_time_s"], event["code"]))

    validation_status: ValidationStatus
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
            pack_current_detected=pack_current_col is not None,
            pack_voltage_detected=pack_voltage_col is not None,
        ),
        "data_quality": _data_quality_snapshot(resolved_data_quality, data_quality_events),
        "rows_input": rows_input,
        "rows_analyzed": rows_analyzed,
        "rows_excluded": rows_excluded,
        "cells_detected": len(cell_cols),
        "temperature_sensors_detected": len(temp_cols),
        "max_cell_voltage_v": float(cell_max.loc[valid_rows].max()) if rows_analyzed else None,
        "min_cell_voltage_v": float(cell_min.loc[valid_rows].min()) if rows_analyzed else None,
        "max_delta_v": round(float(delta_v.loc[valid_rows].max()), 12) if rows_analyzed else None,
        "max_temperature_c": (float(row_max_temp.loc[valid_rows].max()) if rows_analyzed else None),
        "min_temperature_c": (float(row_min_temp.loc[valid_rows].min()) if rows_analyzed else None),
        "max_temperature_spread_c": (
            round(float(temperature_spread.loc[valid_rows].max()), 12) if rows_analyzed else None
        ),
        "max_pack_current_a": (
            float(rule_numeric.loc[valid_rows, pack_current_col].max())
            if rows_analyzed and pack_current_col is not None
            else None
        ),
        "min_pack_current_a": (
            float(rule_numeric.loc[valid_rows, pack_current_col].min())
            if rows_analyzed and pack_current_col is not None
            else None
        ),
        "max_pack_voltage_v": (
            float(rule_numeric.loc[valid_rows, pack_voltage_col].max())
            if rows_analyzed and pack_voltage_col is not None
            else None
        ),
        "min_pack_voltage_v": (
            float(rule_numeric.loc[valid_rows, pack_voltage_col].min())
            if rows_analyzed and pack_voltage_col is not None
            else None
        ),
        "violations": violations,
    }


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
