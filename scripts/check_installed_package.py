"""Smoke-test an installed distribution from outside the source checkout."""

import json
import subprocess
import sys
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import jsonschema

from batterylog import (
    AnalysisService,
    FailureModelConfig,
    SourceUnits,
    SustainedImbalanceConfig,
    ValidationConfig,
    ValidationLimits,
    inspect_measurement,
    normalize_measurement,
    validate_result_semantics,
)
from batterylog.analysis.core import analyze_battery_bytes
from batterylog.analysis.report_series import ReportSeriesCollector
from batterylog.desktop_demo import create_demo

expected_version, sample = sys.argv[1:]
assert version("batterylog") == expected_version
gui_help = subprocess.run(
    [str(Path(sys.executable).with_name("batterylog-gui")), "--help"],
    check=True,
    capture_output=True,
    text=True,
)
assert "desktop launcher" in gui_help.stdout
empty_series = ReportSeriesCollector(max_points=14).finish()
assert empty_series.source_rows == 0
assert empty_series.points == ()
schema = json.loads(files("batterylog").joinpath("schema/result-v8.json").read_text())
legacy_v7 = json.loads(files("batterylog").joinpath("schema/result-v7.json").read_text())
legacy_v6 = json.loads(files("batterylog").joinpath("schema/result-v6.json").read_text())
legacy_v5 = json.loads(files("batterylog").joinpath("schema/result-v5.json").read_text())
legacy_v4 = json.loads(files("batterylog").joinpath("schema/result-v4.json").read_text())
legacy_v3 = json.loads(files("batterylog").joinpath("schema/result-v3.json").read_text())
legacy_v2 = json.loads(files("batterylog").joinpath("schema/result-v2.json").read_text())
jsonschema.Draft202012Validator.check_schema(schema)
jsonschema.Draft202012Validator.check_schema(legacy_v7)
jsonschema.Draft202012Validator.check_schema(legacy_v6)
jsonschema.Draft202012Validator.check_schema(legacy_v5)
jsonschema.Draft202012Validator.check_schema(legacy_v4)
jsonschema.Draft202012Validator.check_schema(legacy_v3)
jsonschema.Draft202012Validator.check_schema(legacy_v2)
assert schema["properties"]["schema_version"]["const"] == 8
assert legacy_v7["properties"]["schema_version"]["const"] == 7
assert legacy_v6["properties"]["schema_version"]["const"] == 6
assert legacy_v5["properties"]["schema_version"]["const"] == 5
assert legacy_v4["properties"]["schema_version"]["const"] == 4
assert legacy_v3["properties"]["schema_version"]["const"] == 3
assert legacy_v2["properties"]["schema_version"]["const"] == 2
failure_schema = json.loads(files("batterylog").joinpath("schema/result-v9.json").read_text())
model_config_schema = json.loads(
    files("batterylog").joinpath("schema/failure-config-v1.json").read_text()
)
jsonschema.Draft202012Validator.check_schema(failure_schema)
jsonschema.Draft202012Validator.check_schema(model_config_schema)
failure_result = analyze_battery_bytes(
    b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.5,3.25,25\n1,3.5,3.25,25\n2,3.5,3.25,25\n",
    failure_models=FailureModelConfig(1, sustained_imbalance=SustainedImbalanceConfig(0.125, 2)),
)
jsonschema.validate(failure_result, failure_schema)
validate_result_semantics(failure_result)
assert failure_result["validation_status"] == "FAIL"
assert failure_result["failure_models"]["evaluations"][0]["events"][0]["duration_s"] == 2
with TemporaryDirectory() as directory:
    demo = create_demo(Path(directory))
    demo_report = demo / "report.html"
    demo_run = subprocess.run(
        [
            sys.executable,
            "-m",
            "batterylog",
            str(demo / "synthetic_demo.csv"),
            "--config",
            str(demo / "validation.yaml"),
            "--report",
            str(demo_report),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert demo_run.returncode == 1
    demo_result = json.loads(demo_run.stdout)
    assert demo_result["validation_status"] == "FAIL"
    assert {v["code"] for v in demo_result["violations"]} == {
        "CELL_IMBALANCE_HIGH",
        "TEMPERATURE_HIGH",
    }
    assert len(demo_result["violations"]) == 2
    assert demo_report.is_file()
    normalized = normalize_measurement(
        sample, Path(directory) / "prepared", units=SourceUnits("s", "V", "degC")
    )
    assert normalized["analysis_performed"] is False
    assert (
        AnalysisService().analyze_path(Path(directory) / "prepared/normalized.csv").result
        == AnalysisService().analyze_path(sample).result
    )
    normalized_cli = subprocess.run(
        [
            str(Path(sys.executable).with_name("batterylog")),
            str(Path(sample).resolve()),
            "--normalize",
            "--time-unit",
            "s",
            "--cell-voltage-unit",
            "V",
            "--temperature-unit",
            "degC",
            "--output-dir",
            str(Path(directory) / "prepared-cli"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(normalized_cli.stdout)["rows_written"] == normalized["rows_written"]
    inspection = inspect_measurement(sample)
    assert inspection["metadata_status"] == "OK"
    assert inspection["analysis_performed"] is False
    inspected = subprocess.run(
        [
            str(Path(sys.executable).with_name("batterylog")),
            str(Path(sample).resolve()),
            "--inspect",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(inspected.stdout) == inspection
    report = Path(directory) / "report.html"
    completed = subprocess.run(
        [
            str(Path(sys.executable).with_name("batterylog")),
            str(Path(sample).resolve()),
            "--cell-max-v",
            "5",
            "--report",
            str(report),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    jsonschema.validate(result, schema)
    validate_result_semantics(result)
    assert result["validation_status"] == "PASS"
    service_output = AnalysisService(
        ValidationConfig(limits=ValidationLimits(cell_max_v=5.0))
    ).analyze_path(sample, report_max_points=20)
    assert service_output.result == result
    assert service_output.report_series is not None
    assert service_output.report_series.source_rows == result["rows_analyzed"]
    with Path(sample).open("rb") as handle:
        file_output = AnalysisService(
            ValidationConfig(limits=ValidationLimits(cell_max_v=5.0))
        ).analyze_file(handle, source_name=Path(sample).name, report_max_points=20)
        assert not handle.closed
        assert file_output == service_output
    html = report.read_text(encoding="utf-8")
    assert html.count('class="timeseries-chart"') == 3
    assert "Cell-voltage envelope" in html

    mismatch = Path(directory) / "pack-cell-mismatch.csv"
    mismatch.write_text(
        "timestamp_s,cell_1_v,cell_2_v,temp_c,pack_voltage_v\n"
        "0,3.5,3.5,25,7.0\n"
        "1,3.5,3.5,25,7.25\n",
        encoding="utf-8",
    )
    mismatch_run = subprocess.run(
        [
            str(Path(sys.executable).with_name("batterylog")),
            str(mismatch),
            "--pack-cell-sum-max-delta-v",
            "0.125",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert mismatch_run.returncode == 1
    mismatch_result = json.loads(mismatch_run.stdout)
    jsonschema.validate(mismatch_result, schema)
    validate_result_semantics(mismatch_result)
    assert mismatch_result["rules_evaluated"] == ["PACK_VOLTAGE_CELL_SUM_MISMATCH"]
    assert mismatch_result["violations"][0]["signed_error_v"] == 0.25

    inputs = Path(directory) / "batch-inputs"
    inputs.mkdir()
    prepared_csv = Path(directory) / "prepared/normalized.csv"
    assert inspect_measurement(prepared_csv)["metadata_status"] == "OK"
    (inputs / "summary.csv").write_bytes(prepared_csv.read_bytes())
    batch_out = Path(directory) / "batch-results"
    batch_run = subprocess.run(
        [
            str(Path(sys.executable).with_name("batterylog")),
            str(inputs),
            "--batch",
            "--cell-max-v",
            "5",
            "--output-dir",
            str(batch_out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    batch_summary = json.loads(batch_run.stdout)
    assert batch_summary["batch_schema_version"] == 1
    assert batch_summary["files"][0]["status"] == "PASS"
    assert batch_summary["files"][0]["result_json"] == "files/summary.csv/result.json"
    batch_result = json.loads((batch_out / batch_summary["files"][0]["result_json"]).read_text())
    jsonschema.validate(batch_result, schema)
    validate_result_semantics(batch_result)
    assert batch_result == result
    assert (batch_out / batch_summary["files"][0]["report_html"]).is_file()
    assert (batch_out / "summary.csv").is_file()

print(
    f"Installed BatteryLog {expected_version}: normalization/inspection/batch flow, service, CLI, schema, rules and HTML plots verified"
)
