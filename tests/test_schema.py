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
SCHEMA_PATH = ROOT / "batterylog" / "schema" / "result-v8.json"
V7_SCHEMA_PATH = ROOT / "batterylog" / "schema" / "result-v7.json"
V6_SCHEMA_PATH = ROOT / "batterylog" / "schema" / "result-v6.json"
V5_SCHEMA_PATH = ROOT / "batterylog" / "schema" / "result-v5.json"
V4_SCHEMA_PATH = ROOT / "batterylog" / "schema" / "result-v4.json"
V3_SCHEMA_PATH = ROOT / "batterylog" / "schema" / "result-v3.json"
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


def test_generated_results_validate_against_schema_v7(
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


def test_schema_v7_validates_pack_measurement_provenance_and_extrema(
    validator: Draft202012Validator,
) -> None:
    result = analyze_battery_bytes(
        b"timestamp_s,pack_current_a,pack_voltage_v,cell_1_v,temp_c\n"
        b"0,-10,398,3.8,25\n"
        b"1,20,405,3.9,26\n"
    )

    validator.validate(result)
    assert result["signal_mapping"]["pack_current_source"] == "pack_current_a"
    assert result["signal_mapping"]["pack_voltage_source"] == "pack_voltage_v"

    missing_provenance = copy.deepcopy(result)
    missing_provenance["signal_mapping"]["pack_current_source"] = None
    with pytest.raises(ValidationError):
        validator.validate(missing_provenance)

    invalid_canonical_source = copy.deepcopy(result)
    invalid_canonical_source["signal_mapping"]["pack_voltage_source"] = "VendorVoltage"
    with pytest.raises(ValidationError):
        validator.validate(invalid_canonical_source)


def test_schema_v7_validates_pack_overcurrent_contract(
    validator: Draft202012Validator,
) -> None:
    result = analyze_battery_bytes(
        b"timestamp_s,pack_current_a,cell_1_v,temp_c\n0,-61,3.8,25\n1,121,3.8,25\n",
        limits=ValidationLimits(
            pack_charge_max_a=60.0,
            pack_discharge_max_a=120.0,
            pack_current_positive_direction="discharge",
        ),
    )

    validator.validate(result)
    assert {event["unit"] for event in result["violations"]} == {"A"}

    missing_direction = copy.deepcopy(result)
    missing_direction["limits_applied"]["pack_current_positive_direction"] = None
    with pytest.raises(ValidationError):
        validator.validate(missing_direction)

    wrong_unit = copy.deepcopy(result)
    wrong_unit["violations"][0]["unit"] = "V"
    with pytest.raises(ValidationError):
        validator.validate(wrong_unit)


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


def test_schema_v7_requires_violation_event_evidence(
    validator: Draft202012Validator,
) -> None:
    result = analyze_battery_bytes(
        b"timestamp_s,cell_1_v,temp_c\n0,4.3,25\n1,4.4,25\n",
        limits=ValidationLimits(cell_max_v=4.2),
    )
    validator.validate(result)

    event = result["violations"][0]
    assert event["sample_count"] == 2
    assert event["duration_s"] == pytest.approx(1.0)
    assert event["peak_excursion"] == pytest.approx(0.2)

    for field in ("sample_count", "duration_s", "peak_excursion"):
        missing = copy.deepcopy(result)
        missing["violations"][0].pop(field)
        with pytest.raises(ValidationError):
            validator.validate(missing)

    invalid_count = copy.deepcopy(result)
    invalid_count["violations"][0]["sample_count"] = 0
    with pytest.raises(ValidationError):
        validator.validate(invalid_count)

    for field in ("duration_s", "peak_excursion"):
        negative = copy.deepcopy(result)
        negative["violations"][0][field] = -1.0
        with pytest.raises(ValidationError):
            validator.validate(negative)


def test_schema_artifact_matches_runtime_version(
    result_schema: dict[str, object],
) -> None:
    assert RESULT_SCHEMA_VERSION == 8
    assert SCHEMA_PATH.name == f"result-v{RESULT_SCHEMA_VERSION}.json"
    assert result_schema["title"] == "BatteryLog Analysis Result v8"
    assert result_schema["description"] == (
        "BatteryLog result schema version 8 with pack-voltage/cell-sum plausibility evidence "
        "and mismatch-rule support."
    )
    assert result_schema["$id"] == (
        "https://raw.githubusercontent.com/CANWECAN/BatteryLog/"
        "v0.9.1/batterylog/schema/result-v8.json"
    )
    assert "/main/" not in str(result_schema["$id"])
    assert "/blob/" not in str(result_schema["$id"])

    properties = result_schema["properties"]
    assert isinstance(properties, dict)
    schema_version = properties["schema_version"]
    assert isinstance(schema_version, dict)
    assert schema_version["const"] == RESULT_SCHEMA_VERSION


def test_result_schema_v7_remains_frozen() -> None:
    schema = json.loads(V7_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == (
        "https://raw.githubusercontent.com/CANWECAN/BatteryLog/"
        "v0.9.0/batterylog/schema/result-v7.json"
    )
    assert schema["properties"]["schema_version"] == {"const": 7}
    assert "pack_voltage_cell_sum_peak" not in schema["properties"]
    assert "PACK_VOLTAGE_CELL_SUM_MISMATCH" not in schema["$defs"]["ruleCode"]["enum"]


def test_result_schema_v6_remains_frozen() -> None:
    schema = json.loads(V6_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)

    assert schema["title"] == "BatteryLog Analysis Result v6"
    assert schema["$id"] == (
        "https://raw.githubusercontent.com/CANWECAN/BatteryLog/"
        "v0.9.0/batterylog/schema/result-v6.json"
    )
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["schema_version"] == {"const": 6}

    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    violation_event = definitions["violationEvent"]
    assert isinstance(violation_event, dict)
    required = violation_event["required"]
    event_properties = violation_event["properties"]
    assert isinstance(required, list)
    assert isinstance(event_properties, dict)
    for field in ("sample_count", "duration_s", "peak_excursion"):
        assert field not in required
        assert field not in event_properties


def test_result_schema_v4_remains_frozen() -> None:
    schema = json.loads(V4_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)

    assert schema["title"] == "BatteryLog Analysis Result v4"
    assert schema["$id"] == (
        "https://raw.githubusercontent.com/CANWECAN/BatteryLog/"
        "v0.9.0/batterylog/schema/result-v4.json"
    )
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["schema_version"] == {"const": 4}
    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    rule_codes = definitions["ruleCode"]
    assert isinstance(rule_codes, dict)
    assert "PACK_CHARGE_OVERCURRENT" not in rule_codes["enum"]
    assert "PACK_DISCHARGE_OVERCURRENT" not in rule_codes["enum"]


def test_result_schema_v3_remains_frozen() -> None:
    schema = json.loads(V3_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)

    assert schema["title"] == "BatteryLog Analysis Result v3"
    assert schema["$id"] == (
        "https://raw.githubusercontent.com/CANWECAN/BatteryLog/"
        "v0.8.0/batterylog/schema/result-v3.json"
    )
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["schema_version"] == {"const": 3}
    assert "max_pack_current_a" not in properties
    assert "max_pack_voltage_v" not in properties


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


def test_schema_v7_accepts_data_quality_only_fail_and_all_excluded(
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


def test_schema_v7_rejects_legacy_result_version_number(
    validator: Draft202012Validator,
) -> None:
    result = copy.deepcopy(analyze_battery_log(SAMPLE))
    result["schema_version"] = 2  # type: ignore[typeddict-item]

    with pytest.raises(ValidationError):
        validator.validate(result)


def test_schema_v7_rejects_data_quality_event_on_pass(
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


def test_schema_v7_rejects_non_null_extrema_when_all_rows_excluded(
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


def test_schema_v7_rejects_data_quality_events_without_excluded_rows(
    validator: Draft202012Validator,
) -> None:
    result = analyze_battery_bytes(
        b"timestamp_s,cell_1_v,temp_c\n0,3.8,25\n1,bad,25\n",
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )
    payload = copy.deepcopy(result)
    payload["rows_analyzed"] = 2
    payload["rows_excluded"] = 0

    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_schema_v7_rejects_rule_violations_when_no_rows_were_analyzed(
    validator: Draft202012Validator,
) -> None:
    all_excluded = analyze_battery_bytes(
        b"timestamp_s,cell_1_v,temp_c\n0,bad,25\n",
        limits=ValidationLimits(cell_max_v=4.2),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )
    failed_rule = analyze_battery_bytes(
        b"timestamp_s,cell_1_v,temp_c\n0,4.3,25\n",
        limits=ValidationLimits(cell_max_v=4.2),
    )
    payload = copy.deepcopy(all_excluded)
    payload["violations"] = copy.deepcopy(failed_rule["violations"])

    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_generated_results_satisfy_semantic_row_accounting() -> None:
    results = _results_for_all_statuses()
    results.append(
        analyze_battery_bytes(
            b"timestamp_s,cell_1_v,temp_c\n0,3.8,25\n1,bad,25\n",
            data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
        )
    )

    for result in results:
        assert result["rows_input"] == result["rows_analyzed"] + result["rows_excluded"]
        if result["rows_analyzed"] == 0:
            assert result["violations"] == []
        for event in result["violations"]:
            assert event["sample_count"] >= 1
            assert event["duration_s"] == pytest.approx(event["end_time_s"] - event["start_time_s"])
            assert event["peak_excursion"] == pytest.approx(
                abs(event["measured_value"] - event["limit_value"])
            )
        for event in result["data_quality"]["events"]:
            assert 1 <= event["start_row"] <= event["end_row"] <= result["rows_input"]
            row_span = event["end_row"] - event["start_row"] + 1
            assert event["affected_values"] == row_span * len(event["signals"])


def test_schema_v7_rejects_excluded_rows_in_strict_mode(
    validator: Draft202012Validator,
) -> None:
    result = copy.deepcopy(analyze_battery_log(SAMPLE))
    result["rows_excluded"] = 1

    with pytest.raises(ValidationError):
        validator.validate(result)


def test_schema_v7_validates_temperature_spread_contract(
    validator: Draft202012Validator,
) -> None:
    result = analyze_battery_bytes(
        b"timestamp_s,temp_1_c,temp_2_c,cell_1_v\n0,20,30,3.8\n1,22,40,3.8\n",
        limits=ValidationLimits(temperature_spread_max_c=10.0),
    )

    validator.validate(result)
    assert result["max_temperature_spread_c"] == pytest.approx(18.0)
    assert result["violations"][0]["code"] == "TEMPERATURE_SPREAD_HIGH"
    assert result["violations"][0]["unit"] == "degC"
    assert len(result["violations"][0]["signals"]) == 2

    negative_limit = copy.deepcopy(result)
    negative_limit["limits_applied"]["temperature_spread_max_c"] = -1.0
    with pytest.raises(ValidationError):
        validator.validate(negative_limit)


def test_result_schema_v5_remains_frozen() -> None:
    schema = json.loads(V5_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)

    assert schema["title"] == "BatteryLog Analysis Result v5"
    assert schema["$id"] == (
        "https://raw.githubusercontent.com/CANWECAN/BatteryLog/"
        "v0.9.0/batterylog/schema/result-v5.json"
    )
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["schema_version"] == {"const": 5}
    assert "max_temperature_spread_c" not in properties
    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    assert "TEMPERATURE_SPREAD_HIGH" not in definitions["ruleCode"]["enum"]
