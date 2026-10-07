"""Smoke-test installed BatteryLog MDF/MF4 support outside the source checkout."""

import io
import json
import sys
from contextlib import redirect_stdout
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import jsonschema
import numpy as np
from asammdf import MDF, Signal

from batterylog import (
    AnalysisService,
    FailureModelConfig,
    SourceUnits,
    TemperatureRiseConfig,
    ValidationConfig,
    ValidationLimits,
    analyze_battery_log,
    inspect_measurement,
    normalize_measurement,
    validate_result_semantics,
)
from batterylog.__main__ import run

expected_version = sys.argv[1]
assert version("batterylog") == expected_version
schema = json.loads(files("batterylog").joinpath("schema/result-v8.json").read_text())
validator = jsonschema.Draft202012Validator(schema)
failure_schema = json.loads(files("batterylog").joinpath("schema/result-v9.json").read_text())

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    source = root / "artifact-smoke.mf4"
    report = root / "artifact-smoke.html"
    timestamps = np.array([10.0, 11.0, 12.0])
    raw_source = root / "millivolts.mf4"
    with MDF(version="4.10") as raw_mdf:
        raw_mdf.append(
            [
                Signal(np.array([3500.0, 4000.0, 3500.0]), timestamps, name="cell_1_v", unit="mV"),
                Signal(np.array([298.15, 300.15, 298.15]), timestamps, name="temp_c", unit="K"),
            ],
            common_timebase=True,
        )
        raw_mdf.save(raw_source, overwrite=True)
    normalized = normalize_measurement(
        raw_source, root / "prepared", units=SourceUnits("s", "mV", "K")
    )
    normalized_result = AnalysisService().analyze_path(root / "prepared/normalized.csv").result
    assert normalized["rows_written"] == 3
    assert normalized_result["max_cell_voltage_v"] == 4.0
    assert normalized_result["max_temperature_c"] == 27.0

    mdf = MDF(version="4.10")
    try:
        mdf.append(
            [
                Signal(
                    np.array([3.80, 4.30, 3.80]),
                    timestamps,
                    name="cell_1_v",
                    unit="V",
                ),
                Signal(
                    np.array([3.79, 3.90, 3.79]),
                    timestamps,
                    name="cell_2_v",
                    unit="V",
                ),
                Signal(
                    np.array([25.0, 56.0, 25.0]),
                    timestamps,
                    name="temp_1_c",
                    unit="degC",
                ),
            ],
            common_timebase=True,
        )
        mdf.save(source, overwrite=True)
    finally:
        mdf.close()

    inspection = inspect_measurement(source)
    assert inspection["metadata_status"] == "OK"
    assert inspection["time_basis"] == "mdf_master"
    assert inspection["analysis_performed"] is False
    inspected_stdout = io.StringIO()
    with redirect_stdout(inspected_stdout):
        inspected_code = run([str(source), "--inspect"])
    assert inspected_code == 0
    assert json.loads(inspected_stdout.getvalue()) == inspection

    result = analyze_battery_log(
        source,
        limits=ValidationLimits(cell_max_v=4.2, temperature_max_c=55.0),
    )
    validator.validate(result)
    validate_result_semantics(result)
    service = AnalysisService(
        ValidationConfig(limits=ValidationLimits(cell_max_v=4.2, temperature_max_c=55.0))
    )
    output = service.analyze_path(source, report_max_points=20)
    assert output.result == result
    assert output.report_series is not None
    assert output.report_series.source_rows == 3
    with source.open("rb") as handle:
        file_output = service.analyze_file(handle, source_name=source.name, report_max_points=20)
        assert not handle.closed
        assert file_output == output
    assert result["validation_status"] == "FAIL"
    assert result["rows_analyzed"] == 3
    assert result["violations"][0]["start_time_s"] == 11.0

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = run(
            [
                str(source),
                "--cell-max-v",
                "5.0",
                "--temp-max-c",
                "60.0",
                "--report",
                str(report),
            ]
        )

    payload = json.loads(stdout.getvalue())
    validator.validate(payload)
    validate_result_semantics(payload)
    assert exit_code == 0
    assert payload["validation_status"] == "PASS"
    assert report.exists()
    html = report.read_text(encoding="utf-8")
    assert source.name in html
    assert html.count('class="timeseries-chart"') == 3
    assert "Cell-voltage envelope" in html

    model_result = (
        AnalysisService(
            ValidationConfig(
                failure_models=FailureModelConfig(
                    2, temperature_rise=TemperatureRiseConfig(60, 0.1)
                )
            )
        )
        .analyze_path(source)
        .result
    )
    jsonschema.validate(model_result, failure_schema)
    validate_result_semantics(model_result)
    assert model_result["schema_version"] == 9
    assert model_result["validation_status"] == "FAIL"
    model_event = model_result["failure_models"]["evaluations"][0]["events"][0]
    assert model_event["code"] == "TEMPERATURE_RISE_HIGH"
    assert model_event["measured_value"] == 1860
    assert model_event["evidence"]["previous_time_s"] == 10

    inputs = root / "batch-inputs"
    inputs.mkdir()
    (inputs / source.name).write_bytes(source.read_bytes())
    batch_out = root / "batch-results"
    batch_stdout = io.StringIO()
    with redirect_stdout(batch_stdout):
        batch_code = run(
            [
                str(inputs),
                "--batch",
                "--cell-max-v",
                "5.0",
                "--temp-max-c",
                "60.0",
                "--output-dir",
                str(batch_out),
            ]
        )
    batch_summary = json.loads(batch_stdout.getvalue())
    assert batch_code == 0
    assert batch_summary["files"][0]["status"] == "PASS"
    batch_result = json.loads((batch_out / batch_summary["files"][0]["result_json"]).read_text())
    validator.validate(batch_result)
    validate_result_semantics(batch_result)
    assert batch_result == payload
    assert (batch_out / batch_summary["files"][0]["report_html"]).is_file()
    assert (batch_out / "summary.csv").is_file()

print(
    f"Installed BatteryLog {expected_version}: MF4 extra, inspection, service/path/handle parity, schema/semantics and HTML plots verified"
)
