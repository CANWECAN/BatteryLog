"""Characterize opt-in models on a pinned CORA battery measurement archive.

PyArrow is only needed to run the external campaign, not to import the references.
The vector/episode references do not call BatteryLog's temporal collector. Limits
are sensitivity probes, not calibrated limits or physical fault labels.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ARCHIVE_SHA256 = "174fccb08a8d215a1a8b1dcf8a5daeb951819ec97b8d9ff8b7d4a013763e77a3"
CYCLES = (125, 127, 196, 197, 229, 260, 268, 338, 343, 406, 410)
PROFILES = {
    "sensitive": (0.02, 5.0, 0.01, 0.15),
    "baseline": (0.05, 10.0, 0.025, 0.30),
    "relaxed": (0.10, 30.0, 0.05, 0.50),
}
CODES = ("CELL_IMBALANCE_SUSTAINED", "TEMPERATURE_RISE_HIGH", "CELL_SAG_UNDER_LOAD")


def above(values, limit):
    """Independent expression of the published binary64 comparison contract."""
    return (values > limit) & ~np.isclose(values, limit, rtol=8 * np.finfo(float).eps, atol=0)


def at_least(values, limit):
    return (values >= limit) | np.isclose(values, limit, rtol=8 * np.finfo(float).eps, atol=0)


def intervals(mask, breaks):
    """Inclusive row bounds of true runs, split at acquisition discontinuities."""
    starts = np.flatnonzero(mask & np.r_[True, ~mask[:-1] | breaks[1:]])
    ends = np.flatnonzero(mask & np.r_[~mask[1:] | breaks[1:], True])
    return list(zip(starts.tolist(), ends.tolist(), strict=True))


def peak_record(times, values, start, end, evidence):
    peak = start + int(np.argmax(values[start : end + 1]))
    return {
        "start_time_s": float(times[start]),
        "end_time_s": float(times[end]),
        "peak_time_s": float(times[peak]),
        "measured_value": float(values[peak]),
        "sample_count": end - start + 1,
        "evidence": evidence(peak),
    }


def reference_models(frame, config):
    """Calculate expected spans, sample counts, peaks and chains from raw rows."""
    times = frame["timestamp_s"].to_numpy(dtype=float)
    cells = frame[[f"cell_{i}_v" for i in range(1, 13)]].to_numpy(dtype=float)
    temperatures = frame[[f"temp_{i}_c" for i in range(1, 25)]].to_numpy(dtype=float)
    current = frame["pack_current_a"].to_numpy(dtype=float)
    valid = np.isfinite(frame.to_numpy(dtype=float)).all(axis=1)
    if not len(times) or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("This campaign requires finite, strictly increasing source times")
    dt = np.r_[np.nan, np.diff(times)]
    breaks = np.r_[True, ~valid[:-1] | ~valid[1:] | above(dt[1:], config.max_gap_s)]
    delta = np.max(cells, axis=1) - np.min(cells, axis=1)
    references = {}

    cfg = config.sustained_imbalance
    events = []
    evaluated = sum(
        int(at_least(times[start : end + 1] - times[start], cfg.duration_s).sum())
        for start, end in intervals(valid, breaks)
    )
    for start, end in intervals(valid & above(delta, cfg.max_delta_v), breaks):
        if at_least(times[end] - times[start], cfg.duration_s):
            events.append(
                peak_record(
                    times,
                    delta,
                    start,
                    end,
                    lambda p: {
                        "cell_min_v": float(cells[p].min()),
                        "cell_max_v": float(cells[p].max()),
                        "required_duration_s": cfg.duration_s,
                    },
                )
            )
    references[CODES[0]] = {
        "events": events,
        "evaluated_samples": evaluated,
        "incomplete_intervals": 0,
    }

    cfg = config.temperature_rise
    eligible = valid & np.r_[False, valid[:-1]] & ~breaks & at_least(dt, cfg.min_interval_s)
    rates = np.full_like(temperatures, -np.inf)
    rates[1:] = (temperatures[1:] - temperatures[:-1]) / dt[1:, None] * 60
    maximum_rate = rates.max(axis=1)
    events = []
    for start, end in intervals(eligible & above(maximum_rate, cfg.max_c_per_min), breaks):

        def temperature_chain(p):
            sensor = int(np.argmax(rates[p]))
            return {
                "previous_time_s": float(times[p - 1]),
                "interval_s": float(dt[p]),
                "previous_temperature_c": float(temperatures[p - 1, sensor]),
                "temperature_c": float(temperatures[p, sensor]),
            }

        events.append(peak_record(times, maximum_rate, start, end, temperature_chain))
    references[CODES[1]] = {
        "events": events,
        "evaluated_samples": int(eligible.sum()),
        "incomplete_intervals": 0,
    }

    cfg = config.cell_sag
    discharge = current if cfg.positive_direction == "discharge" else -current
    loaded = valid & at_least(discharge, cfg.load_min_discharge_a)
    idle = valid & ~above(np.abs(current), cfg.baseline_max_abs_current_a)
    events, evaluated, incomplete = [], 0, 0
    for segment_start, segment_end in intervals(valid, breaks):
        previous_end = segment_start - 1
        segment_load = np.zeros(len(times), dtype=bool)
        segment_load[segment_start : segment_end + 1] = loaded[segment_start : segment_end + 1]
        for start, end in intervals(segment_load, breaks):
            candidates = np.flatnonzero(idle[previous_end + 1 : start]) + previous_end + 1
            previous_end = end
            if not candidates.size or above(
                times[start] - times[candidates[-1]], cfg.baseline_max_age_s
            ):
                incomplete += 1
                continue
            baseline = int(candidates[-1])
            qualifying = (
                np.flatnonzero(at_least(times[start : end + 1] - times[start], cfg.settling_s))
                + start
            )
            if not qualifying.size:
                incomplete += 1
                continue
            first = int(qualifying[0])
            evaluated += len(qualifying)
            drops = cells[baseline] - cells[first : end + 1]
            medians = np.median(drops, axis=1)
            excess = drops - medians[:, None]
            values = np.zeros(len(times), dtype=float)
            values[first : end + 1] = excess.max(axis=1)
            mask = np.zeros(len(times), dtype=bool)
            mask[first : end + 1] = above(values[first : end + 1], cfg.excess_sag_max_v)
            for event_start, event_end in intervals(mask, breaks):

                def sag_chain(
                    p,
                    *,
                    first=first,
                    excess=excess,
                    baseline=baseline,
                    start=start,
                    drops=drops,
                    medians=medians,
                ):
                    local = p - first
                    cell = int(np.argmax(excess[local]))
                    return {
                        "baseline_time_s": float(times[baseline]),
                        "load_start_time_s": float(times[start]),
                        "baseline_current_a": float(current[baseline]),
                        "current_a": float(current[p]),
                        "baseline_cell_v": float(cells[baseline, cell]),
                        "cell_v": float(cells[p, cell]),
                        "cell_sag_v": float(drops[local, cell]),
                        "median_sag_v": float(medians[local]),
                    }

                events.append(peak_record(times, values, event_start, event_end, sag_chain))
    references[CODES[2]] = {
        "events": events,
        "evaluated_samples": evaluated,
        "incomplete_intervals": incomplete,
    }
    for value in references.values():
        value["status"] = (
            "FAIL"
            if value["events"]
            else "NOT_EVALUATED"
            if not value["evaluated_samples"] or value["incomplete_intervals"]
            else "PASS"
        )
    return references


def compare_models(result, references):
    audited = 0
    evaluations = {item["code"]: item for item in result["failure_models"]["evaluations"]}
    for code, reference in references.items():
        actual = evaluations[code]
        for field in ("status", "evaluated_samples", "incomplete_intervals"):
            if actual[field] != reference[field]:
                raise AssertionError(f"{code} {field}: {actual[field]} != {reference[field]}")
        if len(actual["events"]) != len(reference["events"]):
            raise AssertionError(f"{code}: event count differs")
        for actual_event, expected in zip(actual["events"], reference["events"], strict=True):
            for field, value in expected.items():
                pairs = value.items() if field == "evidence" else [(field, value)]
                source = actual_event["evidence"] if field == "evidence" else actual_event
                for key, number in pairs:
                    if not np.isclose(source[key], number, rtol=1e-12, atol=1e-9):
                        raise AssertionError(f"{code} {key}: {source[key]} != {number}")
            audited += 1
    return audited


def canonical_branch(source, branch):
    timestamps = pd.to_datetime(source["Timestamp"], errors="raise")
    data = {
        "timestamp_s": (timestamps - timestamps.iloc[0]).dt.total_seconds().to_numpy(dtype=float)
    }
    data.update(
        {
            f"cell_{i}_v": source[f"Voltage_Cell_P{branch}S{i} [V]"].to_numpy(dtype=float)
            for i in range(1, 13)
        }
    )
    names = [
        f"Temperature_Cell_{p}_P{branch}S{i} [degC]"
        for i in range(1, 13)
        for p in ("Top", "Bottom")
    ]
    data.update(
        {f"temp_{i}_c": source[name].to_numpy(dtype=float) for i, name in enumerate(names, 1)}
    )
    data["pack_current_a"] = source[f"Current_Actual_P{branch} [A]"].to_numpy(dtype=float)
    data["pack_voltage_v"] = source[f"Voltage_Actual_P{branch} [V]"].to_numpy(dtype=float)
    return pd.DataFrame(data)


def profile_config(name):
    from batterylog import (
        CellSagConfig,
        FailureModelConfig,
        SustainedImbalanceConfig,
        TemperatureRiseConfig,
    )

    delta, rate, sag, _ = PROFILES[name]
    return FailureModelConfig(
        1,
        sustained_imbalance=SustainedImbalanceConfig(delta, 30),
        temperature_rise=TemperatureRiseConfig(rate, 0.25),
        cell_sag=CellSagConfig("charge", 0.05, 2, 5, 0.5, sag),
    )


class FrameLoader:
    source_format = "external-parquet"

    def __init__(self, frame, size):
        self.frame, self.size = frame, size

    def iter_chunks(self, *, signal_mapping):
        if signal_mapping is not None:
            raise ValueError("The adapter already supplies canonical branch signals")
        for start in range(0, len(self.frame), self.size):
            yield self.frame.iloc[start : start + self.size].copy()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    import re
    import time
    import zipfile

    import pyarrow.parquet as pq
    import yaml
    from jsonschema import Draft202012Validator

    from batterylog import (
        BalancingConfig,
        DataQualityConfig,
        ValidationLimits,
        validate_result_semantics,
    )
    from batterylog.analysis.streaming import analyze_measurement_loader

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cycles", type=int, nargs="+", default=list(CYCLES))
    parser.add_argument("--chunk-rows", type=int, default=4096)
    args = parser.parse_args()
    if args.chunk_rows <= 0 or len(set(args.cycles)) != len(args.cycles):
        parser.error("Require positive chunk size and unique cycles")
    if args.output.exists():
        parser.error("Use a new output directory; existing evidence is never overwritten")
    if digest(args.zip_path) != ARCHIVE_SHA256:
        raise ValueError("Source ZIP SHA-256 differs from the pinned campaign archive")
    import batterylog

    root = Path(batterylog.__file__).resolve().parents[1]
    validator = Draft202012Validator(
        json.loads((root / "batterylog/schema/result-v9.json").read_text())
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    args.output.mkdir(parents=True)
    records, examples, inventory, semicycles = [], [], [], Counter()
    started = time.perf_counter()
    chunk_checks, missing_balance_checks, audited_events = 0, 0, 0
    with zipfile.ZipFile(args.zip_path) as archive:
        members = {}
        for name in archive.namelist():
            match = re.search(r"Qtzl_Cycle_(\d+).*\.parquet$", name)
            if match and int(match[1]) in args.cycles:
                members[int(match[1])] = name
        if set(members) != set(args.cycles):
            raise ValueError("Requested cycles are absent from the archive")
        for cycle, name in sorted(members.items()):
            raw = archive.read(name)
            source = pq.read_table(io.BytesIO(raw)).to_pandas()
            semicycles.update(
                {str(k): int(v) for k, v in source["Semicycle"].value_counts().items()}
            )
            inventory.append(
                {
                    "cycle": cycle,
                    "member": name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "rows": len(source),
                    "columns": list(source.columns),
                }
            )
            for branch in range(1, 4):
                frame = canonical_branch(source, branch)
                for profile in PROFILES:
                    cfg = profile_config(profile)
                    limits = ValidationLimits(
                        pack_voltage_cell_sum_max_delta_v=PROFILES[profile][3]
                    )
                    result = analyze_measurement_loader(
                        FrameLoader(frame, args.chunk_rows),
                        limits=limits,
                        failure_models=cfg,
                        data_quality=DataQualityConfig("exclude_invalid_rows"),
                    )
                    validator.validate(result)
                    validate_result_semantics(result)
                    reference = reference_models(frame, cfg)
                    count = compare_models(result, reference)
                    audited_events += count
                    cells = frame[[f"cell_{i}_v" for i in range(1, 13)]].to_numpy(dtype=float)
                    valid = np.isfinite(frame.to_numpy(dtype=float)).all(axis=1)
                    mismatch = np.abs(frame["pack_voltage_v"].to_numpy() - cells.sum(axis=1))
                    mismatch_samples = int((valid & above(mismatch, PROFILES[profile][3])).sum())
                    actual_samples = sum(e["sample_count"] for e in result["violations"])
                    if actual_samples != mismatch_samples or result["rows_excluded"] != int(
                        (~valid).sum()
                    ):
                        raise AssertionError("Pack/cell-sum sample count or excluded rows differs")
                    evaluations = result["failure_models"]["evaluations"]
                    records.append(
                        {
                            "cycle": cycle,
                            "branch": branch,
                            "profile": profile,
                            "rows": len(frame),
                            "overall_status": result["validation_status"],
                            "mismatch_samples": mismatch_samples,
                            "audited_events": count,
                            "models": [
                                {
                                    k: e[k]
                                    for k in (
                                        "code",
                                        "status",
                                        "evaluated_samples",
                                        "incomplete_intervals",
                                    )
                                }
                                | {"events": len(e["events"])}
                                for e in evaluations
                            ],
                        }
                    )
                    if cycle == 229 and profile == "baseline":
                        alternate = analyze_measurement_loader(
                            FrameLoader(frame, 997),
                            limits=limits,
                            failure_models=cfg,
                            data_quality=DataQualityConfig("exclude_invalid_rows"),
                        )
                        if alternate != result:
                            raise AssertionError("Chunk-size result parity differs")
                        chunk_checks += 1
                        for evaluation in evaluations:
                            if evaluation["events"]:
                                event = max(evaluation["events"], key=lambda e: e["measured_value"])
                                examples.append({"cycle": cycle, "branch": branch, "event": event})
                        missing_cfg = type(cfg)(
                            **(
                                cfg.__dict__
                                | {
                                    "balancing": BalancingConfig(
                                        "balance_active", 30, 0.01, 0.05, 300
                                    )
                                }
                            )
                        )
                        missing = analyze_measurement_loader(
                            FrameLoader(frame, args.chunk_rows),
                            limits=ValidationLimits(),
                            failure_models=missing_cfg,
                        )
                        for item in missing["failure_models"]["evaluations"][-2:]:
                            if (
                                item["status"] != "NOT_EVALUATED"
                                or item["events"]
                                or item["evaluated_samples"]
                            ):
                                raise AssertionError(
                                    "Absent balancing status produced an evaluated result"
                                )
                            missing_balance_checks += 1
                        if branch == 1:
                            demo = args.output / "demo"
                            demo.mkdir()
                            frame.to_csv(demo / "cycle229-P1.csv", index=False)
                            yaml_config = {
                                "schema_version": 7,
                                "data_quality": {"mode": "exclude_invalid_rows"},
                                "limits": {
                                    "pack_voltage": {"cell_sum_max_delta_v": PROFILES[profile][3]}
                                },
                                "failure_models": {
                                    k: v for k, v in asdict(cfg).items() if v is not None
                                },
                            }
                            (demo / "illustrative-models.yaml").write_text(
                                yaml.safe_dump(yaml_config, sort_keys=False), encoding="utf-8"
                            )
                            write_json(
                                demo / "source.json",
                                {
                                    "doi": "10.34810/data2395",
                                    "license": "CC BY 4.0",
                                    "authors": [
                                        "Joaquín de la Vega Hernández",
                                        "Juan Antonio Ortega Redondo",
                                        "Jordi Roger Riba Ruiz",
                                    ],
                                    "archive_sha256": ARCHIVE_SHA256,
                                    "member": name,
                                    "member_sha256": hashlib.sha256(raw).hexdigest(),
                                    "branch": 1,
                                    "canonical_csv_sha256": digest(demo / "cycle229-P1.csv"),
                                    "transform": "Elapsed timestamp; 12S branch voltage/current; 24 thermistors; no added interpolation",
                                    "positive_current_direction": "charge",
                                    "threshold_role": "illustrative sensitivity probe",
                                },
                            )
            print(f"cycle={cycle} rows={len(source)} records={len(records)} audit=PASS", flush=True)
    aggregates = {}
    for profile in PROFILES:
        aggregates[profile] = {}
        for code in CODES:
            values = [
                m
                for r in records
                if r["profile"] == profile
                for m in r["models"]
                if m["code"] == code
            ]
            aggregates[profile][code] = {
                "outcomes": dict(Counter(m["status"] for m in values)),
                "events": sum(m["events"] for m in values),
                "evaluated_samples": sum(m["evaluated_samples"] for m in values),
                "incomplete_intervals": sum(m["incomplete_intervals"] for m in values),
            }
    summary = {
        "source_doi": "10.34810/data2395",
        "archive_sha256": ARCHIVE_SHA256,
        "analyzer_source": str(root),
        "analyzer_base_commit": head,
        "finished_utc": datetime.now(UTC).isoformat(),
        "runtime_s": time.perf_counter() - started,
        "cycles": sorted(members),
        "unique_source_rows": sum(item["rows"] for item in inventory),
        "branch_profiles": len(records),
        "audited_model_events": audited_events,
        "chunk_parity_checks": chunk_checks,
        "missing_balance_checks": missing_balance_checks,
        "semicycles": dict(semicycles),
        "profiles": PROFILES,
        "aggregates": aggregates,
        "threshold_role": "illustrative software characterization; not calibrated safety or diagnosis limits",
        "assumptions": [
            "3P12S mapped as three independent 12S branches",
            "Positive current is charge",
            "Source asynchronous acquisition and ZOH retained",
            "No ground-truth physical fault labels",
            "No directly logged balancing-active channel",
        ],
        "errors": 0,
    }
    if digest(args.zip_path) != ARCHIVE_SHA256:
        raise ValueError("Source ZIP changed during the campaign; no final summary published")
    write_json(args.output / "summary.json", summary)
    write_json(args.output / "runs.json", records)
    write_json(args.output / "inventory.json", inventory)
    write_json(args.output / "examples.json", examples)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
