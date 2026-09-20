import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from batterylog.config import (
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
    RuleCode,
    SignalMappingInfo,
    ViolationEvent,
)
from batterylog.signals import canonicalize_battery_signals

from .comparison import BINARY64_ABS_TOL, BINARY64_REL_TOL
from .rules import build_high_events, build_imbalance_events, build_low_events

CELL_SIGNAL_RE = re.compile(r"^cell_(\d+)_v$")
TEMP_SIGNAL_RE = re.compile(r"^temp_(\d+)_c$")


def _indexed_signal_columns(
    columns: pd.Index,
    pattern: re.Pattern[str],
    kind: str,
) -> list[str]:
    indexed: list[tuple[int, str]] = []
    seen_indexes: dict[int, str] = {}

    for column in columns:
        match = pattern.fullmatch(str(column))
        if match is None:
            continue

        index = int(match.group(1))
        if index in seen_indexes:
            previous = seen_indexes[index]
            raise ValueError(f"Duplicate {kind} signal index {index}: {previous!r} and {column!r}")
        seen_indexes[index] = str(column)
        indexed.append((index, str(column)))

    indexed.sort(key=lambda item: (item[0], item[1]))
    return [column for _, column in indexed]


def _find_signal_columns(columns: pd.Index) -> tuple[list[str], list[str]]:
    cell_cols = _indexed_signal_columns(columns, CELL_SIGNAL_RE, "cell")
    indexed_temp_cols = _indexed_signal_columns(columns, TEMP_SIGNAL_RE, "temperature")

    if "temp_c" in columns and indexed_temp_cols:
        raise ValueError("Legacy temp_c cannot be combined with indexed temp_<n>_c signals")

    temp_cols = ["temp_c"] if "temp_c" in columns else indexed_temp_cols
    return cell_cols, temp_cols


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
    missing_position = _first_true_position(numeric.isna().to_numpy())
    if missing_position is not None:
        row_pos, column_pos = missing_position
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


def _limits_snapshot(limits: ValidationLimits) -> AppliedLimits:
    return {
        "cell_min_v": limits.cell_min_v,
        "cell_max_v": limits.cell_max_v,
        "imbalance_max_v": limits.imbalance_max_v,
        "temperature_min_c": limits.temperature_min_c,
        "temperature_max_c": limits.temperature_max_c,
    }


def _analysis_options_snapshot(config: EventDetectionConfig) -> AnalysisOptions:
    return {"max_event_gap_s": config.max_gap_s}


def _comparison_policy_snapshot() -> ComparisonPolicyInfo:
    return {
        "mode": "strict_with_binary64_guard",
        "relative_tolerance": BINARY64_REL_TOL,
        "absolute_tolerance": BINARY64_ABS_TOL,
    }


def _signal_mapping_snapshot(mapping: SignalMapping | None) -> SignalMappingInfo:
    if mapping is None:
        return {
            "mode": "canonical",
            "timestamp_source": "timestamp_s",
            "cell_voltage_pattern": None,
            "temperature_pattern": None,
        }

    return {
        "mode": "explicit",
        "timestamp_source": mapping.timestamp,
        "cell_voltage_pattern": mapping.cell_voltage.pattern,
        "temperature_pattern": mapping.temperature.pattern,
    }


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
    return codes


def _analyze_battery_frame(
    df: pd.DataFrame,
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

    numeric_cols = ["timestamp_s", *cell_cols, *temp_cols]
    numeric = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    _raise_invalid_numeric_value(df, numeric)

    timestamps = numeric["timestamp_s"]
    if not timestamps.is_monotonic_increasing:
        raise ValueError("timestamp_s must be non-decreasing")

    cell_max = numeric[cell_cols].max(axis=1)
    cell_min = numeric[cell_cols].min(axis=1)
    delta_v = cell_max - cell_min
    row_max_temp = numeric[temp_cols].max(axis=1)
    row_min_temp = numeric[temp_cols].min(axis=1)

    rules_evaluated = _active_rule_codes(resolved_limits)
    violations: list[ViolationEvent] = []

    if resolved_limits.imbalance_max_v is not None:
        violations.extend(
            build_imbalance_events(
                numeric,
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
                numeric=numeric,
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
                numeric=numeric,
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
                numeric=numeric,
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
                numeric=numeric,
                timestamps=timestamps,
                signal_cols=temp_cols,
                row_min=row_min_temp,
                limit=resolved_limits.temperature_min_c,
                code="TEMPERATURE_LOW",
                unit="degC",
                max_gap_s=resolved_event_detection.max_gap_s,
            )
        )

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
        "rows_analyzed": len(df),
        "cells_detected": len(cell_cols),
        "temperature_sensors_detected": len(temp_cols),
        "max_cell_voltage_v": float(cell_max.max()),
        "min_cell_voltage_v": float(cell_min.min()),
        "max_delta_v": round(float(delta_v.max()), 12),
        "max_temperature_c": float(row_max_temp.max()),
        "min_temperature_c": float(row_min_temp.min()),
        "violations": violations,
    }


def analyze_battery_log(
    path: str | Path,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    signal_mapping: SignalMapping | None = None,
) -> AnalysisResult:
    from .streaming import analyze_battery_log_streaming

    return analyze_battery_log_streaming(
        path,
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        signal_mapping=signal_mapping,
    )


def analyze_battery_bytes(
    data: bytes,
    imbalance_limit_v: float | None = None,
    temp_warning_c: float | None = None,
    *,
    limits: ValidationLimits | None = None,
    event_detection: EventDetectionConfig | None = None,
    signal_mapping: SignalMapping | None = None,
) -> AnalysisResult:
    return _analyze_battery_frame(
        load_battery_csv_bytes(data),
        imbalance_limit_v,
        temp_warning_c,
        limits=limits,
        event_detection=event_detection,
        signal_mapping=signal_mapping,
    )
