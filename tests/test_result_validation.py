import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from batterylog import ValidationLimits, validate_result_semantics
from batterylog.analysis.core import analyze_battery_bytes

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "batterylog/schema/result-v8.json").read_text("utf-8"))
STRUCTURAL = Draft202012Validator(SCHEMA)


def _golden(name: str) -> dict:
    return json.loads((ROOT / "tests/golden" / name).read_text("utf-8"))


@pytest.mark.parametrize("path", sorted((ROOT / "tests/golden").glob("*.json")))
def test_fixed_goldens_pass_without_changing_serialized_evidence(path) -> None:
    result = json.loads(path.read_text("utf-8"))
    STRUCTURAL.validate(result)
    before = copy.deepcopy(result)
    assert validate_result_semantics(result) is None
    assert result == before


def _passing_result() -> dict:
    return analyze_battery_bytes(
        b"timestamp_s,cell_1_v,temp_c\n0,3.5,25\n",
        limits=ValidationLimits(cell_max_v=4.2, temperature_max_c=55.0),
    )


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda r: r["limits_applied"].update(cell_max_v=None), "rules_evaluated"),
        (lambda r: r["rules_evaluated"].remove("CELL_OVERVOLTAGE"), "rules_evaluated"),
        (lambda r: r["rules_evaluated"].append("CELL_UNDERVOLTAGE"), "rules_evaluated"),
        (lambda r: r["limits_applied"].update(imbalance_max_v=-0.1), "imbalance_max_v"),
        (lambda r: r["comparison_policy"].update(relative_tolerance=0.5), "comparison_policy"),
        (lambda r: r["comparison_policy"].update(absolute_tolerance=0.1), "comparison_policy"),
        (lambda r: r.update(rows_input=2), "rows_input"),
    ],
)
def test_known_schema_gaps_are_rejected_by_semantic_checks(mutation, message) -> None:
    payload = _passing_result()
    mutation(payload)
    # Demonstrate the published schema really permits each mutation.
    STRUCTURAL.validate(payload)
    before = copy.deepcopy(payload)
    with pytest.raises(ValueError, match=message):
        validate_result_semantics(payload)
    assert payload == before


def test_inactive_violation_is_rejected_even_with_consistent_rule_list() -> None:
    payload = _golden("semantic_multi_rule_fail.json")
    payload["violations"][1]["code"] = "CELL_UNDERVOLTAGE"
    STRUCTURAL.validate(payload)
    with pytest.raises(ValueError, match=r"violations\[1\].code"):
        validate_result_semantics(payload)


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda e: e.update(start_row=3), "start_row"),
        (lambda e: e.update(end_row=4), "end_row"),
        (lambda e: e.update(affected_values=2), "affected_values"),
        (lambda e: e["signals"].append("cell_1_v"), "affected_values"),
    ],
)
def test_data_quality_bounds_and_value_counts_are_checked(mutation, message) -> None:
    payload = _golden("semantic_data_quality_fail.json")
    mutation(payload["data_quality"]["events"][0])
    STRUCTURAL.validate(payload)
    with pytest.raises(ValueError, match=message):
        validate_result_semantics(payload)


def test_multiple_defect_classes_can_overlap_one_excluded_row() -> None:
    payload = _golden("semantic_data_quality_fail.json")
    defect = copy.deepcopy(payload["data_quality"]["events"][0])
    defect.update(code="NON_FINITE_REQUIRED_VALUE", signals=["cell_1_v"])
    payload["data_quality"]["events"].append(defect)
    STRUCTURAL.validate(payload)
    validate_result_semantics(payload)
    assert payload["rows_excluded"] == 1  # affected values are not excluded rows


def test_rule_order_is_not_a_new_wire_requirement() -> None:
    payload = _passing_result()
    payload["rules_evaluated"].reverse()
    STRUCTURAL.validate(payload)
    validate_result_semantics(payload)


def test_other_schema_versions_are_not_silently_accepted() -> None:
    payload = _passing_result()
    payload["schema_version"] = 7
    with pytest.raises(ValueError, match="version 8 only"):
        validate_result_semantics(payload)


@pytest.mark.parametrize(
    "limits,expected_code",
    [
        (ValidationLimits(imbalance_max_v=0.1), "CELL_IMBALANCE_HIGH"),
        (ValidationLimits(cell_max_v=4.2), "CELL_OVERVOLTAGE"),
        (ValidationLimits(cell_min_v=3.0), "CELL_UNDERVOLTAGE"),
        (ValidationLimits(temperature_max_c=55.0), "TEMPERATURE_HIGH"),
        (ValidationLimits(temperature_min_c=-20.0), "TEMPERATURE_LOW"),
        (ValidationLimits(temperature_spread_max_c=10.0), "TEMPERATURE_SPREAD_HIGH"),
        (
            ValidationLimits(pack_charge_max_a=10.0, pack_current_positive_direction="charge"),
            "PACK_CHARGE_OVERCURRENT",
        ),
        (
            ValidationLimits(
                pack_discharge_max_a=20.0, pack_current_positive_direction="discharge"
            ),
            "PACK_DISCHARGE_OVERCURRENT",
        ),
        (
            ValidationLimits(pack_voltage_cell_sum_max_delta_v=0.125),
            "PACK_VOLTAGE_CELL_SUM_MISMATCH",
        ),
    ],
)
def test_all_active_rule_roles_accept_the_existing_producer(limits, expected_code) -> None:
    result = analyze_battery_bytes(
        b"timestamp_s,cell_1_v,cell_2_v,temp_1_c,temp_2_c,pack_current_a,pack_voltage_v\n"
        b"0,3.5,3.5,25,25,0,7\n",
        limits=limits,
    )
    STRUCTURAL.validate(result)
    assert result["rules_evaluated"] == [expected_code]
    validate_result_semantics(result)
