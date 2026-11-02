# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Deterministic independent constant-envelope and capture resource campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from batterylog_research import precharge_capture_review as capture
from batterylog_research import precharge_curve_review as curve

TOLERANCE = 8 * sys.float_info.epsilon
PROFILES = (
    "million_full",
    "five_million_full",
    "million_1000_spans",
    "million_over_bound",
    "twenty_thousand_spans",
)


def beyond(value, bound):
    return value > bound and not math.isclose(value, bound, rel_tol=TOLERANCE, abs_tol=0)


def fingerprint(arrays):
    digest = hashlib.sha256()
    for value in arrays:
        a = np.asarray(value)
        digest.update(str((a.dtype.str, a.shape)).encode())
        digest.update(a.tobytes())
    return digest.hexdigest()


def reference(horizon, current_max=2):
    return np.array([[0, 0, current_max, 0, 0.2], [horizon, 0, current_max, 0, 0.2]])


def constant_oracle(arrays, *, horizon, current_max, gap):
    """Manual row scanner; never imports production partition/validation helpers."""
    times, phase, currents, packs, buses = arrays
    intervals = []
    beginning = None
    for i, state in enumerate(phase):
        if state == 1 and beginning is None:
            beginning = i
        elif state != 1 and beginning is not None:
            intervals.append((beginning, i))
            beginning = None
    if beginning is not None:
        intervals.append((beginning, len(phase)))
    expected = []
    for start, stop in intervals:
        onset = start > 0 and phase[start - 1] == 0
        if onset:
            delta = float(times[start]) - float(times[start - 1])
            onset = delta > 0 and not beyond(delta, gap)
        reviewed, bad = 0, []
        completed = False
        last = bracket = None
        peak_i = peak_v = 0.0
        if onset:
            for i in range(start, stop):
                delta = float(times[i]) - float(times[i - 1])
                if delta <= 0 or beyond(delta, gap):
                    break
                current, pack, bus = float(currents[i]), float(packs[i]), float(buses[i])
                if not all(math.isfinite(x) for x in (current, pack, bus)) or pack <= 0:
                    break
                elapsed = float(times[i]) - float(times[start])
                if beyond(elapsed, horizon):
                    completed, bracket = True, [last, elapsed]
                    break
                voltage_gap = (pack - bus) / pack
                excess_i = abs(current) - current_max if beyond(abs(current), current_max) else 0
                if beyond(0, voltage_gap):
                    excess_v = -voltage_gap
                elif beyond(voltage_gap, 0.2):
                    excess_v = voltage_gap - 0.2
                else:
                    excess_v = 0.0
                reviewed += 1
                last = elapsed
                peak_i, peak_v = max(peak_i, excess_i), max(peak_v, excess_v)
                if excess_i or excess_v:
                    bad.append(i)
                if not beyond(horizon, elapsed):
                    completed, bracket = True, [elapsed, elapsed]
                    break
        expected.append(
            {
                "start": start,
                "stop": stop,
                "onset": bool(onset),
                "reviewed": reviewed,
                "bad": bad,
                "covered": completed,
                "last": last,
                "bracket": bracket,
                "peak_i": peak_i,
                "peak_v": peak_v,
            }
        )
    return expected


def check_case(arrays, *, horizon=2, current_max=2, gap=1, examples=5):
    envelope = reference(horizon, current_max)
    before = fingerprint((*arrays, envelope))
    expected = constant_oracle(arrays, horizon=horizon, current_max=current_max, gap=gap)
    result = capture.review_precharge_capture(
        *arrays, envelope, max_gap_s=gap, max_examples=examples
    )
    assert before == fingerprint((*arrays, envelope)), "source mutation"
    assert len(result["active_spans"]) == len(expected), "span count"
    assert result["observed_activations"] == sum(x["onset"] for x in expected), "onset count"
    assert result["covered_reference_intervals"] == sum(x["covered"] for x in expected), "coverage"
    assert result["reviewed_samples"] == sum(x["reviewed"] for x in expected), "reviewed count"
    assert result["outside_envelope_samples"] == sum(len(x["bad"]) for x in expected), "deviations"
    phase = arrays[1]
    assert result["known_active_samples"] == sum(v == 1 for v in phase), "known phase"
    assert result["unknown_phase_samples"] == sum(v != 0 and v != 1 for v in phase), "unknown phase"
    for actual, wanted in zip(result["active_spans"], expected, strict=True):
        assert actual["source_active_start_index"] == wanted["start"], "start index"
        assert actual["source_active_stop_index_exclusive"] == wanted["stop"], "stop index"
        assert actual["source_review_start_index"] == max(0, wanted["start"] - 1), "context start"
        assert actual["source_review_stop_index_exclusive"] == min(len(phase), wanted["stop"] + 1)
        assert actual["activation_observed"] == wanted["onset"]
        assert actual["declared_interval_covered"] == wanted["covered"]
        assert actual["reviewed_samples"] == wanted["reviewed"]
        assert actual["outside_envelope_samples"] == len(wanted["bad"])
        assert actual["last_qualified_elapsed_s"] == wanted["last"]
        assert actual["reference_horizon_bracket_s"] == wanted["bracket"]
        assert actual["max_current_excess_a"] == wanted["peak_i"]
        assert actual["max_voltage_gap_fraction_excess"] == wanted["peak_v"]
        assert [v["sample_index"] for v in actual["examples"]] == wanted["bad"][:examples]
        for example in actual["examples"]:
            i = example["sample_index"]
            assert example["current_a"] == arrays[2][i]
            assert example["pack_voltage_v"] == arrays[3][i]
            assert example["dc_link_voltage_v"] == arrays[4][i]
    json.dumps(result, allow_nan=False)
    return result, expected


def random_campaign(count, seed):
    rng = np.random.default_rng(seed)
    totals = {
        "cases": count,
        "rows": 0,
        "spans": 0,
        "reviewed_samples": 0,
        "outside_samples": 0,
        "repeat_checks": 0,
        "slice_checks": 0,
    }
    for ordinal in range(count):
        n = int(rng.integers(8, 401))
        states, remaining = [], n
        while remaining:
            size = min(int(rng.integers(1, 26)), remaining)
            states.extend([rng.choice([0.0, 1.0, np.nan], p=[0.3, 0.65, 0.05])] * size)
            remaining -= size
        phase = np.asarray(states)
        phase[rng.random(n) < 0.03] = np.nan
        deltas = rng.choice([0, 0.125, 0.25, 0.5, 2], n, p=[0.02, 0.5, 0.3, 0.15, 0.03])
        times = np.cumsum(deltas) + int(rng.integers(-10, 11))
        current = rng.choice([-3.0, -2, -1, 0, 1, 2, 3], n)
        current[rng.random(n) < 0.01] = np.nan
        pack = np.full(n, 100.0)
        pack[rng.random(n) < 0.01] = 0
        bus = rng.choice([70.0, 90, 100, 110], n)
        bus[rng.random(n) < 0.01] = np.inf
        arrays = times, phase, current, pack, bus
        for a in arrays:
            a.flags.writeable = False
        examples = int(rng.integers(0, 6))
        try:
            result, expected = check_case(arrays, examples=examples)
            if ordinal % 100 == 0:
                repeated = capture.review_precharge_capture(
                    *arrays, reference(2), max_gap_s=1, max_examples=examples
                )
                assert result == repeated, "nondeterministic result"
                totals["repeat_checks"] += 1
                for actual, wanted in zip(result["active_spans"], expected, strict=True):
                    low, high = max(0, wanted["start"] - 1), min(n, wanted["stop"] + 1)
                    single = curve.review_precharge_curve(
                        *(a[low:high] for a in arrays),
                        reference(2),
                        max_gap_s=1,
                        max_examples=examples,
                    )
                    for example in single["examples"]:
                        example["sample_index"] += low
                    assert all(actual[key] == value for key, value in single.items()), (
                        "slice parity"
                    )
                    totals["slice_checks"] += 1
        except Exception as exc:
            raise AssertionError(f"seed={seed}, random case={ordinal}: {exc}") from exc
        totals["rows"] += n
        totals["spans"] += len(expected)
        totals["reviewed_samples"] += result["reviewed_samples"]
        totals["outside_samples"] += result["outside_envelope_samples"]
        if (ordinal + 1) % 1000 == 0:
            print(f"Oracle: {ordinal + 1}/{count} cases", flush=True)
    return totals


def scale_campaign():
    count = 0
    for t_exp in (-300, -150, -10, 0, 10, 150, 300):
        for i_exp in (-300, -150, -10, 0, 10, 150, 300):
            for v_exp in (-300, -150, -10, 0, 10, 150, 300):
                ts, cs, vs = 10.0**t_exp, 10.0**i_exp, 10.0**v_exp
                arrays = (
                    np.array([-ts, 0, ts, 2 * ts]),
                    np.array([0, 1, 1, 1]),
                    np.array([0, cs, 3 * cs, cs]),
                    np.full(4, 100 * vs),
                    np.full(4, 90 * vs),
                )
                result, _ = check_case(arrays, horizon=2 * ts, current_max=2 * cs, gap=2 * ts)
                assert result["covered_reference_intervals"] == 1
                assert result["outside_envelope_samples"] == 1
                count += 1
    return {"cases": count, "exponents": [-300, -150, -10, 0, 10, 150, 300]}


def worker(name):
    if name == "twenty_thousand_spans":
        phase = np.tile([0, 1, 1, 1, 0], 20_000)
        horizon, max_spans = 2 / 1024, 20_000
    elif name == "million_1000_spans":
        phase = (np.arange(1_001_000) % 1001 != 0).astype(float)
        horizon, max_spans = 999 / 1024, 1000
    elif name == "million_over_bound":
        phase = (np.arange(1_000_000) % 2).astype(float)
        horizon, max_spans = 2 / 1024, 1000
    else:
        phase = np.ones(5_000_000 if name == "five_million_full" else 1_000_000)
        phase[0] = 0
        horizon, max_spans = (len(phase) - 2) / 1024, 1000
    n = len(phase)
    times = np.arange(n) / 1024
    current = np.ones(n)
    current[np.arange(n) % 7 == 0] = 3
    pack, bus = np.full(n, 100.0), np.full(n, 90.0)
    arrays = times, phase, current, pack, bus
    envelope = reference(horizon)
    before = fingerprint((*arrays, envelope))
    for a in (*arrays, envelope):
        a.flags.writeable = False
    started = time.perf_counter()
    if name == "million_over_bound":

        def forbidden(*args, **kwargs):
            raise AssertionError("Over-bound capture reached a curve review")

        capture.review_precharge_curve = forbidden
        try:
            capture.review_precharge_capture(*arrays, envelope, max_gap_s=2 / 1024)
        except ValueError as exc:
            assert str(exc) == "Capture has 500000 active spans; max_spans is 1000"
            result = {"rejection": str(exc), "curve_reviews": 0}
        else:
            raise AssertionError("Over-bound capture was accepted")
    else:
        result = capture.review_precharge_capture(
            *arrays, envelope, max_gap_s=2 / 1024, max_spans=max_spans, max_examples=1
        )
    elapsed = time.perf_counter() - started
    assert before == fingerprint((*arrays, envelope)), "large source mutation"
    if name != "million_over_bound":
        expected_spans = (
            20_000
            if name == "twenty_thousand_spans"
            else (1000 if name == "million_1000_spans" else 1)
        )
        assert len(result["active_spans"]) == expected_spans
        assert result["covered_reference_intervals"] == expected_spans
        assert result["reviewed_samples"] == int(np.count_nonzero(phase == 1))
        assert result["outside_envelope_samples"] == int(
            np.count_nonzero((phase == 1) & (current > 2))
        )
        assert all(len(s["examples"]) <= 1 for s in result["active_spans"])
    size = len(json.dumps(result, allow_nan=False, separators=(",", ":")).encode())
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
            1024**2 if sys.platform == "darwin" else 1024
        )
    except ImportError:
        peak = None
    return {
        "profile": name,
        "rows": n,
        "review_wall_s": elapsed,
        "peak_process_rss_mib": peak,
        "serialized_result_bytes": size,
        "source_unchanged": True,
        "observed_activations": result.get("observed_activations"),
        "covered_reference_intervals": result.get("covered_reference_intervals"),
        "reviewed_samples": result.get("reviewed_samples"),
        "outside_envelope_samples": result.get("outside_envelope_samples"),
        "rejection": result.get("rejection"),
        "curve_reviews": result.get("curve_reviews"),
    }


def source_hashes():
    return {
        Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        for p in (curve.__file__, capture.__file__, __file__)
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--random-cases", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--worker", choices=PROFILES)
    args = parser.parse_args(argv)
    if args.worker:
        print(json.dumps(worker(args.worker), allow_nan=False))
        return 0
    if args.output is None or args.random_cases < 1:
        parser.error("Require --output and positive --random-cases")
    if args.output.exists():
        raise FileExistsError(args.output)
    hashes = source_hashes()
    started = time.perf_counter()
    random_result = random_campaign(args.random_cases, args.seed)
    scales = scale_campaign()
    profiles = []
    for profile in PROFILES:
        print(f"Resource profile: {profile}", flush=True)
        run = subprocess.run(
            [sys.executable, "-m", "batterylog_research.precharge_stress", "--worker", profile],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        record = json.loads(run.stdout)
        profiles.append(record)
        print(
            f"Verified {profile}: {record['review_wall_s']:.2f}s, "
            f"peak {record['peak_process_rss_mib']} MiB",
            flush=True,
        )
    assert source_hashes() == hashes, "source changed during campaign"
    report = {
        "scope": "synthetic_software_stress_not_physical_fault_validation",
        "seed": args.seed,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "source_sha256": hashes,
        "oracle_scope": "independent manual scanner and constant reference bands",
        "random": random_result,
        "scales": scales,
        "profiles": profiles,
        "campaign_wall_s": time.perf_counter() - started,
        "rss_scope": "whole isolated worker including imports, inputs, review, hashing and JSON",
    }
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
