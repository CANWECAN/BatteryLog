from dataclasses import dataclass

from batterylog.config import (
    DataQualityConfig,
    EventDetectionConfig,
    SignalMapping,
    ValidationLimits,
)
from batterylog.models import (
    RESULT_SCHEMA_VERSION,
    AnalysisOptions,
    AnalysisResult,
    AppliedLimits,
    ComparisonPolicyInfo,
    DataQualityEvent,
    DataQualityInfo,
    PackVoltageCellSumPeak,
    RuleCode,
    SignalMappingInfo,
    ValidationStatus,
    ViolationEvent,
)
from batterylog.signals import CANONICAL_PACK_CURRENT, CANONICAL_PACK_VOLTAGE

from .comparison import BINARY64_ABS_TOL, BINARY64_REL_TOL


@dataclass(frozen=True)
class AnalysisMetrics:
    max_cell_voltage_v: float | None
    min_cell_voltage_v: float | None
    max_delta_v: float | None
    max_temperature_c: float | None
    min_temperature_c: float | None
    max_temperature_spread_c: float | None
    max_pack_current_a: float | None
    min_pack_current_a: float | None
    max_pack_voltage_v: float | None
    min_pack_voltage_v: float | None
    pack_voltage_cell_sum_peak: PackVoltageCellSumPeak | None


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
        "pack_voltage_cell_sum_max_delta_v": limits.pack_voltage_cell_sum_max_delta_v,
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
            "pack_current_source": CANONICAL_PACK_CURRENT if pack_current_detected else None,
            "pack_voltage_source": CANONICAL_PACK_VOLTAGE if pack_voltage_detected else None,
        }

    return {
        "mode": "explicit",
        "timestamp_source": mapping.timestamp,
        "cell_voltage_pattern": mapping.cell_voltage.pattern,
        "temperature_pattern": mapping.temperature.pattern,
        "pack_current_source": mapping.pack_current,
        "pack_voltage_source": mapping.pack_voltage,
    }


def _data_quality_snapshot(
    config: DataQualityConfig,
    events: list[DataQualityEvent],
) -> DataQualityInfo:
    return {"mode": config.mode, "events": events}


def build_analysis_result(
    *,
    limits: ValidationLimits,
    event_detection: EventDetectionConfig,
    data_quality: DataQualityConfig,
    signal_mapping: SignalMapping | None,
    rules_evaluated: list[RuleCode],
    data_quality_events: list[DataQualityEvent],
    violations: list[ViolationEvent],
    rows_input: int,
    rows_analyzed: int,
    rows_excluded: int,
    cells_detected: int,
    temperature_sensors_detected: int,
    pack_current_detected: bool,
    pack_voltage_detected: bool,
    metrics: AnalysisMetrics,
) -> AnalysisResult:
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
        "limits_applied": _limits_snapshot(limits),
        "analysis_options": _analysis_options_snapshot(event_detection),
        "comparison_policy": _comparison_policy_snapshot(),
        "signal_mapping": _signal_mapping_snapshot(
            signal_mapping,
            pack_current_detected=pack_current_detected,
            pack_voltage_detected=pack_voltage_detected,
        ),
        "data_quality": _data_quality_snapshot(data_quality, data_quality_events),
        "rows_input": rows_input,
        "rows_analyzed": rows_analyzed,
        "rows_excluded": rows_excluded,
        "cells_detected": cells_detected,
        "temperature_sensors_detected": temperature_sensors_detected,
        "max_cell_voltage_v": metrics.max_cell_voltage_v,
        "min_cell_voltage_v": metrics.min_cell_voltage_v,
        "max_delta_v": metrics.max_delta_v,
        "max_temperature_c": metrics.max_temperature_c,
        "min_temperature_c": metrics.min_temperature_c,
        "max_temperature_spread_c": metrics.max_temperature_spread_c,
        "max_pack_current_a": metrics.max_pack_current_a,
        "min_pack_current_a": metrics.min_pack_current_a,
        "max_pack_voltage_v": metrics.max_pack_voltage_v,
        "min_pack_voltage_v": metrics.min_pack_voltage_v,
        "pack_voltage_cell_sum_peak": metrics.pack_voltage_cell_sum_peak,
        "violations": violations,
    }
