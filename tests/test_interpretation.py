import copy
import json
from dataclasses import FrozenInstanceError
from io import BytesIO
from pathlib import Path

import pytest

from batterylog import DataQualityConfig, ValidationLimits
from batterylog.analysis.core import analyze_battery_bytes
from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.interpretation import InterpretationReport
from batterylog.loaders import CsvFileLoader
from batterylog.reporting import render_json_result


@pytest.mark.parametrize(
    "limits,expected_status",
    [
        (ValidationLimits(), "NOT_EVALUATED"),
        (ValidationLimits(imbalance_max_v=0.5), "PASS"),
        (ValidationLimits(imbalance_max_v=0.05), "FAIL"),
    ],
)
def test_real_observations_do_not_become_physical_diagnoses(limits, expected_status):
    result = analyze_battery_bytes(
        b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.7,3.6,25\n1,3.8,3.6,25\n",
        limits=limits,
    )
    before = copy.deepcopy(result)
    before_json = render_json_result(result)
    report = InterpretationReport(engineering_status=result["validation_status"]).to_dict()
    assert report["engineering_status"] == expected_status
    assert report["diagnostic_claim"] is False
    assert [claim["claim"] for claim in report["claims"]] == [
        "CELL_SOC_IMBALANCE",
        "PARALLEL_BRANCH_FAULT_LOCATION",
        "SENSOR_VS_CELL_FAULT_ISOLATION",
    ]
    assert all(claim["status"] == "NOT_EVALUATED" for claim in report["claims"])
    assert all(
        "MEASUREMENT_CONTEXT_NOT_ASSESSED" in claim["reason_codes"] for claim in report["claims"]
    )
    assert result == before
    assert render_json_result(result) == before_json
    if expected_status == "FAIL":
        assert result["violations"][0]["code"] == "CELL_IMBALANCE_HIGH"


def test_data_quality_failure_is_retained_without_asserting_a_sensor_fault():
    result = analyze_battery_bytes(
        b"timestamp_s,cell_1_v,temp_c\n0,3.7,25\n1,3.7,bad\n2,3.7,25\n",
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )
    before = render_json_result(result)
    report = InterpretationReport(engineering_status=result["validation_status"]).to_dict()
    assert report["engineering_status"] == "FAIL"
    isolation = next(
        item for item in report["claims"] if item["claim"] == "SENSOR_VS_CELL_FAULT_ISOLATION"
    )
    assert isolation["status"] == "NOT_EVALUATED"
    assert "FAULT_ISOLATION_MODEL_NOT_AVAILABLE" in isolation["reason_codes"]
    assert render_json_result(result) == before


def test_exports_cannot_mutate_report_or_share_nested_evidence():
    report = InterpretationReport(engineering_status="FAIL")
    expected = report.to_dict()
    exported = report.to_dict()
    exported["engineering_status"] = "PASS"
    exported["claims"][0]["reason_codes"].clear()
    exported["claims"].pop()
    assert report.to_dict() == expected
    assert json.loads(json.dumps(expected, allow_nan=False)) == expected
    with pytest.raises(FrozenInstanceError):
        report.engineering_status = "PASS"
    with pytest.raises(FrozenInstanceError):
        report.diagnostic_claim = True


@pytest.mark.parametrize("status", [True, False, None, 1, "pass", "ERROR", [], {"PASS": 1}])
def test_invalid_engineering_status_is_rejected_without_coercion(status):
    with pytest.raises(ValueError, match="engineering_status"):
        InterpretationReport(engineering_status=status)


def test_caller_cannot_enable_diagnosis_or_replace_the_schema_version():
    with pytest.raises(TypeError):
        InterpretationReport(engineering_status="PASS", diagnostic_claim=True)
    with pytest.raises(TypeError):
        InterpretationReport(engineering_status="PASS", interpretation_schema_version=2)


@pytest.mark.parametrize("chunk_rows", [1, 2, 100])
def test_whole_and_streamed_inputs_keep_the_same_independent_outcome(chunk_rows):
    data = b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.7,3.6,25\n1,3.8,3.6,25\n2,3.7,3.6,25\n"
    limits = ValidationLimits(imbalance_max_v=0.05)
    whole = analyze_battery_bytes(data, limits=limits)
    streamed = analyze_measurement_loader(
        CsvFileLoader(BytesIO(data), chunk_rows=chunk_rows), limits=limits
    )
    whole_json = render_json_result(whole)
    assert whole_json == render_json_result(streamed)
    assert (
        InterpretationReport(whole["validation_status"]).to_dict()
        == InterpretationReport(streamed["validation_status"]).to_dict()
    )
    assert render_json_result(whole) == whole_json
    assert render_json_result(streamed) == whole_json


@pytest.mark.parametrize("path", sorted(Path(__file__).with_name("golden").glob("*.json")))
def test_existing_result_goldens_remain_byte_equivalent_after_annotation(path):
    source = path.read_text(encoding="utf-8")
    result = json.loads(source)
    before = render_json_result(result)
    InterpretationReport(engineering_status=result["validation_status"]).to_dict()
    assert render_json_result(result) == before
    assert path.read_text(encoding="utf-8") == source
