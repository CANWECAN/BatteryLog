"""Measure report-only allocations in fresh processes using the retained MF4 snapshot."""

import argparse
import gc
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import tracemalloc
from pathlib import Path
from time import perf_counter

import psutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "allocation-review"
SNAPSHOT = (
    ROOT.parent
    / "BatteryLog-boundary-hunt/dist/boundary-hunt/real-inputs/mf4-100k-after-snapshot.json"
)


def worker(stage, operation, repeat, metric):
    import batterylog
    from batterylog.analysis.report_series import ReportSeries, ReportSeriesPoint
    from batterylog.reporting import render_html_report, write_html_report

    imported = Path(batterylog.__file__).resolve()
    assert imported == Path(os.environ["PYTHONPATH"]).resolve() / "batterylog/__init__.py"
    snapshot = json.loads(SNAPSHOT.read_text("utf-8"))
    result = snapshot["result"]
    spec = snapshot["series"]
    series = ReportSeries(
        points=tuple(ReportSeriesPoint(**point) for point in spec["points"]),
        source_rows=spec["source_rows"],
        max_points=spec["max_points"],
        strategy=spec["strategy"],
    )
    assert len(result["violations"]) == 100000
    report = OUT / f"{stage}-{metric}-{operation}-{repeat}.html"
    process = psutil.Process()
    gc.collect()
    rss_start = process.memory_info().rss
    sampled = {"rss_peak_bytes": rss_start}
    stop = threading.Event()

    def sample():
        while not stop.wait(0.02):
            sampled["rss_peak_bytes"] = max(sampled["rss_peak_bytes"], process.memory_info().rss)

    sampler = threading.Thread(target=sample, daemon=True)
    if metric == "rss":
        sampler.start()
    else:
        tracemalloc.start()
    started = perf_counter()
    if operation == "write":
        write_html_report(result, report, series=series)
    else:
        content = render_html_report(result, series=series)
        report.write_text(content, encoding="utf-8")
        del content
    elapsed = perf_counter() - started
    heap_peak = None
    if metric == "heap":
        _, heap_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    else:
        stop.set()
        sampler.join()
    html = report.read_text("utf-8")
    svgs = re.findall(r"<svg\b.*?</svg>", html, re.DOTALL)
    data = re.search(
        r'<script id="event-data" type="application/json">(.*?)</script>', html, re.DOTALL
    )
    assert data is not None and len(json.loads(data[1])) == 100000
    record = {
        "stage": stage,
        "metric": metric,
        "html_source_sha256": hashlib.sha256(
            (imported.parent / "reporting/html.py").read_bytes()
        ).hexdigest(),
        "operation": operation,
        "repeat": repeat,
        "elapsed_instrumented_s": elapsed,
        "report_heap_peak_bytes": heap_peak,
        "rss_start_bytes": rss_start if metric == "rss" else None,
        "rss_peak_bytes": sampled["rss_peak_bytes"] if metric == "rss" else None,
        "report_bytes": report.stat().st_size,
        "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
        "svg_bytes": sum(len(svg.encode("utf-8")) for svg in svgs),
        "svg_sha256": hashlib.sha256(json.dumps(svgs).encode()).hexdigest(),
        "embedded_event_json_bytes": len(data[1].encode("utf-8")),
        "events": 100000,
        "charts": len(svgs),
        "import_root": str(imported.parent.parent),
    }
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["before", "after"])
    parser.add_argument("--worker", choices=["write", "render"])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--metric", choices=["heap", "rss"], default="heap")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.worker:
        print(json.dumps(worker(args.stage, args.worker, args.repeat, args.metric)), flush=True)
        return
    cases = []
    for repeat in range(1, 4):
        for operation in ["write", "render"]:
            run = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    args.stage,
                    "--worker",
                    operation,
                    "--repeat",
                    str(repeat),
                    "--metric",
                    args.metric,
                ],
                cwd=ROOT.parent,
                capture_output=True,
                text=True,
                check=True,
            )
            record = json.loads(run.stdout)
            cases.append(record)
            print(json.dumps(record), flush=True)
    assert len({case["report_sha256"] for case in cases}) == 1
    record = {
        "reference_head": "5df999134d4062c932dc733c1dc0fc41b7a78e2e",
        "snapshot_sha256": hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest(),
        "method": "fresh processes; HTML render/write only; imports/snapshot decode excluded; heap uses tracemalloc without RSS sampling; RSS uses 20ms own-process samples without tracemalloc; no speed claim from traced times",
        "cases": cases,
    }
    target = OUT / f"{args.stage}-{args.metric}.json"
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if args.stage == "after":
        before = json.loads((OUT / f"before-{args.metric}.json").read_text("utf-8"))
        assert record["snapshot_sha256"] == before["snapshot_sha256"]
        assert {case["report_sha256"] for case in cases} == {
            case["report_sha256"] for case in before["cases"]
        }
        (ROOT / f"docs/benchmarks/0.10-report-allocation-{args.metric}.json").write_text(
            json.dumps({"before": before, "after": record}, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
