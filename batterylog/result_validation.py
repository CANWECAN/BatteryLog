"""Opt-in cross-field checks for structurally validated result-v8 payloads."""

from batterylog.analysis.comparison import BINARY64_ABS_TOL, BINARY64_REL_TOL
from batterylog.analysis.evaluation import active_rule_codes
from batterylog.config import ValidationLimits, validate_failure_current_direction
from batterylog.failure_config import parse_failure_models
from batterylog.failure_validation import validate_failure_report
from batterylog.models import AnalysisResult


def validate_result_semantics(result: AnalysisResult) -> None:
    """Check documented rule/policy and row-accounting invariants without mutation.

    First parse strict JSON and validate it against its v8 or v9 JSON Schema.
    This function supplements structural validation; it does not replace it or
    establish the correctness of measured extrema, event peaks or source data.
    It returns None on success and raises ValueError on a consistency failure.
    """
    if result["schema_version"] not in (8, 9):
        raise ValueError("Semantic result validation supports schema version 8 or 9 only")

    limits = ValidationLimits(**result["limits_applied"])
    rules = set(result["rules_evaluated"])
    if rules != set(active_rule_codes(limits)):
        raise ValueError("rules_evaluated must match the non-null limits_applied")

    if result["comparison_policy"] != {
        "mode": "strict_with_binary64_guard",
        "relative_tolerance": BINARY64_REL_TOL,
        "absolute_tolerance": BINARY64_ABS_TOL,
    }:
        raise ValueError("comparison_policy must match the fixed result-v8 binary64 policy")

    for index, event in enumerate(result["violations"]):
        if event["code"] not in rules:
            raise ValueError(f"violations[{index}].code must appear in rules_evaluated")

    rows_input = result["rows_input"]
    if rows_input != result["rows_analyzed"] + result["rows_excluded"]:
        raise ValueError("rows_input must equal rows_analyzed + rows_excluded")

    for index, defect in enumerate(result["data_quality"]["events"]):
        start, end = defect["start_row"], defect["end_row"]
        if not 1 <= start <= end <= rows_input:
            raise ValueError(
                f"data_quality.events[{index}] must satisfy 1 <= start_row <= end_row <= rows_input"
            )
        if defect["affected_values"] != (end - start + 1) * len(defect["signals"]):
            raise ValueError(
                f"data_quality.events[{index}].affected_values must equal row span * signal count"
            )

    if result["schema_version"] == 9:
        report = result.get("failure_models")
        if report is None:
            raise ValueError("result-v9 requires failure_models")
        validate_failure_current_direction(limits, parse_failure_models(report["config"]))
        validate_failure_report(report)
        statuses = [item["status"] for item in report["evaluations"]]
        expected_status = (
            "FAIL"
            if result["violations"] or result["data_quality"]["events"] or "FAIL" in statuses
            else "NOT_EVALUATED"
            if "NOT_EVALUATED" in statuses
            else "PASS"
        )
        if result["validation_status"] != expected_status:
            raise ValueError("validation_status must include all configured failure model outcomes")
    elif "failure_models" in result:
        raise ValueError("result-v8 cannot contain failure_models")
