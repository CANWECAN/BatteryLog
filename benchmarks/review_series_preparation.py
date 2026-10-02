"""Compare retained real inputs before/after a report preparation refactor."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import batterylog
from batterylog import AnalysisService
from batterylog.config import load_validation_config

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "series-review"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["before", "after"])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    imported = Path(batterylog.__file__).resolve()
    expected = Path(os.environ["PYTHONPATH"]).resolve() / "batterylog" / "__init__.py"
    assert imported == expected, (imported, expected)
    products = ROOT.parent
    validation = products.parent / "validation" / "cora-data2395" / "cycle229"
    sources = [
        (
            "mf4-100k",
            products
            / "BatteryLog-report-review"
            / "dist"
            / "report-review"
            / "pressure-100000.mf4",
        ),
        *[
            (f"cora-P{branch}", validation / f"Qtzl_Cycle_229_WLTP_WLTP_P{branch}.csv")
            for branch in (1, 2, 3)
        ],
    ]
    metadata = []
    for name, source in sources:
        assert source.is_file(), str(source)
        is_mf4 = source.suffix == ".mf4"
        config_text = (
            "schema_version: 6\nlimits:\n  cell_voltage:\n    max_v: 4.2\n    max_delta_v: 0.08\n"
            if is_mf4
            else "schema_version: 6\nlimits:\n  pack_voltage:\n    cell_sum_max_delta_v: 0.15\n"
            "data_quality:\n  mode: exclude_invalid_rows\n"
        )
        config_path = OUT / f"{name}.yaml"
        config_path.write_text(config_text, encoding="utf-8")
        config = load_validation_config(config_path)
        output = AnalysisService(config).analyze_path(source, report_max_points=2400)
        assert output.report_series is not None
        snapshot = json.loads(
            json.dumps({"result": output.result, "series": asdict(output.report_series)})
        )
        snapshot_path = OUT / f"{name}-{args.stage}-snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
        if args.stage == "after":
            assert snapshot == json.loads((OUT / f"{name}-before-snapshot.json").read_text("utf-8"))
        report = OUT / f"{name}-{args.stage}.html"
        result_path = OUT / f"{name}-{args.stage}.json"
        run = subprocess.run(
            [
                sys.executable,
                "-m",
                "batterylog",
                str(source),
                "--config",
                str(config_path),
                "--report",
                str(report),
                "--json-out",
                str(result_path),
            ],
            cwd=OUT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert run.returncode == 1, (name, run.stderr)
        result = json.loads(result_path.read_text("utf-8"))
        assert json.loads(run.stdout) == result
        assert result["rows_analyzed"] == output.result["rows_analyzed"]
        svgs = re.findall(r"<svg\b.*?</svg>", report.read_text("utf-8"), flags=re.DOTALL)
        svg_path = OUT / f"{name}-{args.stage}-svg.json"
        svg_path.write_text(json.dumps(svgs), encoding="utf-8")
        if args.stage == "after":
            assert result == json.loads((OUT / f"{name}-before.json").read_text("utf-8"))
            assert svgs == json.loads((OUT / f"{name}-before-svg.json").read_text("utf-8"))
        metadata.append(
            {
                "source": name,
                "source_sha256": digest(source.read_bytes()),
                "rows_input": result["rows_input"],
                "rows_analyzed": result["rows_analyzed"],
                "events": len(result["violations"]),
                "quality_events": len(result["data_quality"]["events"]),
                "series_points": len(output.report_series.points),
                "chart_count": len(svgs),
                "svg_sha256": digest(json.dumps(svgs).encode()),
                "full_snapshot_equals_parent": args.stage == "after",
                "cli_result_equals_parent": args.stage == "after",
                "svg_equals_parent": args.stage == "after",
                "stdout_equals_json": True,
            }
        )
    record = {
        "stage": args.stage,
        "import_root": str(imported.parent.parent),
        "reference_head": "916845e005c124f88db2d8bbc3d9cbd119525eaa",
        "streaming_source_sha256": digest(
            (imported.parent / "analysis" / "streaming.py").read_bytes()
        ),
        "scope": "retained CORA cycle-229 branches and aligned 100k-event MF4; not full campaign",
        "cases": metadata,
    }
    target = OUT / "0.10-series-preparation.json" if args.stage == "after" else OUT / "before.json"
    target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
