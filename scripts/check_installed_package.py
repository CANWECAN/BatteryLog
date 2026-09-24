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
schema = json.loads(files("batterylog").joinpath("schema/result-v7.json").read_text())
legacy_v6 = json.loads(files("batterylog").joinpath("schema/result-v6.json").read_text())
legacy_v5 = json.loads(files("batterylog").joinpath("schema/result-v5.json").read_text())
legacy_v4 = json.loads(files("batterylog").joinpath("schema/result-v4.json").read_text())
legacy_v3 = json.loads(files("batterylog").joinpath("schema/result-v3.json").read_text())
legacy_v2 = json.loads(files("batterylog").joinpath("schema/result-v2.json").read_text())
jsonschema.Draft202012Validator.check_schema(schema)
jsonschema.Draft202012Validator.check_schema(legacy_v6)
jsonschema.Draft202012Validator.check_schema(legacy_v5)
jsonschema.Draft202012Validator.check_schema(legacy_v4)
jsonschema.Draft202012Validator.check_schema(legacy_v3)
jsonschema.Draft202012Validator.check_schema(legacy_v2)
assert schema["properties"]["schema_version"]["const"] == 7
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

print(f"Installed BatteryLog {expected_version}: CLI, schema, and HTML plots verified")
