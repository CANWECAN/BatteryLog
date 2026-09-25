"""Reproduce the BatteryLog v0.9.1 CORA real-data validation campaign.

Dataset DOI: 10.34810/data2395. PyArrow is an external validation dependency only.
The configured mismatch threshold is for software characterization, not a universal
battery engineering limit.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.config import DataQualityConfig, ValidationLimits


@dataclass
class FrameLoader:
    frame: pd.DataFrame
    chunk_rows: int
    source_format: str = "external-parquet"

    def iter_chunks(self, *, signal_mapping):
        if signal_mapping is not None:
            raise ValueError("External CORA adapter expects canonical signals")
        for start in range(0, len(self.frame), self.chunk_rows):
            yield self.frame.iloc[start : start + self.chunk_rows].copy()


def canonical_branch(source: pd.DataFrame, elapsed_s: np.ndarray, branch: int) -> pd.DataFrame:
    data: dict[str, object] = {"timestamp_s": elapsed_s}
    for i in range(1, 13):
        data[f"cell_{i}_v"] = source[f"Voltage_Cell_P{branch}S{i} [V]"].to_numpy()
    temp_index = 1
    for i in range(1, 13):
        for location in ("Top", "Bottom"):
            data[f"temp_{temp_index}_c"] = source[
                f"Temperature_Cell_{location}_P{branch}S{i} [degC]"
            ].to_numpy()
            temp_index += 1
    data["pack_current_a"] = source[f"Current_Actual_P{branch} [A]"].to_numpy()
    data["pack_voltage_v"] = source[f"Voltage_Actual_P{branch} [V]"].to_numpy()
    return pd.DataFrame(data)


def direct_evidence(frame: pd.DataFrame, threshold: float) -> dict[str, object]:
    numeric = frame.to_numpy(dtype=float, copy=False)
    valid = np.isfinite(numeric).all(axis=1)
    cells = np.ascontiguousarray(
        frame[[f"cell_{i}_v" for i in range(1, 13)]].to_numpy(dtype=float, copy=False)
    )
    cell_sum = np.sum(cells, axis=1, dtype=np.float64)
    delta = np.abs(frame["pack_voltage_v"].to_numpy(dtype=float) - cell_sum)
    guard = np.isclose(
        delta,
        threshold,
        rtol=8 * np.finfo(np.float64).eps,
        atol=0.0,
    )
    failing = valid & (delta > threshold) & ~guard
    valid_delta = delta[valid]
    return {
        "rows": len(frame),
        "valid_rows": int(valid.sum()),
        "excluded_rows": int((~valid).sum()),
        "violating_rows": int(failing.sum()),
        "peak_v": float(valid_delta.max()) if valid_delta.size else None,
    }


def required_source_columns() -> list[str]:
    columns = ["Timestamp"]
    columns += [f"Current_Actual_P{b} [A]" for b in range(1, 4)]
    columns += [f"Voltage_Actual_P{b} [V]" for b in range(1, 4)]
    columns += [f"Voltage_Cell_P{b}S{i} [V]" for b in range(1, 4) for i in range(1, 13)]
    columns += [
        f"Temperature_Cell_{location}_P{b}S{i} [degC]"
        for b in range(1, 4)
        for i in range(1, 13)
        for location in ("Top", "Bottom")
    ]
    return columns


parser = argparse.ArgumentParser()
parser.add_argument("zip_path", type=Path)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--threshold", type=float, default=0.15)
parser.add_argument("--chunk-rows", type=int, default=25_000)
parser.add_argument("--cycle", type=int)
parser.add_argument("--max-files", type=int)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)

members: list[tuple[int, str]] = []
with zipfile.ZipFile(args.zip_path) as archive:
    for name in archive.namelist():
        match = re.search(r"Qtzl_Cycle_(\d+).*\.parquet$", name)
        if match:
            members.append((int(match.group(1)), name))
members.sort()
if args.cycle is not None:
    members = [item for item in members if item[0] == args.cycle]
if args.max_files is not None:
    members = members[: args.max_files]
if not members:
    raise SystemExit("No matching Parquet cycle files")

started = datetime.now(UTC)
results_path = args.output / "full_campaign_runs.jsonl"
records: list[dict[str, object]] = []
limits = ValidationLimits(pack_voltage_cell_sum_max_delta_v=args.threshold)
dq = DataQualityConfig("exclude_invalid_rows")
columns = required_source_columns()

with zipfile.ZipFile(args.zip_path) as archive, results_path.open("w", encoding="utf-8") as output:
    for file_index, (cycle, name) in enumerate(members, start=1):
        raw = archive.read(name)
        source = pq.read_table(io.BytesIO(raw), columns=columns).to_pandas()
        timestamps = pd.to_datetime(source["Timestamp"], errors="raise")
        elapsed_s = (timestamps - timestamps.iloc[0]).dt.total_seconds().to_numpy(dtype=float)
        for branch in range(1, 4):
            canonical = canonical_branch(source, elapsed_s, branch)
            direct = direct_evidence(canonical, args.threshold)
            started_run = time.perf_counter()
            try:
                result = analyze_measurement_loader(
                    FrameLoader(canonical, args.chunk_rows),
                    limits=limits,
                    data_quality=dq,
                )
                runtime_s = time.perf_counter() - started_run
                events = result["violations"]
                reported_samples = sum(event["sample_count"] for event in events)
                peak = result["pack_voltage_cell_sum_peak"]
                reported_peak = peak["absolute_delta_v"] if peak is not None else None
                parity = (
                    reported_samples == direct["violating_rows"]
                    and result["rows_excluded"] == direct["excluded_rows"]
                    and (
                        direct["peak_v"] is None
                        or (
                            reported_peak is not None
                            and abs(float(reported_peak) - float(direct["peak_v"])) < 1e-9
                        )
                    )
                )
                record = {
                    "cycle": cycle,
                    "file": name,
                    "branch": branch,
                    "runtime_s": runtime_s,
                    "status": result["validation_status"],
                    "rows_input": result["rows_input"],
                    "rows_analyzed": result["rows_analyzed"],
                    "rows_excluded": result["rows_excluded"],
                    "data_quality_events": len(result["data_quality"]["events"]),
                    "events": len(events),
                    "violating_samples": reported_samples,
                    "peak_v": reported_peak,
                    "direct": direct,
                    "parity": bool(parity),
                    "error": None,
                }
            # Keep the campaign running so a single unexpected source/run failure is
            # recorded with its cycle and branch instead of hiding later failures.
            except Exception as exc:  # noqa: BLE001
                runtime_s = time.perf_counter() - started_run
                record = {
                    "cycle": cycle,
                    "file": name,
                    "branch": branch,
                    "runtime_s": runtime_s,
                    "error": f"{type(exc).__name__}: {exc}",
                    "direct": direct,
                    "parity": False,
                }
            records.append(record)
            output.write(json.dumps(record) + "\n")
            output.flush()
            del canonical
        del source
        if file_index == 1 or file_index % 10 == 0 or file_index == len(members):
            print(f"progress {file_index}/{len(members)} cycle={cycle}", flush=True)

successful = [r for r in records if r["error"] is None]
runtimes = np.array([float(r["runtime_s"]) for r in successful], dtype=float)
worst = max(successful, key=lambda r: float(r["peak_v"] or -1.0)) if successful else None
summary = {
    "batterylog_version": version("batterylog"),
    "source_zip": str(args.zip_path),
    "started_utc": started.isoformat(),
    "finished_utc": datetime.now(UTC).isoformat(),
    "threshold_v": args.threshold,
    "threshold_role": "illustrative software-validation threshold; not a universal engineering limit",
    "data_quality_mode": "exclude_invalid_rows",
    "chunk_rows": args.chunk_rows,
    "source_files": len(members),
    "branch_runs": len(records),
    "successful_runs": len(successful),
    "error_runs": len(records) - len(successful),
    "pass_runs": sum(r.get("status") == "PASS" for r in successful),
    "fail_runs": sum(r.get("status") == "FAIL" for r in successful),
    "not_evaluated_runs": sum(r.get("status") == "NOT_EVALUATED" for r in successful),
    "rows_input_total": sum(int(r.get("rows_input", 0)) for r in successful),
    "rows_analyzed_total": sum(int(r.get("rows_analyzed", 0)) for r in successful),
    "rows_excluded_total": sum(int(r.get("rows_excluded", 0)) for r in successful),
    "data_quality_events_total": sum(int(r.get("data_quality_events", 0)) for r in successful),
    "events_total": sum(int(r.get("events", 0)) for r in successful),
    "violating_samples_total": sum(int(r.get("violating_samples", 0)) for r in successful),
    "all_successful_runs_direct_parity": all(bool(r["parity"]) for r in successful),
    "runtime_s_total": float(runtimes.sum()) if runtimes.size else 0.0,
    "runtime_s_median": float(np.median(runtimes)) if runtimes.size else None,
    "runtime_s_p95": float(np.quantile(runtimes, 0.95)) if runtimes.size else None,
    "runtime_s_max": float(runtimes.max()) if runtimes.size else None,
    "worst_run": worst,
}
(args.output / "full_campaign_summary.json").write_text(
    json.dumps(summary, indent=2), encoding="utf-8"
)
print(json.dumps(summary, indent=2))
