"""Smoke-test an installed distribution from outside the source checkout."""

import json
import subprocess
import sys
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import jsonschema

from batterylog.analysis.report_series import ReportSeriesCollector

expected_version, sample = sys.argv[1:]
assert version("batterylog") == expected_version
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
with TemporaryDirectory() as directory:
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
    assert result["validation_status"] == "PASS"
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
    assert mismatch_result["rules_evaluated"] == ["PACK_VOLTAGE_CELL_SUM_MISMATCH"]
    assert mismatch_result["violations"][0]["signed_error_v"] == 0.25

print(f"Installed BatteryLog {expected_version}: CLI, schema, rules, and HTML plots verified")
