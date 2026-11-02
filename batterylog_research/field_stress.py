# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Large-file source, parity and independent-reference probes (Research only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator

from batterylog import (
    DataQualityConfig,
    EventDetectionConfig,
    FailureModelConfig,
    SustainedImbalanceConfig,
    TemperatureRiseConfig,
    ValidationLimits,
    validate_result_semantics,
)
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.loaders.csv import CsvPathLoader
from batterylog_research.voltage_step_audit import audit_voltage_csv

SOURCE_SHA = "f4a7861b72b273f7a78f5fc2e1f965c9c631bc579ea03099d14b10f82df003b9"


def peak_rss_mib():
    """Linux's process-lifetime peak RSS, or unavailable on other platforms."""
    if sys.platform != "linux":
        return None
    import resource

    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 3)


REL = 8 * np.finfo(float).eps
LIMITS = ValidationLimits(
    cell_min_v=2.5,
    cell_max_v=3.65,
    imbalance_max_v=0.1,
    temperature_max_c=55,
    pack_voltage_cell_sum_max_delta_v=0.15,
)
MODELS = FailureModelConfig(
    60,
    sustained_imbalance=SustainedImbalanceConfig(0.05, 30),
    temperature_rise=TemperatureRiseConfig(10, 1),
)
CELLS = [f"cell_{i}_v" for i in range(1, 9)]
TEMPS = [f"temp_{i}_c" for i in range(1, 5)]


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(2**20), b""):
            h.update(chunk)
    return h.hexdigest()


def above(values, limit):
    return (values > limit) & ~np.isclose(values, limit, rtol=REL, atol=0)


def at_least(values, limit):
    return (values >= limit) | np.isclose(values, limit, rtol=REL, atol=0)


def prepare(source, directory):
    if digest(source) != SOURCE_SHA:
        raise ValueError("Unverified field source bytes")
    target = directory / "canonical.csv"
    if target.exists():
        raise ValueError("Canonical output already exists")
    origin = previous = None
    rows = duplicates = regressions = gaps = invalid = 0
    step_counts = [0, 0]
    balance_context_rows = 0
    raw_cells = [f"U_Cell_{i}" for i in range(1, 9)]
    raw_temps = [f"Temperature_{i}" for i in range(1, 5)]
    converter = [f"I_CNV_Cell_{i}" for i in range(1, 9)]
    cols = ["Timestamp", "U_Battery", "I_Battery", *raw_cells, *raw_temps, *converter]
    with target.open("w") as output:
        for chunk in pd.read_csv(source, usecols=cols, chunksize=100000, skip_blank_lines=False):
            timestamps = pd.to_datetime(chunk["Timestamp"], errors="raise")
            if timestamps.isna().any():
                raise ValueError("Missing field source timestamp")
            if origin is None:
                origin = timestamps.iloc[0]
            elapsed = (timestamps - origin).dt.total_seconds().to_numpy()
            dt = np.diff(np.r_[previous, elapsed]) if previous is not None else np.diff(elapsed)
            duplicates += int((dt == 0).sum())
            regressions += int((dt < 0).sum())
            gaps += int((dt > 60).sum())
            previous = elapsed[-1]
            frame = pd.DataFrame({"timestamp_s": elapsed})
            for original, canonical in zip(raw_cells, CELLS, strict=True):
                frame[canonical] = chunk[original].to_numpy()
            for original, canonical in zip(raw_temps, TEMPS, strict=True):
                frame[canonical] = chunk[original].to_numpy()
            frame["pack_current_a"] = chunk["I_Battery"].to_numpy()
            frame["pack_voltage_v"] = chunk["U_Battery"].to_numpy()
            invalid += int((~np.isfinite(frame.to_numpy()).all(axis=1)).sum())
            values = frame[TEMPS].to_numpy()
            changes = np.abs(np.diff(values, axis=0))
            finite_nonzero = changes[np.isfinite(changes) & (changes > 0)]
            step_counts[0] += len(finite_nonzero)
            step_counts[1] += int((finite_nonzero == 1).sum())
            balance_context_rows += int(
                (np.abs(chunk[converter].to_numpy()).max(axis=1) > 0.1).sum()
            )
            frame.to_csv(output, index=False, header=rows == 0, float_format="%.17g", na_rep="NaN")
            rows += len(frame)
    stats = {
        "rows": rows,
        "source_bytes": source.stat().st_size,
        "canonical_bytes": target.stat().st_size,
        "canonical_sha256": digest(target),
        "source_sha256": SOURCE_SHA,
        "origin_as_recorded": str(origin),
        "last_elapsed_s": float(previous),
        "duplicate_timestamp_pairs": duplicates,
        "timestamp_regressions": regressions,
        "gaps_above_60s": gaps,
        "nonfinite_rows_in_used_channels": invalid,
        "within_prepare_chunk_nonzero_temperature_changes": step_counts[0],
        "within_prepare_chunk_exact_1C_changes": step_counts[1],
        "rows_any_converter_abs_current_above_0_1A": balance_context_rows,
        "converter_current_used_as_balancing_status": False,
        "rows_removed_or_resampled": 0,
    }
    dump(directory / "source_stats.json", stats)
    print(json.dumps(stats), flush=True)


def core(csv_path, output, size):
    started = time.perf_counter()
    result = analyze_measurement_loader(
        CsvPathLoader(csv_path, chunk_rows=size),
        limits=LIMITS,
        failure_models=MODELS,
        data_quality=DataQualityConfig("exclude_invalid_rows"),
        event_detection=EventDetectionConfig(max_gap_s=60),
    )
    analyzed = time.perf_counter() - started
    schema = json.loads(
        (Path(__file__).parents[1] / "batterylog/schema/result-v9.json").read_text()
    )
    Draft202012Validator(schema).validate(result)
    validate_result_semantics(result)
    serialized = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    output.write_bytes(serialized)
    stats = {
        "chunk_rows": size,
        "rows": result["rows_input"],
        "status": result["validation_status"],
        "rows_excluded": result["rows_excluded"],
        "core_events": len(result["violations"]),
        "failure_events": sum(len(e["events"]) for e in result["failure_models"]["evaluations"]),
        "json_bytes": len(serialized),
        "result_sha256": hashlib.sha256(serialized).hexdigest(),
        "analysis_seconds": round(analyzed, 3),
        "total_seconds": round(time.perf_counter() - started, 3),
        "whole_process_peak_rss_mib": peak_rss_mib(),
    }
    dump(output.with_suffix(".stats.json"), stats)
    print(json.dumps(stats), flush=True)


def intervals(mask, breaks):
    starts = np.flatnonzero(mask & np.r_[True, ~mask[:-1] | breaks[1:]])
    ends = np.flatnonzero(mask & np.r_[~mask[1:] | breaks[1:], True])
    return zip(starts, ends, strict=True)


def model_references(frame):
    times = frame["timestamp_s"].to_numpy()
    cells = frame[CELLS].to_numpy()
    temperatures = frame[TEMPS].to_numpy(dtype=float)
    valid = np.isfinite(frame.to_numpy()).all(axis=1)
    dt = np.r_[np.nan, np.diff(times)]
    breaks = np.r_[True, ~valid[:-1] | ~valid[1:] | above(dt[1:], 60)]
    spread = cells.max(axis=1) - cells.min(axis=1)
    eligible_sustained = 0
    for start, end in intervals(valid, breaks):
        eligible_sustained += int(at_least(times[start : end + 1] - times[start], 30).sum())
    sustained = []
    for start, end in intervals(valid & above(spread, 0.05), breaks):
        if not at_least(times[end] - times[start], 30):
            continue
        peak = int(start + np.argmax(spread[start : end + 1]))
        sustained.append(
            {
                "start_time_s": float(times[start]),
                "end_time_s": float(times[end]),
                "peak_time_s": float(times[peak]),
                "measured_value": float(spread[peak]),
                "sample_count": int(end - start + 1),
                "evidence": {
                    "cell_min_v": float(cells[peak].min()),
                    "cell_max_v": float(cells[peak].max()),
                    "required_duration_s": 30.0,
                },
            }
        )
    # Duplicate times flush temperature runs, but do not reset sustained spans.
    eligible = valid & np.r_[False, valid[:-1]] & ~breaks & at_least(dt, 1)
    rates = np.full_like(temperatures, np.nan)
    np.divide(
        temperatures[1:] - temperatures[:-1], dt[1:, None], out=rates[1:], where=dt[1:, None] > 0
    )
    rates *= 60
    maximum = np.max(rates, axis=1)
    temperature_events = []
    for start, end in intervals(eligible & above(maximum, 10), breaks):
        peak = int(start + np.argmax(maximum[start : end + 1]))
        sensor = int(np.argmax(rates[peak]))
        temperature_events.append(
            {
                "start_time_s": float(times[start]),
                "end_time_s": float(times[end]),
                "peak_time_s": float(times[peak]),
                "measured_value": float(maximum[peak]),
                "sample_count": int(end - start + 1),
                "evidence": {
                    "previous_time_s": float(times[peak - 1]),
                    "interval_s": float(dt[peak]),
                    "previous_temperature_c": float(temperatures[peak - 1, sensor]),
                    "temperature_c": float(temperatures[peak, sensor]),
                },
            }
        )
    return {
        "CELL_IMBALANCE_SUSTAINED": (eligible_sustained, sustained),
        "TEMPERATURE_RISE_HIGH": (int(eligible.sum()), temperature_events),
    }


def reference(csv_path, result_path, output):
    started = time.perf_counter()
    frame = pd.read_csv(csv_path, skip_blank_lines=False)
    result = json.loads(result_path.read_text())
    valid = np.isfinite(frame.to_numpy()).all(axis=1)
    cells = frame[CELLS].to_numpy()
    temperatures = frame[TEMPS].to_numpy()
    spread = cells.max(axis=1) - cells.min(axis=1)
    delta = np.abs(frame["pack_voltage_v"].to_numpy() - cells.sum(axis=1))
    core_counts = {
        "CELL_UNDERVOLTAGE": int((valid & above(-cells.min(axis=1), -2.5)).sum()),
        "CELL_OVERVOLTAGE": int((valid & above(cells.max(axis=1), 3.65)).sum()),
        "CELL_IMBALANCE_HIGH": int((valid & above(spread, 0.1)).sum()),
        "TEMPERATURE_HIGH": int((valid & above(temperatures.max(axis=1), 55)).sum()),
        "PACK_VOLTAGE_CELL_SUM_MISMATCH": int((valid & above(delta, 0.15)).sum()),
    }
    for code, count in core_counts.items():
        observed = sum(e["sample_count"] for e in result["violations"] if e["code"] == code)
        if observed != count:
            raise AssertionError(f"Independent {code} count mismatch: {observed} != {count}")
    if result["rows_excluded"] != int((~valid).sum()):
        raise AssertionError("Independent exclusion count mismatch")
    references = model_references(frame)
    audited = 0
    for evaluation in result["failure_models"]["evaluations"]:
        eligible, events = references[evaluation["code"]]
        if evaluation["evaluated_samples"] != eligible or len(evaluation["events"]) != len(events):
            raise AssertionError(f"Independent {evaluation['code']} accounting mismatch")
        expected_status = "FAIL" if events else "PASS" if eligible else "NOT_EVALUATED"
        if evaluation["status"] != expected_status:
            raise AssertionError("Independent model status mismatch")
        for actual, expected in zip(evaluation["events"], events, strict=True):
            for key, value in expected.items():
                observed = actual["evidence"] if key == "evidence" else actual
                for name, number in value.items() if key == "evidence" else [(key, value)]:
                    if not np.isclose(observed[name], number, rtol=1e-12, atol=1e-9):
                        raise AssertionError(f"Independent model evidence {name} mismatch")
            audited += 1
    stats = {
        "rows": len(frame),
        "core_violating_rows": core_counts,
        "independent_model_events_audited": audited,
        "spread_rows_by_probe_V": {
            str(t): int((valid & above(spread, t)).sum()) for t in (0.02, 0.05, 0.1, 0.2)
        },
        "pack_sum_rows_by_probe_V": {
            str(t): int((valid & above(delta, t)).sum()) for t in (0.05, 0.15, 0.3, 0.5)
        },
        "cell_voltage_min": float(np.min(cells[valid])),
        "cell_voltage_max": float(np.max(cells[valid])),
        "temperature_min": float(np.min(temperatures[valid])),
        "temperature_max": float(np.max(temperatures[valid])),
        "maximum_pack_sum_error_V": float(np.max(delta[valid])),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "whole_process_peak_rss_mib": peak_rss_mib(),
    }
    dump(output, stats)
    print(json.dumps(stats), flush=True)


def peer(csv_path, output):
    started = time.perf_counter()
    with csv_path.open(newline="") as source:
        report = audit_voltage_csv(source, peer_step_threshold_v=0.05, max_gap_s=60)
    stats = {
        "report": report,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "whole_process_peak_rss_mib": peak_rss_mib(),
    }
    dump(output, stats)
    print(json.dumps(stats), flush=True)


def hostile(csv_path, output):
    frame = pd.read_csv(csv_path, nrows=2049)
    mutations = []
    for field, value in (("timestamp_s", -1), ("cell_1_v", np.inf)):
        changed = frame.copy()
        changed.loc[1024, field] = value
        observed = []
        for size in (1, 7, 1024, 65536):
            try:
                from batterylog.analysis.streaming import _analyze_battery_chunks

                _analyze_battery_chunks(
                    (changed.iloc[i : i + size] for i in range(0, len(changed), size)),
                    limits=LIMITS,
                    failure_models=MODELS,
                )
            except ValueError as exc:
                observed.append(str(exc))
            else:
                raise AssertionError("Injected invalid input was accepted")
        if len(set(observed)) != 1:
            raise AssertionError("Chunk sizes changed rejection diagnostics")
        mutations.append({"field": field, "value": str(value), "diagnostic": observed[0]})
    # Tiny partitions also compare a real source window, with all duplicates retained.
    reference_result = _analyze_battery_frame(frame, limits=LIMITS, failure_models=MODELS)
    for size in (1, 7, 1024, 65536):
        from batterylog.analysis.streaming import _analyze_battery_chunks

        result = _analyze_battery_chunks(
            (frame.iloc[i : i + size] for i in range(0, len(frame), size)),
            limits=LIMITS,
            failure_models=MODELS,
        )
        if result != reference_result:
            raise AssertionError("Small source-window partition changed result")
    dump(
        output,
        {
            "source_window_rows": len(frame),
            "mutations": mutations,
            "small_partition_exact_matches": 4,
        },
    )


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["prepare", "core", "reference", "peer", "hostile"])
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--result", type=Path)
    p.add_argument("--chunk-rows", type=int, default=65536)
    args = p.parse_args(argv)
    if args.mode == "prepare":
        args.output.mkdir(exist_ok=False)
        prepare(args.source, args.output)
    elif args.mode == "core":
        core(args.source, args.output, args.chunk_rows)
    elif args.mode == "reference":
        if args.result is None:
            p.error("--result is required for reference")
        reference(args.source, args.result, args.output)
    elif args.mode == "peer":
        peer(args.source, args.output)
    else:
        hostile(args.source, args.output)


if __name__ == "__main__":
    main()
