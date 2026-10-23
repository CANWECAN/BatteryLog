# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Research-only review of observed temperature-rise events; never edits analysis results."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from importlib.resources import files
from math import isfinite
from pathlib import Path
from typing import Any

from jsonschema.exceptions import ValidationError


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")  # noqa: TRY004 - public value contract
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def triage_temperature_events(
    result: dict[str, Any],
    *,
    min_temperature_c: float | None = None,
    max_temperature_c: float | None = None,
    max_reported_rate_c_per_min: float | None = None,
    max_examples: int = 5,
) -> dict[str, Any]:
    """Flag only existing rise events for source review; cannot vet unreported samples."""
    bounds = {
        "min_temperature_c": min_temperature_c,
        "max_temperature_c": max_temperature_c,
        "max_reported_rate_c_per_min": max_reported_rate_c_per_min,
    }
    if all(value is None for value in bounds.values()):
        raise ValueError("Specify at least one source-review bound")
    bounds = {
        name: _finite_number(value, name) if value is not None else None
        for name, value in bounds.items()
    }
    low = bounds["min_temperature_c"]
    high = bounds["max_temperature_c"]
    rate_ceiling = bounds["max_reported_rate_c_per_min"]
    if low is not None and high is not None and low > high:
        raise ValueError("min_temperature_c cannot exceed max_temperature_c")
    if rate_ceiling is not None and rate_ceiling <= 0:
        raise ValueError("max_reported_rate_c_per_min must be positive")
    if (
        isinstance(max_examples, bool)
        or not isinstance(max_examples, int)
        or not 0 <= max_examples <= 100
    ):
        raise ValueError("max_examples must be an integer between 0 and 100")
    if not isinstance(result, dict) or result.get("schema_version") != 9:
        raise ValueError("A BatteryLog result-v9 payload is required")
    report = result.get("failure_models")
    if not isinstance(report, dict) or not isinstance(report.get("evaluations"), list):
        raise ValueError("result-v9 failure-model evaluations are missing")  # noqa: TRY004
    matches = [
        item
        for item in report["evaluations"]
        if isinstance(item, dict) and item.get("code") == "TEMPERATURE_RISE_HIGH"
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("events"), list):
        raise ValueError("Exactly one configured temperature-rise evaluation is required")

    events = matches[0]["events"]
    flagged = 0
    reason_counts: Counter[str] = Counter()
    sensor_counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict) or event.get("code") != "TEMPERATURE_RISE_HIGH":
            raise ValueError(f"Invalid temperature-rise event at index {index}")
        evidence = event.get("evidence")
        signals = event.get("signals")
        if (
            not isinstance(evidence, dict)
            or not isinstance(signals, list)
            or not signals
            or not isinstance(signals[0], str)
        ):
            raise ValueError(f"Invalid temperature evidence at index {index}")
        before = _finite_number(evidence.get("previous_temperature_c"), "previous_temperature_c")
        after = _finite_number(evidence.get("temperature_c"), "temperature_c")
        observed_rate = _finite_number(event.get("measured_value"), "measured_value")
        peak_time = _finite_number(event.get("peak_time_s"), "peak_time_s")
        reasons = []
        if low is not None and min(before, after) < low:
            reasons.append("temperature_below_review_floor")
        if high is not None and max(before, after) > high:
            reasons.append("temperature_above_review_ceiling")
        if rate_ceiling is not None and observed_rate > rate_ceiling:
            reasons.append("reported_rise_above_review_ceiling")
        if not reasons:
            continue
        flagged += 1
        reason_counts.update(reasons)
        # The first signal carries the numerical evidence when peak rates tie.
        sensor_counts[signals[0]] += 1
        if len(examples) < max_examples:
            examples.append(
                {
                    "event_index": index,
                    "peak_time_s": peak_time,
                    "representative_signal": signals[0],
                    "previous_temperature_c": before,
                    "temperature_c": after,
                    "reported_rate_c_per_min": observed_rate,
                    "reasons": reasons,
                }
            )
    return {
        "scope": "existing_temperature_rise_events_only",
        "interpretation": "Source-review flags, not proof of sensor faults or false alarms",
        "bounds": bounds,
        "temperature_events_reviewed": len(events),
        "events_flagged": flagged,
        "events_without_review_flags": len(events) - flagged,
        "reason_counts": dict(sorted(reason_counts.items())),
        "representative_sensor_counts": dict(sorted(sensor_counts.items())),
        "examples": examples,
    }


def _reject_nonfinite_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON value: {value}")


def _strict_float(value: str) -> float:
    return _finite_number(float(value), "JSON number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"Duplicate JSON key {key!r}")
        data[key] = value
    return data


def _validate_source_result(result: dict[str, Any]) -> None:
    """Apply Core's structural AND semantic result-v9 contracts before analysis."""
    from jsonschema import Draft202012Validator

    from batterylog import validate_result_semantics

    schema_path = files("batterylog").joinpath("schema", "result-v9.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(result)
    validate_result_semantics(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_json", type=Path)
    parser.add_argument("--min-temperature-c", type=float)
    parser.add_argument("--max-temperature-c", type=float)
    parser.add_argument("--max-reported-rate-c-per-min", type=float)
    parser.add_argument("--max-examples", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        with args.result_json.open(encoding="utf-8") as source:
            result = json.load(
                source,
                parse_constant=_reject_nonfinite_constant,
                parse_float=_strict_float,
                object_pairs_hook=_unique_object,
            )
        _validate_source_result(result)
        summary = triage_temperature_events(
            result,
            min_temperature_c=args.min_temperature_c,
            max_temperature_c=args.max_temperature_c,
            max_reported_rate_c_per_min=args.max_reported_rate_c_per_min,
            max_examples=args.max_examples,
        )
    except (OSError, ValueError, TypeError, KeyError, OverflowError, ValidationError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
