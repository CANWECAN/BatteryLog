# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Bounded investigative comparisons, not new BatteryLog rules or fault labels."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from batterylog import CellSagConfig, FailureModelConfig, TemperatureRiseConfig
from batterylog.analysis.core import _analyze_battery_frame

REL = 8 * np.finfo(float).eps


def above(value, limit):
    # math.isclose uses max(abs(value), abs(limit)); NumPy uses only the
    # second argument. Both directions preserve Core's symmetric boundary.
    equivalent = np.isclose(value, limit, rtol=REL, atol=0) | np.isclose(
        limit, value, rtol=REL, atol=0
    )
    return (value > limit) & ~equivalent


def temperature_rates(times, temperatures, *, max_gap_s, min_interval_s, window_s):
    """Adjacent pair and trailing endpoint secant; never infer sensor refresh times.

    Window endpoints are original samples. The newest reference at least W seconds
    old must lie in the same valid, positive-time, gap-bounded block. No fit,
    interpolation, physical outlier removal or rewriting of Core events occurs.
    This full-array investigation uses memory proportional to the input.
    """
    for value in (max_gap_s, min_interval_s, window_s):
        if isinstance(value, bool) or not np.isfinite(value) or value <= 0:
            raise ValueError("Timing parameters must be finite and positive")
    times = np.asarray(times, dtype=float)
    temperatures = np.asarray(temperatures, dtype=float)
    if (
        times.ndim != 1
        or temperatures.ndim != 2
        or temperatures.shape[0] != len(times)
        or temperatures.shape[1] == 0
        or len(times) == 0
        or not np.isfinite(times).all()
        or (np.diff(times) < 0).any()
    ):
        raise ValueError("Require nonempty aligned samples and finite nondecreasing time")
    valid = np.isfinite(temperatures).all(axis=1)
    dt = np.diff(times)
    eligible = valid[1:] & valid[:-1] & (dt > 0) & ~above(dt, max_gap_s)
    adjacent = np.full(temperatures.shape, np.nan)
    use = eligible & ~above(min_interval_s, dt)
    with np.errstate(over="raise", invalid="ignore"):
        adjacent[1:][use] = np.diff(temperatures, axis=0)[use] / dt[use, None] * 60
    window = np.full(temperatures.shape, np.nan)
    block_start = 0
    for i in range(len(times)):
        if not valid[i] or i == 0 or not eligible[i - 1]:
            block_start = i
        if not valid[i]:
            continue
        j = int(np.searchsorted(times, times[i] - window_s, side="right") - 1)
        if j < block_start or j >= i:
            continue
        span = times[i] - times[j]
        if above(span, window_s + max_gap_s):
            continue
        with np.errstate(over="raise", invalid="raise"):
            window[i] = (temperatures[i] - temperatures[j]) / span * 60
    if np.isinf(adjacent).any() or np.isinf(window).any():
        raise ValueError("Rate calculation overflowed")
    return adjacent, window


def rate_summary(times, rates, threshold):
    valid = np.isfinite(rates).all(axis=1)
    exceeding = np.zeros(rates.shape, dtype=bool)
    exceeding[valid] = above(rates[valid], threshold)
    rows = exceeding.any(axis=1)
    return {
        "eligible_observations": int(valid.sum()),
        "exceeding_observations": int(rows.sum()),
        "first_exceeding_time_s": float(times[np.flatnonzero(rows)[0]]) if rows.any() else None,
        "peak_c_per_min": float(rates[valid].max()) if valid.any() else None,
        "peak_exceeding_sensor_count": int(exceeding.sum(axis=1).max()),
    }


def sag_context(times, current, config, *, max_gap_s):
    """Explain missing load observations with an independent source-state trace.

    Low-current span is observed, not verified electrochemical relaxation. Counts
    describe load episodes, not Core incomplete_intervals (which also include
    interruption accounting). A baseline is consumed at each load onset.
    """
    times, current = np.asarray(times, dtype=float), np.asarray(current, dtype=float)
    if (
        times.ndim != 1
        or current.shape != times.shape
        or not len(times)
        or not np.isfinite(times).all()
        or not np.isfinite(current).all()
        or (np.diff(times) < 0).any()
        or not np.isfinite(max_gap_s)
        or max_gap_s <= 0
    ):
        raise ValueError("Require finite aligned current/time and positive gap")
    sign = 1 if config.positive_direction == "discharge" else -1
    loaded = ~above(config.load_min_discharge_a, current * sign)
    low = ~above(np.abs(current), config.baseline_max_abs_current_a)
    reasons = Counter()
    episodes = []
    baseline = low_start = pending = None
    previous_low = False
    for i, t in enumerate(times):
        broken = i > 0 and above(t - times[i - 1], max_gap_s)
        if broken:
            if pending is not None:
                pending["ended_by"] = "gap"
                episodes.append(pending)
            baseline = low_start = pending = None
            previous_low = False
        if not loaded[i]:
            if pending is not None:
                pending["ended_by"] = "load_below_threshold"
                episodes.append(pending)
                pending = None
            if low[i]:
                if not previous_low:
                    low_start = t
                baseline = (t, low_start)
            low_start = low_start if low[i] else None
            previous_low = bool(low[i])
            continue
        previous_low = False
        low_start = None
        if pending is None:
            age = t - baseline[0] if baseline is not None else None
            reason = (
                "missing_rest_reference"
                if baseline is None
                else "nonpreceding_rest_reference"
                if age <= 0
                else "stale_rest_reference"
                if above(age, config.baseline_max_age_s)
                else "reference_available"
            )
            pending = {
                "load_start_s": float(t),
                "last_load_sample_s": float(t),
                "reference_age_at_onset_s": float(age) if age is not None else None,
                "observed_low_current_span_s": float(baseline[0] - baseline[1])
                if baseline is not None
                else None,
                "reference_reason": reason,
                "eligible_samples": 0,
            }
            reasons[reason] += 1
            baseline = None
        pending["last_load_sample_s"] = float(t)
        if pending["reference_reason"] == "reference_available" and not above(
            config.settling_s, t - pending["load_start_s"]
        ):
            pending["eligible_samples"] += 1
    if pending is not None:
        pending["ended_by"] = "capture_end"
        episodes.append(pending)
    return {
        "load_episodes": len(episodes),
        "reference_reason_counts": dict(sorted(reasons.items())),
        "episodes_without_eligible_samples": sum(not e["eligible_samples"] for e in episodes),
        "episodes": episodes,
    }


def _frame(times, temperatures, current=None):
    temperatures = np.asarray(temperatures)
    if temperatures.ndim == 1:
        temperatures = temperatures[:, None]
    data = {"timestamp_s": times, **{f"temp_{i + 1}_c": v for i, v in enumerate(temperatures.T)}}
    data.update({f"cell_{i}_v": np.full(len(times), 3.5) for i in range(1, 4)})
    if current is not None:
        data["pack_current_a"] = current
    return pd.DataFrame(data)


def synthetic_campaign():
    times = np.arange(0, 20.01, 0.32)
    ramps = 25 + times * 12 / 60
    quantized = np.round(ramps / 0.1) * 0.1
    zoh = 25 + np.floor(times / 2) * 2 * 12 / 60
    scenarios = {
        "constant": (np.full(len(times), 25.0), None),
        "linear_12_c_per_min": (ramps, 0.0),
        "quantized_12_c_per_min": (quantized, 0.0),
        "zoh_12_c_per_min": (zoh, 0.0),
        "single_0_1_c_step": (25 + (times >= 5) * 0.1, 5.0),
        "short_0_5_c_pulse": (25 + ((times >= 5) & (times < 5.64)) * 0.5, 5.0),
        "implausible_655_c_pulse": (25 + ((times >= 5) & (times < 5.64)) * 630.28, 5.0),
    }
    records = []
    for name, (temp, onset) in scenarios.items():
        frame = _frame(times, temp)
        original = _analyze_battery_frame(
            frame,
            failure_models=FailureModelConfig(1, temperature_rise=TemperatureRiseConfig(10, 0.25)),
        )["failure_models"]["evaluations"][0]
        adjacent, _ = temperature_rates(
            times, temp[:, None], max_gap_s=1, min_interval_s=0.25, window_s=1
        )
        pair_summary = rate_summary(times, adjacent, 10)
        assert pair_summary["eligible_observations"] == original["evaluated_samples"]
        assert pair_summary["exceeding_observations"] == sum(
            e["sample_count"] for e in original["events"]
        )
        windows = {}
        for horizon in (1, 2, 5):
            _, rates = temperature_rates(
                times, temp[:, None], max_gap_s=1, min_interval_s=0.25, window_s=horizon
            )
            summary = rate_summary(times, rates, 10)
            first = summary["first_exceeding_time_s"]
            summary["delay_from_declared_onset_s"] = (
                first - onset if first is not None and onset is not None else None
            )
            windows[str(horizon)] = summary
        records.append(
            {
                "scenario": name,
                "declared_onset_s": onset,
                "core_status": original["status"],
                "adjacent": pair_summary,
                "endpoint_windows_s": windows,
            }
        )
    config = CellSagConfig("discharge", 0.05, 2, 5, 0.5, 0.05)
    sag_records = []
    for name, current in {
        "rest_then_load": [0, 0, 0, 3, 3, 0],
        "dynamic_load_without_new_rest": [0, 3, 3, 1, 3, 3],
        "single_low_current_reference": [1, 0, 3, 3, 1, 1],
        "stale_reference": [0, 1, 1, 1, 1, 1, 3, 3],
    }.items():
        t = np.arange(len(current), dtype=float)
        result = _analyze_battery_frame(
            _frame(t, np.full(len(t), 25), current),
            failure_models=FailureModelConfig(1, cell_sag=config),
        )
        observed = result["failure_models"]["evaluations"][0]
        context = sag_context(t, current, config, max_gap_s=1)
        assert (
            sum(e["eligible_samples"] for e in context["episodes"]) == observed["evaluated_samples"]
        )
        sag_records.append(
            {
                "scenario": name,
                "core_status": observed["status"],
                "core_incomplete_intervals": observed["incomplete_intervals"],
                **context,
            }
        )
    return {"temperature": records, "sag": sag_records}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = {
        "scope": "synthetic_characterization_only",
        "production_decisions_changed": False,
        "campaign": synthetic_campaign(),
    }
    report["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
