import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from batterylog import ValidationLimits, analyze_battery_log, load_validation_config

ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "batterylog" / "schema" / "result-v1.json"
SAMPLE = ROOT / "examples" / "sample_battery_log.csv"
VENDOR_SAMPLE = ROOT / "examples" / "vendor_battery_log.csv"
VENDOR_CONFIG = ROOT / "examples" / "vendor_mapping.example.yaml"


@pytest.fixture(scope="module")
def result_schema() -> dict[str, object]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


@pytest.fixture(scope="module")
def validator(result_schema: dict[str, object]) -> Draft202012Validator:
    return Draft202012Validator(result_schema)


def _results_for_all_statuses() -> list[dict[str, object]]:
    not_evaluated = analyze_battery_log(SAMPLE)
    passed = analyze_battery_log(
        SAMPLE,
        limits=ValidationLimits(
            imbalance_max_v=0.11,
            temperature_max_c=50.0,
        ),
    )

    config = load_validation_config(VENDOR_CONFIG)
    failed = analyze_battery_log(
        VENDOR_SAMPLE,
        limits=config.limits,
        event_detection=config.event_detection,
        signal_mapping=config.signals,
    )
    return [not_evaluated, passed, failed]


def test_generated_results_validate_against_schema_v1(
    validator: Draft202012Validator,
) -> None:
    for result in _results_for_all_statuses():
        validator.validate(result)


def test_schema_rejects_unknown_top_level_fields(
    validator: Draft202012Validator,
) -> None:
    result = copy.deepcopy(analyze_battery_log(SAMPLE))
    result["unexpected"] = True  # type: ignore[typeddict-unknown-key]

    with pytest.raises(ValidationError):
        validator.validate(result)


def test_schema_rejects_missing_required_fields(
    validator: Draft202012Validator,
) -> None:
    result = dict(analyze_battery_log(SAMPLE))
    result.pop("comparison_policy")

    with pytest.raises(ValidationError):
        validator.validate(result)


@pytest.mark.parametrize(
    ("status", "limits", "mutate"),
    [
        (
            "PASS",
            ValidationLimits(imbalance_max_v=0.11),
            lambda payload: payload["rules_evaluated"].clear(),
        ),
        (
            "FAIL",
            ValidationLimits(imbalance_max_v=0.08),
            lambda payload: payload["violations"].clear(),
        ),
        (
            "NOT_EVALUATED",
            ValidationLimits(),
            lambda payload: payload["rules_evaluated"].append("CELL_OVERVOLTAGE"),
        ),
    ],
)
def test_schema_enforces_validation_status_invariants(
    validator: Draft202012Validator,
    status: str,
    limits: ValidationLimits,
    mutate,
) -> None:
    result = copy.deepcopy(analyze_battery_log(SAMPLE, limits=limits))
    assert result["validation_status"] == status
    mutate(result)

    with pytest.raises(ValidationError):
        validator.validate(result)


def test_schema_rejects_invalid_canonical_mapping_provenance(
    validator: Draft202012Validator,
) -> None:
    result = copy.deepcopy(analyze_battery_log(SAMPLE))
    result["signal_mapping"]["timestamp_source"] = "Time"

    with pytest.raises(ValidationError):
        validator.validate(result)


def test_schema_rejects_rule_unit_mismatch(
    validator: Draft202012Validator,
) -> None:
    result = copy.deepcopy(
        analyze_battery_log(
            SAMPLE,
            limits=ValidationLimits(imbalance_max_v=0.08),
        )
    )
    assert result["violations"][0]["code"] == "CELL_IMBALANCE_HIGH"
    result["violations"][0]["unit"] = "degC"

    with pytest.raises(ValidationError):
        validator.validate(result)
