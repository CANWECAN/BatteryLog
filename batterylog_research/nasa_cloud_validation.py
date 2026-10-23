# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Bounded real-data validation on hash-pinned NASA-origin MAT mirror files.

SciPy is an external campaign dependency, not a BatteryLog runtime dependency.
No fault labels, acquisition simultaneity or official-file authentication claimed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator

from batterylog import (
    BalancingConfig,
    ContactorResponseConfig,
    DataQualityConfig,
    FailureModelConfig,
    PrechargeCurrentConfig,
    TemperatureRiseConfig,
    UnloadedCurrentConfig,
    ValidationLimits,
    validate_result_semantics,
)
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import _analyze_battery_chunks

MIRROR = "devhaaana/nasa-battery-aging-dataset"
SOURCE_COMMIT = "c881323a09dfa4c8f7405945ac7c81480b5f4307"
SOURCES = {
    "B0005": {
        "bytes": 15956874,
        "git_blob": "8ecf6c78caf437a36fec60cf02470510b46e9162",
        "sha256": "0eae4585baf3f200c09fe24c5ab884f1889679fc75206ca1aa19da704104f0b0",
    },
    "B0018": {
        "bytes": 8502218,
        "git_blob": "13ef3ffda5be655edc2ed08a52073aedf73b548b",
        "sha256": "d1e6c923a43ea1c9666b3a90bbb521757a067fd60b4d17dbfaa49c50b179da69",
    },
}
REL_TOL = 8 * np.finfo(float).eps
FIELDS = {
    "Time": "timestamp_s",
    "Voltage_measured": "cell_1_v",
    "Temperature_measured": "temp_1_c",
    "Current_measured": "pack_current_a",
}
LIMITS = ValidationLimits(cell_min_v=2.7, cell_max_v=4.2, temperature_max_c=45)
MODELS = FailureModelConfig(60, temperature_rise=TemperatureRiseConfig(1, 0.1))
QUALITY = DataQualityConfig("exclude_invalid_rows")


def verify_source(path: Path, expected: dict) -> None:
    data = path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if (
        len(data) != expected["bytes"]
        or blob != expected["git_blob"]
        or hashlib.sha256(data).hexdigest() != expected["sha256"]
    ):
        raise ValueError(f"Source identity mismatch: {path.name}")


def acquire_sources(directory: Path, download: bool) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, expected in SOURCES.items():
        path = directory / f"{name}.mat"
        if not path.exists() and download:
            url = f"https://raw.githubusercontent.com/{MIRROR}/{SOURCE_COMMIT}/data/{name}.mat"
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(expected["bytes"] + 1)
            if len(data) != expected["bytes"]:
                raise ValueError(f"Unexpected download length: {name}")
            # Validate downloaded bytes before installing the source file.
            temporary = path.with_suffix(".download")
            temporary.write_bytes(data)
            try:
                verify_source(temporary, expected)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        verify_source(path, expected)


def canonical_operation(data: dict) -> pd.DataFrame:
    arrays = {target: np.atleast_1d(data[key]).astype(float) for key, target in FIELDS.items()}
    lengths = {len(value) for value in arrays.values()}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) < 2:
        raise ValueError("Source measurement arrays must have matching lengths >= 2")
    frame = pd.DataFrame(arrays)
    times = frame["timestamp_s"].to_numpy()
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("Campaign requires finite strictly increasing source times")
    # Preserve original per-operation seconds and all source values, including NaN.
    return frame


def above(values, limit):
    return (values > limit) & ~np.isclose(values, limit, rtol=REL_TOL, atol=0)


def temperature_reference(frame: pd.DataFrame, gap=60, minimum=0.1, ceiling=1) -> dict:
    """Independent array calculation, without the production temporal collector."""
    times = frame["timestamp_s"].to_numpy()
    temperature = frame["temp_1_c"].to_numpy()
    valid = np.isfinite(frame.to_numpy()).all(axis=1)
    dt = np.r_[np.nan, np.diff(times)]
    breaks = np.r_[True, ~valid[:-1] | ~valid[1:] | above(dt[1:], gap)]
    eligible = (
        valid
        & np.r_[False, valid[:-1]]
        & ~breaks
        & ((dt >= minimum) | np.isclose(dt, minimum, rtol=REL_TOL, atol=0))
    )
    rates = np.r_[np.nan, np.diff(temperature) / dt[1:] * 60]
    mask = eligible & above(rates, ceiling)
    starts = np.flatnonzero(mask & np.r_[True, ~mask[:-1] | breaks[1:]])
    ends = np.flatnonzero(mask & np.r_[~mask[1:] | breaks[1:], True])
    events = []
    for start, end in zip(starts, ends, strict=True):
        peak = int(start + np.argmax(rates[start : end + 1]))
        events.append(
            {
                "start_time_s": float(times[start]),
                "end_time_s": float(times[end]),
                "peak_time_s": float(times[peak]),
                "measured_value": float(rates[peak]),
                "sample_count": int(end - start + 1),
                "evidence": {
                    "previous_time_s": float(times[peak - 1]),
                    "interval_s": float(dt[peak]),
                    "previous_temperature_c": float(temperature[peak - 1]),
                    "temperature_c": float(temperature[peak]),
                },
            }
        )
    return {
        "status": "FAIL" if events else "PASS" if eligible.any() else "NOT_EVALUATED",
        "evaluated_samples": int(eligible.sum()),
        "incomplete_intervals": 0,
        "events": events,
    }


def compare_temperature(actual: dict, reference: dict) -> int:
    for key in ("status", "evaluated_samples", "incomplete_intervals"):
        if actual[key] != reference[key]:
            raise AssertionError(f"Temperature {key} differs from raw-array reference")
    if len(actual["events"]) != len(reference["events"]):
        raise AssertionError("Temperature event count differs")
    for event, expected in zip(actual["events"], reference["events"], strict=True):
        for key, value in expected.items():
            if key == "evidence":
                pairs = value.items()
                observed = event["evidence"]
            else:
                pairs = [(key, value)]
                observed = event
            for field, number in pairs:
                if not math.isclose(observed[field], number, rel_tol=1e-12, abs_tol=1e-9):
                    raise AssertionError(f"Temperature event {field} differs")
    return len(reference["events"])


def audit_core(result: dict, frame: pd.DataFrame) -> dict:
    valid = np.isfinite(frame.to_numpy()).all(axis=1)
    voltage = frame["cell_1_v"].to_numpy()
    temperature = frame["temp_1_c"].to_numpy()
    counts = {
        "CELL_UNDERVOLTAGE": int((valid & above(-voltage, -2.7)).sum()),
        "CELL_OVERVOLTAGE": int((valid & above(voltage, 4.2)).sum()),
        "TEMPERATURE_HIGH": int((valid & above(temperature, 45)).sum()),
    }
    if result["rows_excluded"] != int((~valid).sum()):
        raise AssertionError("Excluded-row count differs from source finite mask")
    for code, expected in counts.items():
        actual = sum(
            event["sample_count"] for event in result["violations"] if event["code"] == code
        )
        if actual != expected:
            raise AssertionError(f"{code}: {actual} != {expected}")
    return counts


def main(argv=None) -> int:
    from scipy.io import loadmat

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    options = parser.parse_args(argv)
    acquire_sources(options.data_dir, options.download)
    options.output.mkdir(parents=True, exist_ok=False)
    schema = json.loads(
        (Path(__file__).parents[1] / "batterylog/schema/result-v9.json").read_text()
    )
    validator = Draft202012Validator(schema)
    started = time.perf_counter()
    summary = {
        "scope": "NASA-origin mirror, single-cell source-software characterization",
        "mirror": MIRROR,
        "source_commit": SOURCE_COMMIT,
        "sources": SOURCES,
        "limits_are_illustrative": True,
        "source_authentication": "Mirror blob match; official NASA byte checksum unavailable",
        "resampling_or_clipping": False,
        "operations": 0,
        "rows": 0,
        "excluded_rows": 0,
        "temperature_events_audited": 0,
        "chunk_comparisons": 0,
        "strict_rejections_checked": 0,
        "missing_channel_runs": 0,
    }
    outcomes = Counter()
    operation_types = Counter()
    violations = Counter()
    records = []
    for label in SOURCES:
        operations = loadmat(options.data_dir / f"{label}.mat", simplify_cells=True)[label]["cycle"]
        sample_operations = {}
        for index, operation in enumerate(operations, start=1):
            kind = operation["type"]
            if kind not in {"charge", "discharge"}:
                continue
            sample_operations.setdefault(kind, []).append(index)
        selected = {items[edge] for items in sample_operations.values() for edge in (0, -1)}
        for index, operation in enumerate(operations, start=1):
            kind = operation["type"]
            if kind not in {"charge", "discharge"}:
                continue
            frame = canonical_operation(operation["data"])
            kwargs = {"limits": LIMITS, "failure_models": MODELS, "data_quality": QUALITY}
            result = _analyze_battery_frame(frame, **kwargs)
            validator.validate(result)
            validate_result_semantics(result)
            core_counts = audit_core(result, frame)
            evaluation = result["failure_models"]["evaluations"][0]
            audited = compare_temperature(evaluation, temperature_reference(frame))
            sizes = (997, 4096) + ((1, 7, 1024, 65536) if index in selected else ())
            for size in sizes:
                chunks = (frame.iloc[i : i + size] for i in range(0, len(frame), size))
                observed = _analyze_battery_chunks(chunks, **kwargs)
                if observed != result:
                    raise AssertionError(f"{label} operation {index}: chunk {size} changed result")
                summary["chunk_comparisons"] += 1
            if result["rows_excluded"]:
                try:
                    _analyze_battery_frame(frame, limits=LIMITS, failure_models=MODELS)
                except ValueError:
                    summary["strict_rejections_checked"] += 1
                else:
                    raise AssertionError("Strict mode accepted non-finite source data")
            if index in selected:
                missing = FailureModelConfig(
                    60,
                    temperature_rise=TemperatureRiseConfig(1, 0.1),
                    balancing=BalancingConfig("balance_active", 2, 0.02, 0.08, 4),
                    unloaded_current=UnloadedCurrentConfig("unloaded", 0.5, 2),
                    contactor_response=ContactorResponseConfig("command", "feedback", 2),
                    precharge_current=PrechargeCurrentConfig("precharge", 2, 4, 3),
                )
                check = _analyze_battery_frame(
                    frame, limits=LIMITS, failure_models=missing, data_quality=QUALITY
                )
                validator.validate(check)
                validate_result_semantics(check)
                for item in check["failure_models"]["evaluations"]:
                    if (
                        item["code"] != "TEMPERATURE_RISE_HIGH"
                        and item["status"] != "NOT_EVALUATED"
                    ):
                        raise AssertionError(
                            "Absent hardware status channel produced an evaluated result"
                        )
                summary["missing_channel_runs"] += 1
            summary["operations"] += 1
            summary["rows"] += len(frame)
            summary["excluded_rows"] += result["rows_excluded"]
            summary["temperature_events_audited"] += audited
            outcomes[result["validation_status"]] += 1
            operation_types[kind] += 1
            violations.update(core_counts)
            records.append(
                {
                    "cell": label,
                    "source_operation": index,
                    "type": kind,
                    "rows": len(frame),
                    "excluded": result["rows_excluded"],
                    "status": result["validation_status"],
                    "violating_samples": core_counts,
                    "temperature_events": audited,
                }
            )
        print(f"Completed {label}: {summary['operations']} operations", flush=True)
    summary["outcomes"] = dict(outcomes)
    summary["operation_types"] = dict(operation_types)
    summary["violating_samples"] = dict(violations)
    summary["elapsed_s"] = round(time.perf_counter() - started, 3)
    (options.output / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n"
    )
    (options.output / "operations.json").write_text(
        json.dumps(records, indent=2, allow_nan=False) + "\n"
    )
    print(json.dumps(summary, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
