"""Smoke-test installed BatteryLog MDF/MF4 support outside the source checkout."""

import io
import json
import sys
from contextlib import redirect_stdout
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from asammdf import MDF, Signal

from batterylog import ValidationLimits, analyze_battery_log
from batterylog.__main__ import run

expected_version = sys.argv[1]
assert version("batterylog") == expected_version

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    source = root / "artifact-smoke.mf4"
    report = root / "artifact-smoke.html"
    timestamps = np.array([10.0, 11.0, 12.0])

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

    result = analyze_battery_log(
        source,
        limits=ValidationLimits(cell_max_v=4.2, temperature_max_c=55.0),
    )
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
    assert exit_code == 0
    assert payload["validation_status"] == "PASS"
    assert report.exists()
    assert source.name in report.read_text(encoding="utf-8")

print(f"Installed BatteryLog {expected_version}: MF4 extra and report path verified")
