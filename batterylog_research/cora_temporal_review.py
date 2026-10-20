# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Read-only temporal review of prepared CORA 12-cell / 24-temperature branch CSVs.

This investigation preserves recorded outliers and existing Core decisions.
Identical values do not prove stale acquisition; observed changes do not reveal
producer refresh times or hardware resolution. No field fault labels are assumed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from batterylog import CellSagConfig, FailureModelConfig, TemperatureRiseConfig
from batterylog.analysis.core import _analyze_battery_frame
from batterylog_research.temporal_characterization import (
    rate_summary,
    sag_context,
    temperature_rates,
)

CELLS = [f"cell_{i}_v" for i in range(1, 13)]
TEMPERATURES = [f"temp_{i}_c" for i in range(1, 25)]
COLUMNS = ["timestamp_s", *CELLS, *TEMPERATURES, "pack_current_a", "pack_voltage_v"]
SAG = CellSagConfig("charge", 0.025, 2, 5, 0.5, 0.05)
MAX_GAP_S = 1.0
GRID_C = 0.01
GRID_TOLERANCE_C = 4e-5


def _stats(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {"count": 0, "min": None, "median": None, "p95": None, "max": None}
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite descriptive statistic")
    with np.errstate(over="ignore", invalid="ignore"):
        result = {
            "count": len(values),
            "min": float(values.min()),
            "median": float(np.median(values)),
            "p95": float(np.quantile(values, 0.95)),
            "max": float(values.max()),
        }
    if not all(np.isfinite(result[key]) for key in ("min", "median", "p95", "max")):
        raise ValueError("Descriptive statistic overflowed")
    return result


def _validated(frame):
    if frame.columns.has_duplicates or set(frame.columns) != set(COLUMNS) or len(frame) < 2:
        raise ValueError("Require exact prepared CORA branch columns and at least two rows")
    source = frame[COLUMNS]
    if any(source[c].dtype.kind not in "iuf" for c in COLUMNS):
        raise ValueError("Require real numeric source columns")
    values = source.to_numpy(dtype=float, copy=True)
    if not np.isfinite(values).all():
        raise ValueError("Require finite recorded values; no silent row removal")
    times = values[:, 0]
    with np.errstate(over="ignore", invalid="ignore"):
        dt = np.diff(times)
        duration = times[-1] - times[0]
    if not np.isfinite(dt).all() or (dt <= 0).any() or not np.isfinite(duration):
        raise ValueError("Require finite strictly increasing timestamps and finite duration")
    return source.copy(deep=True), times, dt


def _sensor_changes(times, values, dt):
    contiguous = dt <= MAX_GAP_S
    rows = []
    for sensor, samples in zip(TEMPERATURES, values.T, strict=True):
        with np.errstate(over="ignore", invalid="ignore"):
            steps = np.diff(samples)
            residual = np.abs(samples - np.round(samples / GRID_C) * GRID_C)
        if not np.isfinite(steps[contiguous]).all() or not np.isfinite(residual).all():
            raise ValueError("Temperature descriptor calculation overflowed")
        changed = steps != 0
        intervals = []
        previous_change = None
        for i in range(1, len(times)):
            if not contiguous[i - 1]:
                previous_change = None
                continue
            if changed[i - 1]:
                if previous_change is not None:
                    intervals.append(times[i] - times[previous_change])
                previous_change = i
        rows.append(
            {
                "sensor": sensor,
                "contiguous_pairs": int(contiguous.sum()),
                "repeated_value_pairs": int((contiguous & ~changed).sum()),
                "absolute_nonzero_steps_c": _stats(np.abs(steps[contiguous & changed])),
                "between_observed_changes_s": _stats(intervals),
                "grid_compatibility": {
                    "candidate_grid_c": GRID_C,
                    "tolerance_c": GRID_TOLERANCE_C,
                    "compatible_fraction": float(np.mean(residual <= GRID_TOLERANCE_C)),
                    "max_residual_c": float(residual.max()),
                },
            }
        )
    return rows


def review_branch(frame):
    """Require prepared branch shape; do not mutate caller data or Core results."""
    source, times, dt = _validated(frame)
    temp = source[TEMPERATURES].to_numpy(dtype=float, copy=True)
    current = source["pack_current_a"].to_numpy(dtype=float, copy=True)
    result = _analyze_battery_frame(
        source,
        failure_models=FailureModelConfig(
            MAX_GAP_S,
            temperature_rise=TemperatureRiseConfig(10, 0.25),
            cell_sag=SAG,
        ),
    )
    evaluations = {e["code"]: e for e in result["failure_models"]["evaluations"]}
    thermal = evaluations["TEMPERATURE_RISE_HIGH"]
    sag = evaluations["CELL_SAG_UNDER_LOAD"]
    adjacent, _ = temperature_rates(
        times, temp, max_gap_s=MAX_GAP_S, min_interval_s=0.25, window_s=1
    )
    pair = rate_summary(times, adjacent, 10)
    context = sag_context(times, current, SAG, max_gap_s=MAX_GAP_S)
    if (
        pair["eligible_observations"] != thermal["evaluated_samples"]
        or pair["exceeding_observations"] != sum(e["sample_count"] for e in thermal["events"])
        or sum(e["eligible_samples"] for e in context["episodes"]) != sag["evaluated_samples"]
    ):
        raise RuntimeError("Independent characterization disagrees with Core eligibility/counts")
    windows = {}
    for horizon in (1, 2, 5):
        _, rates = temperature_rates(
            times, temp, max_gap_s=MAX_GAP_S, min_interval_s=0.25, window_s=horizon
        )
        windows[str(horizon)] = rate_summary(times, rates, 10)
    maximum = np.unravel_index(np.argmax(temp), temp.shape)
    minimum = np.unravel_index(np.argmin(temp), temp.shape)
    return {
        "rows": len(source),
        "duration_s": float(times[-1] - times[0]),
        "dt_s": _stats(dt),
        "gap_count": int((dt > MAX_GAP_S).sum()),
        "core": {
            e["code"]: {
                "status": e["status"],
                "evaluated_samples": e["evaluated_samples"],
                "incomplete_intervals": e["incomplete_intervals"],
                "event_count": len(e["events"]),
                "exceeding_samples": sum(event["sample_count"] for event in e["events"]),
                "reason": e["reason"],
            }
            for e in (thermal, sag)
        },
        "temperature": {
            "adjacent": pair,
            "endpoint_windows_s": windows,
            "recorded_minimum": {
                "value_c": float(temp[minimum]),
                "sensor": TEMPERATURES[minimum[1]],
                "row_index": int(minimum[0]),
                "timestamp_s": float(times[minimum[0]]),
            },
            "recorded_maximum": {
                "value_c": float(temp[maximum]),
                "sensor": TEMPERATURES[maximum[1]],
                "row_index": int(maximum[0]),
                "timestamp_s": float(times[maximum[0]]),
            },
            "per_sensor_changes": _sensor_changes(times, temp, dt),
        },
        "sag_context": {
            **context,
            "reference_age_at_onset_s": _stats(
                [
                    e["reference_age_at_onset_s"]
                    for e in context["episodes"]
                    if e["reference_age_at_onset_s"] is not None
                ]
            ),
            "observed_low_current_span_s": _stats(
                [
                    e["observed_low_current_span_s"]
                    for e in context["episodes"]
                    if e["observed_low_current_span_s"] is not None
                ]
            ),
            "zero_span_reference_episodes": sum(
                e["observed_low_current_span_s"] == 0 for e in context["episodes"]
            ),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    branches = []
    for path in args.csv:
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        branch = review_branch(pd.read_csv(path))
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        if before != after:
            raise RuntimeError("Source CSV changed during review")
        branches.append({"csv_name": path.name, "csv_sha256": before, **branch})
    root = Path(__file__).resolve().parents[1]
    sources = [
        Path(__file__),
        root / "batterylog_research/temporal_characterization.py",
        root / "batterylog/analysis/failure_models.py",
        root / "batterylog/failure_config.py",
    ]
    report = {
        "scope": "prepared_CORA_branch_temporal_characterization",
        "dataset_doi": "10.34810/data2395",
        "production_decisions_changed": False,
        "fault_labels_available_to_review": False,
        "configuration": {
            "max_gap_s": MAX_GAP_S,
            "temperature_limit_c_per_min": 10,
            "temperature_min_interval_s": 0.25,
            "sag_positive_direction": "charge",
            "sag_excess_v": 0.025,
            "sag_load_min_discharge_a": 2,
            "sag_baseline_max_abs_current_a": 0.05,
            "sag_baseline_max_age_s": 5,
            "sag_settling_s": 0.5,
        },
        "runtime": {
            "python": platform.python_version(),
            "numpy": version("numpy"),
            "pandas": version("pandas"),
            "batterylog": version("batterylog"),
        },
        "source_sha256": {
            str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sources
        },
        "limitations": [
            "Observed changes are not acquisition refresh intervals or hardware resolution.",
            "Candidate centigrid compatibility is descriptive, not a calibration result.",
            "Low-current duration is observed context, not verified electrochemical rest.",
            "Window counts are not detection-quality or false-alarm metrics.",
            "No precharge state or DC-link signal is mapped in these prepared CSVs.",
            "Full arrays are retained in memory; this is not a streaming importer.",
        ],
        "branches": branches,
    }
    payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
