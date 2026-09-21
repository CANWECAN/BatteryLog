import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from batterylog import (
    RESULT_SCHEMA_VERSION,
    DataQualityConfig,
    ValidationLimits,
    analyze_battery_log,
    load_validation_config,
)
from batterylog.analysis.core import analyze_battery_bytes

ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "batterylog" / "schema" / "result-v3.json"
V2_SCHEMA_PATH = ROOT / "batterylog" / "schema" / "result-v2.json"
LEGACY_SCHEMA_PATH = ROOT / "batterylog" / "schema" / "result-v1.json"
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
        data_quality=config.data_quality,
        signal_mapping=config.signals,
    )
    return [not_evaluated, passed, failed]


def test_generated_results_validate_against_schema_v3(
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


def test_schema_artifact_matches_runtime_version(
    result_schema: dict[str, object],
) -> None:
    assert RESULT_SCHEMA_VERSION == 3
    assert SCHEMA_PATH.name == f"result-v{RESULT_SCHEMA_VERSION}.json"
    assert result_schema["title"] == "BatteryLog Analysis Result v3"
    assert result_schema["$id"] == (
        "https://raw.githubusercontent.com/CANWECAN/BatteryLog/"
        "v0.8.0/batterylog/schema/result-v3.json"
    )
    assert "/main/" not in str(result_schema["$id"])
    assert "/blob/" not in str(result_schema["$id"])

    properties = result_schema["properties"]
    assert isinstance(properties, dict)
    schema_version = properties["schema_version"]
    assert isinstance(schema_version, dict)
    assert schema_version["const"] == RESULT_SCHEMA_VERSION


def test_result_schema_v2_remains_frozen() -> None:
    schema = json.loads(V2_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)

    assert schema["title"] == "BatteryLog Analysis Result v2"
    assert schema["$id"] == (
        "https://raw.githubusercontent.com/CANWECAN/BatteryLog/"
        "v0.7.0/batterylog/schema/result-v2.json"
    )
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["schema_version"] == {"const": 2}
    assert "data_quality" not in properties
    assert "rows_input" not in properties
    assert "rows_excluded" not in properties


def test_no_strict_legacy_v1_schema_is_published() -> None:
    assert not LEGACY_SCHEMA_PATH.exists()


def test_schema_v3_accepts_data_quality_only_fail_and_all_excluded(
    validator: Draft202012Validator,
) -> None:
    config = DataQualityConfig(mode="exclude_invalid_rows")
    dq_only = analyze_battery_bytes(
        b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.8,3.79,25\n1,,3.79,25\n",
        limits=ValidationLimits(),
        data_quality=config,
    )
    all_excluded = analyze_battery_bytes(
        b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,bad,3.79,25\n",
        limits=ValidationLimits(cell_max_v=4.2),
        data_quality=config,
    )

    validator.validate(dq_only)
    validator.validate(all_excluded)
    assert dq_only["validation_status"] == "FAIL"
    assert dq_only["violations"] == []
    assert all_excluded["rows_analyzed"] == 0
    assert all_excluded["max_cell_voltage_v"] is None


def test_schema_v3_rejects_legacy_result_version_number(
    validator: Draft202012Validator,
) -> None:
    result = copy.deepcopy(analyze_battery_log(SAMPLE))
    result["schema_version"] = 2  # type: ignore[typeddict-item]

    with pytest.raises(ValidationError):
        validator.validate(result)


def test_schema_v3_rejects_data_quality_event_on_pass(
    validator: Draft202012Validator,
) -> None:
    result = copy.deepcopy(
        analyze_battery_log(
            SAMPLE,
            limits=ValidationLimits(imbalance_max_v=0.11),
        )
    )
    assert result["validation_status"] == "PASS"
    result["data_quality"]["events"].append(
        {
            "code": "MISSING_REQUIRED_VALUE",
            "start_row": 1,
            "end_row": 1,
            "signals": ["cell_1_v"],
            "affected_values": 1,
        }
    )

    with pytest.raises(ValidationError):
        validator.validate(result)


def test_schema_v3_rejects_non_null_extrema_when_all_rows_excluded(
    validator: Draft202012Validator,
) -> None:
    result = analyze_battery_bytes(
        b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,bad,3.79,25\n",
        limits=ValidationLimits(cell_max_v=4.2),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )
    payload = copy.deepcopy(result)
    payload["max_cell_voltage_v"] = 3.8

    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_schema_v3_rejects_excluded_rows_in_strict_mode(
    validator: Draft202012Validator,
) -> None:
    result = copy.deepcopy(analyze_battery_log(SAMPLE))
    result["rows_excluded"] = 1

    with pytest.raises(ValidationError):
        validator.validate(result)
