"""Smoke-test an installed distribution from outside the source checkout."""

import json
import subprocess
import sys
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

import jsonschema

from batterylog.analysis.report_series import ReportSeriesCollector

expected_version, sample = sys.argv[1:]
assert version("batterylog") == expected_version
empty_series = ReportSeriesCollector(max_points=12).finish()
assert empty_series.source_rows == 0
assert empty_series.points == ()
schema = json.loads(files("batterylog").joinpath("schema/result-v2.json").read_text())
jsonschema.Draft202012Validator.check_schema(schema)
completed = subprocess.run(
    [
        str(Path(sys.executable).with_name("batterylog")),
        str(Path(sample).resolve()),
        "--cell-max-v",
        "5",
    ],
    check=True,
    capture_output=True,
    text=True,
)
result = json.loads(completed.stdout)
jsonschema.validate(result, schema)
assert result["validation_status"] == "PASS"
print(f"Installed BatteryLog {expected_version}: CLI and packaged schema verified")
