# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Compare one sampled precharge interval to a declared envelope; no diagnosis."""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import MAX_EMAX, MIN_EMIN, Decimal, localcontext
from itertools import pairwise
from math import isclose, isfinite
from numbers import Real
from pathlib import Path

import numpy as np
import pandas as pd

from batterylog import FailureModelConfig, PrechargeCurrentConfig
from batterylog.analysis.core import _analyze_battery_frame

REL = 8 * np.finfo(float).eps


def _above(value, limit):
    return value > limit and not isclose(value, limit, rel_tol=REL, abs_tol=0)


def _numeric(values, name, *, phase=False):
    raw = np.asarray(values)
    boolean_measurement = not phase and any(
        isinstance(v, (bool, np.bool_)) for v in np.asarray(values, dtype=object).flat
    )
    if raw.dtype.kind not in ("biuf" if phase else "iuf") or boolean_measurement:
        raise ValueError(f"{name} requires real numeric samples")
    if phase:
        # Classify the producer's values before binary64 rounding can turn an
        # unknown extended-precision value into an apparently valid 0 or 1.
        return np.where((raw == 0) | (raw == 1), raw, np.nan).astype(float)
    return raw.astype(float)


def _excess(value, low, high):
    if _above(low, value):
        excess = float(low - value)
    elif _above(value, high):
        excess = float(value - high)
    else:
        excess = 0.0
    if not isfinite(excess):
        raise ValueError("Declared-envelope comparison overflowed")
    return excess


def _validate_controls(max_gap_s, max_examples):
    """Validate controls and return a finite positive binary64 gap."""
    try:
        gap = float(max_gap_s)
    except (OverflowError, TypeError, ValueError):
        raise ValueError("max_gap_s must be finite and positive") from None
    if (
        isinstance(max_gap_s, bool)
        or not isinstance(max_gap_s, Real)
        or not isfinite(gap)
        or gap <= 0
    ):
        raise ValueError("max_gap_s must be finite and positive")
    if (
        isinstance(max_examples, bool)
        or not isinstance(max_examples, int)
        or not 0 <= max_examples <= 100
    ):
        raise ValueError("max_examples must be an integer from 0 to 100")
    return gap


def _decimal_delta(value, origin):
    """Keep decimal timestamp cancellation exact, independent of ambient context."""
    if not origin:
        return value
    if not value:
        return origin.copy_negate()
    precision = (
        max(value.adjusted(), origin.adjusted())
        - min(value.as_tuple().exponent, origin.as_tuple().exponent)
        + 2
    )
    with localcontext() as context:
        context.prec = max(28, precision)
        context.Emax, context.Emin, context.clamp = MAX_EMAX, MIN_EMIN, 0
        return value - origin


def _validated_source(times, active, current_a, pack_voltage_v, dc_link_voltage_v):
    original_time = np.asarray(times)
    decimal_clock = original_time.dtype.kind == "O" and all(
        isinstance(value, Decimal) for value in original_time.flat
    )
    if decimal_clock:
        if (
            original_time.ndim != 1
            or not original_time.size
            or any(not value.is_finite() for value in original_time)
        ):
            raise ValueError("Require finite one-dimensional decimal source time")
        time = original_time.astype(float)
    else:
        time = _numeric(times, "time")
    phase = _numeric(active, "phase", phase=True)
    current = _numeric(current_a, "current")
    pack = _numeric(pack_voltage_v, "pack voltage")
    bus = _numeric(dc_link_voltage_v, "DC-link voltage")
    arrays = (time, phase, current, pack, bus)
    if time.ndim != 1 or not time.size or any(a.ndim != 1 or a.shape != time.shape for a in arrays):
        raise ValueError("Require nonempty aligned one-dimensional source arrays")
    with np.errstate(over="ignore"):
        intervals = (
            np.asarray(
                [float(_decimal_delta(b, a)) for a, b in pairwise(original_time)],
                dtype=float,
            )
            if decimal_clock
            else np.diff(time)
        )
    if (
        not np.isfinite(time).all()
        or not np.isfinite(intervals).all()
        or (original_time[1:] < original_time[:-1]).any()
        or (intervals < 0).any()
    ):
        raise ValueError("Require finite nondecreasing source time and finite intervals")
    return time, phase, current, pack, bus, intervals


def _validated_envelope(envelope):
    bounds = _numeric(envelope, "envelope")
    if (
        bounds.ndim != 2
        or bounds.shape[1] != 5
        or len(bounds) < 2
        or not np.isfinite(bounds).all()
        or bounds[0, 0] != 0
        or (np.diff(bounds[:, 0]) <= 0).any()
        or (bounds[:, 1:3] < 0).any()
        or (bounds[:, 1] > bounds[:, 2]).any()
        or (bounds[:, 3] > bounds[:, 4]).any()
    ):
        raise ValueError(
            "Require ordered finite bounds, nonnegative current and time starting at zero"
        )
    return bounds


def review_precharge_curve(
    times,
    active,
    current_a,
    pack_voltage_v,
    dc_link_voltage_v,
    envelope,
    *,
    max_gap_s,
    max_examples=5,
):
    """Inspect a declared interval without changing recorded samples or Core results.

    Envelope columns: elapsed s, current magnitude lower/upper A, relative
    pack/DC-link voltage-gap lower/upper. Only the reference is interpolated.
    Duplicate times conservatively interrupt this study's qualification.
    """
    max_gap_s = _validate_controls(max_gap_s, max_examples)
    time, phase, current, pack, bus, intervals = _validated_source(
        times, active, current_a, pack_voltage_v, dc_link_voltage_v
    )
    # The scalar _above comparator uses math.isclose's symmetric tolerance.
    # NumPy scales by its second argument; both orders preserve the same edge.
    close_to_gap = np.isclose(intervals, max_gap_s, rtol=REL, atol=0) | np.isclose(
        max_gap_s, intervals, rtol=REL, atol=0
    )
    observed_edges = (
        (phase[:-1] == 0)
        & (phase[1:] == 1)
        & (intervals > 0)
        & ((intervals <= max_gap_s) | close_to_gap)
    )
    if observed_edges.sum() > 1:
        raise ValueError("Review multiple observed activations in separate calls")
    bounds = _validated_envelope(envelope)

    original_time = np.asarray(times)
    decimal_clock = original_time.dtype.kind == "O"
    start_index = None
    start = previous = bracket = None
    lost = complete = False
    reviewed = outside = 0
    current_peak = gap_peak = 0.0
    last_elapsed = horizon_bracket = None
    reasons = set()
    examples = []
    horizon = float(bounds[-1, 0])
    for i, t in enumerate(time):
        if i and (intervals[i - 1] <= 0 or _above(intervals[i - 1], max_gap_s)):
            if start is not None:
                lost = True
                reasons.add("source_interval_interrupted")
            previous = None
        if not np.isfinite(phase[i]) or phase[i] not in (0, 1):
            reasons.add("unknown_phase_sample")
            lost = lost or start is not None
            previous = None
            continue
        if not phase[i]:
            if start is not None and not complete:
                reasons.add("phase_ended_before_coverage_completed")
                lost = True
            previous = (float(t), False)
            continue
        if previous is not None and not previous[1]:
            if start is not None:
                raise ValueError("Review multiple observed activations in separate calls")
            start = float(t)
            start_index = i
            bracket = [previous[0], start]
        elif start is None:
            reasons.add("activation_not_observed")
        previous = (float(t), True)
        if start is None or lost:
            continue
        if not all(isfinite(v) for v in (current[i], pack[i], bus[i])) or pack[i] <= 0:
            reasons.add("invalid_active_measurement")
            lost = True
            previous = None
            continue
        elapsed = (
            float(_decimal_delta(original_time[i], original_time[start_index]))
            if decimal_clock
            else float(t) - start
        )
        if not isfinite(elapsed):
            raise ValueError("Elapsed-time calculation overflowed")
        if _above(elapsed, horizon):
            complete = True
            horizon_bracket = [last_elapsed, elapsed]
            break
        voltage_gap = (float(pack[i]) - float(bus[i])) / float(pack[i])
        if not isfinite(voltage_gap):
            raise ValueError("Relative voltage-gap calculation overflowed")
        limits = [float(np.interp(elapsed, bounds[:, 0], bounds[:, col])) for col in range(1, 5)]
        if not all(isfinite(v) for v in limits):
            raise ValueError("Declared-envelope interpolation overflowed")
        current_excess = _excess(abs(float(current[i])), *limits[:2])
        gap_excess = _excess(voltage_gap, *limits[2:])
        reviewed += 1
        last_elapsed = elapsed
        current_peak = max(current_peak, current_excess)
        gap_peak = max(gap_peak, gap_excess)
        if current_excess or gap_excess:
            outside += 1
            if len(examples) < max_examples:
                examples.append(
                    {
                        "sample_index": i,
                        "elapsed_s": elapsed,
                        "current_a": float(current[i]),
                        "pack_voltage_v": float(pack[i]),
                        "dc_link_voltage_v": float(bus[i]),
                        "voltage_gap_fraction": voltage_gap,
                        "declared_current_bounds_a": limits[:2],
                        "declared_voltage_gap_bounds": limits[2:],
                        "current_excess_a": current_excess,
                        "voltage_gap_fraction_excess": gap_excess,
                    }
                )
        if not _above(horizon, elapsed):
            complete = True
            horizon_bracket = [elapsed, elapsed]
            break
    if start is None:
        reasons.add("no_observed_precharge_activation")
    elif not complete and not reasons:
        reasons.add("capture_ended_before_reference_horizon")
    return {
        "scope": "declared_interval_observations_only",
        "production_decisions_changed": False,
        "reference_horizon_s": horizon,
        "observed_start_bracket_s": bracket,
        "last_qualified_elapsed_s": last_elapsed,
        "reference_horizon_bracket_s": horizon_bracket,
        "reviewed_samples": reviewed,
        "outside_envelope_samples": outside,
        "max_current_excess_a": current_peak,
        "max_voltage_gap_fraction_excess": gap_peak,
        "declared_interval_covered": complete,
        "incomplete_reasons": sorted(reasons),
        "examples": examples,
    }


def synthetic_cases():
    time = np.r_[-0.1, np.round(np.arange(0, 4.01, 0.1), 2), 4.1]
    active = ((time >= 0) & (time <= 4)).astype(float)
    elapsed = np.maximum(time, 0)
    expected = np.exp(-elapsed)
    current = 8 * expected
    bus = 400 * (1 - expected)
    current[active == 0] = 0
    pack = np.full(len(time), 400.0)
    knots = np.arange(0, 4.01, 0.25)
    reference = np.exp(-knots)
    envelope = np.column_stack(
        (
            knots,
            np.maximum(8 * reference - 0.2, 0),
            8 * reference + 0.2,
            np.maximum(reference - 0.02, 0),
            reference + 0.02,
        )
    )
    cases = {"declared_normal": (time, active, current, pack, bus)}
    slow = np.exp(-elapsed / 2.5)
    cases["slow_but_checkpoint_current_drop_sufficient"] = (
        time,
        active,
        np.where(active, 8 * slow, 0),
        pack,
        400 * (1 - slow),
    )
    disturbed_i, disturbed_v = current.copy(), bus.copy()
    pulse = (time >= 1.5) & (time <= 1.7)
    disturbed_i[pulse] += 2
    disturbed_v[pulse] -= 50
    cases["early_disturbance_then_checkpoint_recovers"] = (
        time,
        active,
        disturbed_i,
        pack,
        disturbed_v,
    )
    cases["interrupted_phase"] = (time, active * (time < 2), current, pack, bus)
    keep = (time < 1.5) | (time > 1.8)
    cases["missing_source_interval"] = tuple(a[keep] for a in (time, active, current, pack, bus))
    cases["capture_starts_active"] = tuple(a[1:] for a in (time, active, current, pack, bus))
    implausible = bus.copy()
    implausible[time == 1.5] = 1200
    cases["finite_voltage_inconsistency"] = (time, active, current, pack, implausible)
    return envelope, cases


def synthetic_campaign():
    envelope, cases = synthetic_cases()
    records = []
    for name, arrays in cases.items():
        time, active, current, pack, bus = arrays
        frame = pd.DataFrame(
            {
                "timestamp_s": time,
                "precharge_active": active,
                "pack_current_a": current,
                "pack_voltage_v": pack,
                "dc_link_voltage_v": bus,
                "temp_c": 25.0,
            }
        )
        # Self-consistent synthetic 96S context; no physical pack validation claim.
        for index in range(1, 97):
            frame[f"cell_{index}_v"] = pack / 96
        core = _analyze_battery_frame(
            frame,
            failure_models=FailureModelConfig(
                0.2, precharge_current=PrechargeCurrentConfig("precharge_active", 4, 8, 6)
            ),
        )["failure_models"]["evaluations"][0]
        observed = review_precharge_curve(*arrays, envelope, max_gap_s=0.2)
        records.append(
            {
                "scenario": name,
                "existing_checkpoint_status": core["status"],
                "existing_checkpoint_events": len(core["events"]),
                **observed,
            }
        )
    return {
        "scope": "synthetic_software_study_not_physical_fault_labels",
        "sample_interval_s": 0.1,
        "max_gap_s": 0.2,
        "envelope_columns": [
            "elapsed_s",
            "min_abs_current_a",
            "max_abs_current_a",
            "min_voltage_gap_fraction",
            "max_voltage_gap_fraction",
        ],
        "declared_envelope": envelope.tolist(),
        "existing_checkpoint": {"evaluation_s": 4, "min_start_abs_current_a": 8, "min_drop_a": 6},
        "scenarios": records,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = synthetic_campaign()
    report["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
