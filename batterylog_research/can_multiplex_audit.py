# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Observe declared CAN multiplex coverage and timing; never assemble a pack snapshot."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from batterylog_research.can_prepare import (
    _identifier,
    _keys,
    exact_timestamps,
    load_profile,
    publish_new_file,
    read_frames,
    sha256,
    validate_multiplexers,
)


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a positive finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return Decimal(str(value))


def _groups(values, name, *, allow_empty=False):
    if not isinstance(values, list) or (not values and not allow_empty):
        raise ValueError(f"Invalid {name}")
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
        raise ValueError(f"Invalid {name}")
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {name}")
    return values


def compile_audit(database, profile):
    _keys(
        profile,
        (
            "bus",
            "dbc_sha256",
            "frame_id",
            "extended",
            "selector",
            "required_groups",
            "ignored_groups",
            "max_frame_gap_s",
            "max_sweep_span_s",
            "freshness_budgets_s",
        ),
        "multiplex profile",
    )
    if not isinstance(profile["bus"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", profile["bus"]):
        raise ValueError("Invalid audit bus")
    if not isinstance(profile["dbc_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", profile["dbc_sha256"]
    ):
        raise ValueError("Invalid audit DBC hash")
    frame_id = _identifier(profile["frame_id"])
    if not isinstance(profile["extended"], bool):
        raise TypeError("Audit extended must be boolean")
    if not profile["extended"] and frame_id > 0x7FF:
        raise ValueError("Standard audit identifier out of range")
    message = database.get_message_by_frame_id(frame_id, force_extended_id=profile["extended"])
    if message.is_extended_frame != profile["extended"] or message.is_fd or message.is_container:
        raise ValueError("Audit requires the declared classic CAN frame type")
    validate_multiplexers(message)
    if not isinstance(profile["selector"], str):
        raise TypeError("Audit selector must be a signal name")
    selector = message.get_signal_by_name(profile["selector"])
    if not selector.is_multiplexer or selector.multiplexer_signal is not None:
        raise ValueError("Audit requires a top-level multiplexer")
    required = _groups(profile["required_groups"], "required_groups")
    ignored = _groups(profile["ignored_groups"], "ignored_groups", allow_empty=True)
    if set(required) & set(ignored):
        raise ValueError("Required and ignored groups overlap")
    declared = {
        v
        for s in message.signals
        if s.multiplexer_signal == selector.name
        for v in s.multiplexer_ids
    }
    if not set(required + ignored) <= declared:
        raise ValueError("Profile contains a group not defined by the DBC")
    gap = _positive(profile["max_frame_gap_s"], "max_frame_gap_s")
    span = _positive(profile["max_sweep_span_s"], "max_sweep_span_s")
    if not isinstance(profile["freshness_budgets_s"], list) or not profile["freshness_budgets_s"]:
        raise ValueError("Missing freshness budgets")
    budgets = [_positive(v, "freshness budget") for v in profile["freshness_budgets_s"]]
    if len(set(budgets)) != len(budgets):
        raise ValueError("Duplicate freshness budgets")
    return message, required, set(ignored), gap, span, sorted(budgets)


@exact_timestamps
def audit_stream(source, database, profile):
    from cantools.database.errors import DecodeError

    message, required, ignored, gap_limit, span_limit, budgets = compile_audit(database, profile)
    required_set = set(required)
    successors = dict(zip(required, required[1:] + required[:1], strict=True))
    origin = previous_time = previous_group = previous_required = previous_payload = None
    latest, windows, window = {}, [], None
    counts, group_counts = Counter(), Counter()
    order_examples, repeat_examples, unexpected_examples, gap_examples = [], [], [], []
    freshness = {
        format(b, "f"): {"all_groups_seen": 0, "all_groups_within_age": 0} for b in budgets
    }
    oldest_min = oldest_max = None
    next_window_gap = False

    def finish(reason):
        nonlocal window
        if window is None:
            return
        missing = [g for g in required if g not in window["groups"]]
        observed_span = window["last_time"] - window["first_time"]
        windows.append(
            {
                "window": len(windows) + 1,
                "opened_by_start_group": window["started"],
                "opened_after_gap": window["after_gap"],
                "closing_reason": reason,
                "first_source_line": window["first_line"],
                "last_source_line": window["last_line"],
                "first_time_s": float(window["first_time"] - origin),
                "last_time_s": float(window["last_time"] - origin),
                "observed_span_s": float(observed_span),
                "required_frames": window["frames"],
                "groups_seen": sorted(window["groups"]),
                "missing_groups": missing,
                "duplicate_group_observations": {
                    str(k): v - 1 for k, v in sorted(window["groups"].items()) if v > 1
                },
                "coverage_complete": not missing,
                "coverage_complete_within_span_bound": not missing and observed_span <= span_limit,
                "boundary_authenticated": False,
            }
        )
        window = None

    for frame in read_frames(source):
        if origin is None:
            origin = frame.timestamp
        counts["frames_input"] += 1
        if frame.bus != profile["bus"] or (frame.frame_id, frame.extended) != (
            profile["frame_id"],
            profile["extended"],
        ):
            counts["other_transport_frames"] += 1
            continue
        try:
            decoded = message.decode(
                frame.data, decode_choices=False, allow_truncated=False, allow_excess=False
            )
        except (ValueError, DecodeError) as exc:
            raise ValueError(f"Multiplex decode failed at source line {frame.line}: {exc}") from exc
        group = decoded[profile["selector"]]
        if isinstance(group, bool) or not isinstance(group, int):
            raise TypeError(f"Non-integer selector at source line {frame.line}")
        counts["selected_message_frames"] += 1
        group_counts[group] += 1
        if previous_time is not None:
            dt = frame.timestamp - previous_time
            if dt == 0:
                counts["duplicate_selected_timestamps"] += 1
            if group == previous_group:
                counts["adjacent_group_repeats"] += 1
                if frame.data == previous_payload:
                    counts["adjacent_identical_payload_repeats"] += 1
                if len(repeat_examples) < 10:
                    repeat_examples.append(
                        {
                            "source_line": frame.line,
                            "group": group,
                            "interval_s": float(dt),
                            "identical_payload": frame.data == previous_payload,
                        }
                    )
            if dt > gap_limit:
                counts["selected_frame_gaps"] += 1
                if len(gap_examples) < 10:
                    gap_examples.append({"source_line": frame.line, "interval_s": float(dt)})
                finish("selected_frame_gap")
                latest.clear()
                previous_required = None
                next_window_gap = True
        previous_time, previous_group, previous_payload = frame.timestamp, group, frame.data
        if group in ignored:
            counts["declared_ignored_group_frames"] += 1
            continue
        if group not in required_set:
            counts["unexpected_group_frames"] += 1
            if len(unexpected_examples) < 10:
                unexpected_examples.append({"source_line": frame.line, "group": group})
            continue
        counts["required_group_frames"] += 1
        if previous_required is not None and group != successors[previous_required]:
            counts["declared_order_departures"] += 1
            if len(order_examples) < 10:
                order_examples.append(
                    {
                        "source_line": frame.line,
                        "previous_group": previous_required,
                        "expected_group": successors[previous_required],
                        "observed_group": group,
                    }
                )
        previous_required = group
        if group == required[0]:
            finish("next_start_group")
        if window is None:
            window = {
                "started": group == required[0],
                "after_gap": next_window_gap,
                "first_line": frame.line,
                "last_line": frame.line,
                "first_time": frame.timestamp,
                "last_time": frame.timestamp,
                "frames": 0,
                "groups": Counter(),
            }
            next_window_gap = False
        window["last_line"], window["last_time"] = frame.line, frame.timestamp
        window["frames"] += 1
        window["groups"][group] += 1
        latest[group] = frame.timestamp
        if len(latest) == len(required):
            oldest = frame.timestamp - min(latest.values())
            oldest_min = oldest if oldest_min is None else min(oldest_min, oldest)
            oldest_max = oldest if oldest_max is None else max(oldest_max, oldest)
            for budget in budgets:
                row = freshness[format(budget, "f")]
                row["all_groups_seen"] += 1
                row["all_groups_within_age"] += int(oldest <= budget)
        else:
            counts["required_arrivals_before_all_groups_seen"] += 1
    finish("end_of_recording")
    if not counts["selected_message_frames"] or not counts["required_group_frames"]:
        raise ValueError("No required multiplex group observations")
    complete = [w for w in windows if w["coverage_complete"]]
    return {
        "scope": "research_can_multiplex_timing_observation",
        "diagnostic_claim": False,
        "origin_timestamp_as_recorded": str(origin),
        "profile": profile,
        "counts": dict(counts),
        "observations_by_group": {str(k): n for k, n in sorted(group_counts.items())},
        "windows": windows,
        "complete_coverage_windows": len(complete),
        "complete_windows_within_span_bound": sum(
            w["coverage_complete_within_span_bound"] for w in complete
        ),
        "freshness_at_required_group_arrivals": freshness,
        "oldest_group_age_s_when_all_seen_min_max": [float(oldest_min), float(oldest_max)]
        if oldest_min is not None
        else None,
        "examples": {
            "order_departures": order_examples,
            "repeats": repeat_examples,
            "unexpected_groups": unexpected_examples,
            "gaps": gap_examples,
        },
        "interpretation_limits": [
            "Windows are partitioned on declared start-group appearances, not an authenticated cycle counter.",
            "A repeated start group may be a repetition or a new cycle; missing groups do not identify the cause.",
            "Head/tail fragments and configured gap breaks are reported separately from closed coverage windows.",
            "Freshness describes logged-frame ages only; the timing cache never outputs voltage snapshots.",
            "No canonical CSV, pack sum, interpolation or carried voltage measurements are produced.",
            "Expected order, ignored groups and timing limits are declared review assumptions, not manufacturer requirements.",
        ],
    }


def audit_paths(log, dbc, profile_path, output):
    import cantools

    log, dbc, profile_path, output = map(Path, (log, dbc, profile_path, output))
    if output.exists():
        raise ValueError("Audit output already exists")
    hashes = [sha256(p) for p in (log, dbc, profile_path)]
    profile = load_profile(profile_path)
    if not isinstance(profile, dict) or profile.get("dbc_sha256") != hashes[1]:
        raise ValueError("Audit DBC SHA-256 does not match the profile")
    database = cantools.database.load_file(dbc, strict=True)
    with log.open(encoding="utf-8", newline="") as source:
        result = audit_stream(source, database, profile)
    if hashes != [sha256(p) for p in (log, dbc, profile_path)]:
        raise ValueError("Audit inputs changed during processing")
    result["source_sha256"], result["dbc_sha256"], result["profile_sha256"] = hashes
    with TemporaryDirectory(prefix=".can-audit-", dir=output.parent) as temporary:
        staging = Path(temporary) / "audit.json"
        staging.write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
        )
        publish_new_file(staging, output)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("dbc", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    result = audit_paths(options.log, options.dbc, options.profile, options.output)
    print(
        json.dumps(
            {"counts": result["counts"], "complete_windows": result["complete_coverage_windows"]}
        )
    )


if __name__ == "__main__":
    main()
