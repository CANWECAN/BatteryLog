from batterylog.analysis.result_assembly import AnalysisMetrics, build_analysis_result
from batterylog.config import DataQualityConfig, EventDetectionConfig, ValidationLimits
from batterylog.models import DataQualityEvent, RuleCode


def _metrics(*, analyzed: bool) -> AnalysisMetrics:
    return AnalysisMetrics(
        max_cell_voltage_v=3.7 if analyzed else None,
        min_cell_voltage_v=3.7 if analyzed else None,
        max_delta_v=0.0 if analyzed else None,
        max_temperature_c=25.0 if analyzed else None,
        min_temperature_c=25.0 if analyzed else None,
        max_temperature_spread_c=0.0 if analyzed else None,
        max_pack_current_a=None,
        min_pack_current_a=None,
        max_pack_voltage_v=None,
        min_pack_voltage_v=None,
        pack_voltage_cell_sum_peak=None,
    )


def _result(*, rules: list[RuleCode], data_quality_events: list[DataQualityEvent]):
    excluded = bool(data_quality_events)
    return build_analysis_result(
        limits=ValidationLimits(cell_max_v=4.2 if rules else None),
        event_detection=EventDetectionConfig(),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows" if excluded else "strict"),
        signal_mapping=None,
        rules_evaluated=rules,
        data_quality_events=data_quality_events,
        violations=[],
        rows_input=1,
        rows_analyzed=0 if excluded else 1,
        rows_excluded=1 if excluded else 0,
        cells_detected=1,
        temperature_sensors_detected=1,
        pack_current_detected=excluded,
        pack_voltage_detected=excluded,
        metrics=_metrics(analyzed=not excluded),
    )


def test_result_assembly_not_evaluated_without_rules_or_evidence() -> None:
    result = _result(rules=[], data_quality_events=[])
    assert result["validation_status"] == "NOT_EVALUATED"


def test_result_assembly_passes_when_rules_are_evaluated_without_evidence() -> None:
    result = _result(rules=["CELL_OVERVOLTAGE"], data_quality_events=[])
    assert result["validation_status"] == "PASS"
    assert result["rules_evaluated"] == ["CELL_OVERVOLTAGE"]


def test_result_assembly_data_quality_forces_fail_and_preserves_canonical_pack_sources() -> None:
    result = _result(
        rules=[],
        data_quality_events=[
            {
                "code": "NON_NUMERIC_REQUIRED_VALUE",
                "start_row": 1,
                "end_row": 1,
                "signals": ["cell_1_v"],
                "affected_values": 1,
            }
        ],
    )
    assert result["validation_status"] == "FAIL"
    assert result["signal_mapping"]["pack_current_source"] == "pack_current_a"
    assert result["signal_mapping"]["pack_voltage_source"] == "pack_voltage_v"
