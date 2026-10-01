"""Recheck the retained CORA cycle-229 CSVs through the packaged CLI."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
out = root / "dist" / "quality-review"
stage = sys.argv[1]
config = out / "cora.yaml"
config.write_text(
    "schema_version: 6\nlimits:\n  pack_voltage:\n    cell_sum_max_delta_v: 0.15\ndata_quality:\n  mode: exclude_invalid_rows\n",
    encoding="utf-8",
)
source_dir = root.parents[1] / "validation" / "cora-data2395" / "cycle229"
cases = []
imported = Path(
    subprocess.check_output(
        [sys.executable, "-c", "import batterylog; print(batterylog.__file__)"], cwd=out, text=True
    ).strip()
).resolve()
expected_import = Path(os.environ["PYTHONPATH"]) / "batterylog" / "__init__.py"
assert imported == expected_import.resolve(), str(imported)
for branch in [1, 2, 3]:
    source = source_dir / f"Qtzl_Cycle_229_WLTP_WLTP_P{branch}.csv"
    json_path = out / f"cora-P{branch}-{stage}.json"
    report = out / f"cora-P{branch}-{stage}.html"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "batterylog",
            str(source),
            "--config",
            str(config),
            "--json-out",
            str(json_path),
            "--report",
            str(report),
        ],
        cwd=out,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert run.returncode == 1, run.stderr
    result = json.loads(json_path.read_text(encoding="utf-8"))
    assert json.loads(run.stdout) == result
    if stage == "after":
        assert result == json.loads(
            (out / f"cora-P{branch}-before.json").read_text(encoding="utf-8")
        )
    assert result["schema_version"] == 8
    assert result["rows_input"] == 16365 and result["rows_excluded"] == 0
    assert result["validation_status"] == "FAIL"
    cases.append(
        {
            "branch": branch,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_bytes": source.stat().st_size,
            "rows_input": result["rows_input"],
            "rows_analyzed": result["rows_analyzed"],
            "rows_excluded": result["rows_excluded"],
            "quality_events": len(result["data_quality"]["events"]),
            "violation_events": len(result["violations"]),
            "cli_exit": run.returncode,
            "stdout_equals_json_file": True,
            "result_equals_parent": stage == "after",
            "html_bytes": report.stat().st_size,
        }
    )
if stage == "after":
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        try:
            for case in cases:
                branch = case["branch"]
                result = json.loads(
                    (out / f"cora-P{branch}-after.json").read_text(encoding="utf-8")
                )
                context = browser.new_context()
                context.route(
                    "**/*",
                    lambda route: (
                        route.continue_()
                        if route.request.url.startswith("file:")
                        else route.abort()
                    ),
                )
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                page.goto((out / f"cora-P{branch}-after.html").as_uri(), wait_until="load")
                payload = page.locator("#event-data").evaluate("(e)=>JSON.parse(e.textContent)")
                assert len(payload) == case["violation_events"]
                assert all(
                    record["start"] == event["start_time_s"]
                    and record["end"] == event["end_time_s"]
                    and record["signals"] == event["signals"]
                    for record, event in zip(payload, result["violations"], strict=True)
                )
                page.locator("#event-pages [data-page=last]").click()
                last_cells = (
                    page.locator("#event-table tbody tr").last.locator("td").all_text_contents()
                )
                assert last_cells == payload[-1]["cells"]
                assert last_cells[10].startswith("pack ") and "signed error" in last_cells[10]
                assert page.locator(".status strong").inner_text() == "FAIL" and not errors
                case.update(
                    all_events_retained=True,
                    last_page_evidence_preserved=True,
                    page_errors=errors,
                    chart_count=page.locator("svg.timeseries-chart").count(),
                )
                context.close()
        finally:
            browser.close()
    (root / "docs" / "benchmarks" / "0.10-cora-cycle229-recheck.json").write_text(
        json.dumps(
            {
                "dataset": "CORA data2395 cycle 229, existing canonical CSV adapter",
                "threshold_v": 0.15,
                "threshold_purpose": "software characterization only",
                "package_import_root": os.environ.get("PYTHONPATH"),
                "cases": cases,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
print(json.dumps(cases), flush=True)
