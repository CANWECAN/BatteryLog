# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Pinned real multiplex timing and synthetic loss/repetition/order campaign."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

from batterylog_research.can_cloud_validation import DBC_SHA, LOG_SHA
from batterylog_research.can_multiplex_audit import audit_paths
from batterylog_research.can_prepare import sha256


def raw_reference(lines, profile):
    """Direct selector-byte parsing and offline partitions; no DBC/stream auditor."""
    origin = Decimal(lines[0].split()[0][1:-1])
    selected = []
    for number, line in enumerate(lines, 1):
        time, bus, raw = line.split()
        identifier, payload = raw.split("#")
        if bus == "can0" and identifier == "401":
            selected.append((number, Decimal(time[1:-1]), bytes.fromhex(payload)[0], payload))
    required = profile["required_groups"]
    required_set = set(required)
    ignored = set(profile["ignored_groups"])
    gap = Decimal(str(profile["max_frame_gap_s"]))
    span = Decimal(str(profile["max_sweep_span_s"]))
    breaks = (
        [0]
        + [i for i in range(1, len(selected)) if selected[i][1] - selected[i - 1][1] > gap]
        + [len(selected)]
    )
    windows = []
    departures = 0
    budgets = [Decimal(str(v)) for v in profile["freshness_budgets_s"]]
    fresh = {format(v, "f"): {"all_groups_seen": 0, "all_groups_within_age": 0} for v in budgets}
    ages = []
    unavailable = 0
    for block_number, (a, b) in enumerate(pairwise(breaks)):
        observations = [r for r in selected[a:b] if r[2] in required_set]
        starts = [i for i, r in enumerate(observations) if r[2] == required[0]]
        boundaries = sorted({0, *starts, len(observations)})
        for left, right in pairwise(boundaries):
            records = observations[left:right]
            if not records:
                continue
            counts = Counter(r[2] for r in records)
            missing = [g for g in required if g not in counts]
            dt = records[-1][1] - records[0][1]
            closed = (
                "next_start_group"
                if right < len(observations)
                else ("selected_frame_gap" if b < len(selected) else "end_of_recording")
            )
            windows.append(
                {
                    "window": len(windows) + 1,
                    "opened_by_start_group": records[0][2] == required[0],
                    "opened_after_gap": block_number > 0 and left == 0,
                    "closing_reason": closed,
                    "first_source_line": records[0][0],
                    "last_source_line": records[-1][0],
                    "first_time_s": float(records[0][1] - origin),
                    "last_time_s": float(records[-1][1] - origin),
                    "observed_span_s": float(dt),
                    "required_frames": len(records),
                    "groups_seen": sorted(counts),
                    "missing_groups": missing,
                    "duplicate_group_observations": {
                        str(k): n - 1 for k, n in sorted(counts.items()) if n > 1
                    },
                    "coverage_complete": not missing,
                    "coverage_complete_within_span_bound": not missing and dt <= span,
                    "boundary_authenticated": False,
                }
            )
        order = [r[2] for r in observations]
        departures += sum(
            now != required[(required.index(old) + 1) % len(required)]
            for old, now in pairwise(order)
        )
        # Brute-force receipt history per arrival, independent of the streaming cache.
        for index in range(a, b):
            arrival = selected[index]
            if arrival[2] not in required_set:
                continue
            latest = []
            for group in required:
                matching = [r[1] for r in selected[a : index + 1] if r[2] == group]
                if matching:
                    latest.append(matching[-1])
            if len(latest) != len(required):
                unavailable += 1
                continue
            oldest = arrival[1] - min(latest)
            ages.append(oldest)
            for budget in budgets:
                row = fresh[format(budget, "f")]
                row["all_groups_seen"] += 1
                row["all_groups_within_age"] += int(oldest <= budget)
    counts = {
        "frames_input": len(lines),
        "other_transport_frames": len(lines) - len(selected),
        "selected_message_frames": len(selected),
        "required_group_frames": sum(r[2] in required_set for r in selected),
        "declared_ignored_group_frames": sum(r[2] in ignored for r in selected),
        "unexpected_group_frames": sum(r[2] not in required_set | ignored for r in selected),
        "selected_frame_gaps": len(breaks) - 2,
        "required_arrivals_before_all_groups_seen": unavailable,
        "declared_order_departures": departures,
        "duplicate_selected_timestamps": sum(a[1] == b[1] for a, b in pairwise(selected)),
        "adjacent_group_repeats": sum(a[2] == b[2] for a, b in pairwise(selected)),
        "adjacent_identical_payload_repeats": sum(
            a[2] == b[2] and a[3] == b[3] for a, b in pairwise(selected)
        ),
    }
    return {
        "windows": windows,
        "counts": counts,
        "freshness": fresh,
        "age_range": [float(min(ages)), float(max(ages))] if ages else None,
    }


def compare_reference(actual, lines, profile):
    reference = raw_reference(lines, profile)
    if actual["windows"] != reference["windows"]:
        raise AssertionError("Multiplex window/evidence mismatch with offline raw reference")
    for key, value in reference["counts"].items():
        if actual["counts"].get(key, 0) != value:
            raise AssertionError(f"Multiplex sample accounting mismatch: {key}")
    if actual["freshness_at_required_group_arrivals"] != reference["freshness"]:
        raise AssertionError("Multiplex freshness differs from brute-force receipt reference")
    if actual["oldest_group_age_s_when_all_seen_min_max"] != reference["age_range"]:
        raise AssertionError("Multiplex logged-age extrema mismatch")
    return len(reference["windows"])


def campaign(log, dbc, profile_path, destination):
    if sha256(log) != LOG_SHA or sha256(dbc) != DBC_SHA:
        raise ValueError("Unverified multiplex campaign source")
    destination.mkdir()
    lines = log.read_text().splitlines(keepends=True)
    profile = json.loads(profile_path.read_text())
    baseline = audit_paths(log, dbc, profile_path, destination / "baseline.json")
    compared = {"baseline": compare_reference(baseline, lines, profile)}
    selected = [(i, int(s.split("#", 1)[1][:2], 16)) for i, s in enumerate(lines) if " 401#" in s]
    starts = [i for i, (_, group) in enumerate(selected) if group == 0]
    mutations = {}
    for name in (
        "missing_group",
        "duplicate_group",
        "reordered_groups",
        "old_group_history",
        "selected_frame_gap",
        "unexpected_group",
    ):
        changed = lines.copy()
        start = starts[0]
        changed_lines = []
        if name in {"missing_group", "old_group_history"}:
            start = starts[0] if name == "missing_group" else starts[1]
            position = selected[start + 5][0]
            changed_lines = [position + 1]
            del changed[position]
        elif name == "duplicate_group":
            position = selected[start + 4][0]
            changed_lines = [position + 1]
            changed.insert(position + 1, changed[position])
        elif name == "reordered_groups":
            a, b = selected[start + 4][0], selected[start + 5][0]
            head_a, data_a = changed[a].split("#", 1)
            head_b, data_b = changed[b].split("#", 1)
            changed[a], changed[b] = head_a + "#" + data_b, head_b + "#" + data_a
            changed_lines = [a + 1, b + 1]
        elif name == "selected_frame_gap":
            remove = {selected[start + offset][0] for offset in (4, 5, 6, 7)}
            changed_lines = [i + 1 for i in sorted(remove)]
            changed = [s for i, s in enumerate(changed) if i not in remove]
        else:
            position = selected[0][0]
            changed_lines = [position + 1]
            changed.insert(position + 1, changed[position].split("#", 1)[0] + "#2400000000000000\n")
        source = destination / f"{name}.log"
        source.write_text("".join(changed))
        result = audit_paths(source, dbc, profile_path, destination / f"{name}.json")
        compared[name] = compare_reference(result, changed, profile)
        mutations[name] = {
            "synthetic_mutation": True,
            "baseline_source_lines_modified": changed_lines,
            "mutated_source_sha256": result["source_sha256"],
            "counts": result["counts"],
            "complete_coverage_windows": result["complete_coverage_windows"],
            "complete_windows_within_span_bound": result["complete_windows_within_span_bound"],
            "oldest_group_age_s_when_all_seen_min_max": result[
                "oldest_group_age_s_when_all_seen_min_max"
            ],
            "freshness_at_required_group_arrivals": result["freshness_at_required_group_arrivals"],
            "incomplete_windows": [w for w in result["windows"] if not w["coverage_complete"]],
            "examples": result["examples"],
        }
    if mutations["missing_group"]["complete_coverage_windows"] != 3:
        raise AssertionError("Missing group was filled into a complete window")
    if mutations["duplicate_group"]["counts"].get("adjacent_identical_payload_repeats") != 1:
        raise AssertionError("Repeated source frame was not observed")
    if mutations["reordered_groups"]["counts"].get("declared_order_departures") != 3:
        raise AssertionError("Declared-order change was concealed")
    if mutations["old_group_history"]["oldest_group_age_s_when_all_seen_min_max"][1] <= 100:
        raise AssertionError("Old receipt history was not characterized")
    if mutations["selected_frame_gap"]["counts"].get("selected_frame_gaps") != 1:
        raise AssertionError("Selected-message gap was concealed")
    if mutations["unexpected_group"]["counts"].get("unexpected_group_frames") != 1:
        raise AssertionError("Undeclared selector was ignored")
    summary = {
        "scope": "research_model3_multiplex_campaign",
        "diagnostic_claim": False,
        "source_log": {
            "repository": "dalathegreat/EV-CANlogs",
            "commit": "9cbfc24528d9dfb2923c532f987ce1f3c278908f",
            "sha256": LOG_SHA,
        },
        "source_dbc": {
            "repository": "joshwardell/model3dbc",
            "commit": "c56c113c353d09b1a5dd57677461f02fe8b7c6ca",
            "sha256": DBC_SHA,
        },
        "baseline": baseline,
        "mutations": mutations,
        "offline_raw_reference_windows_matched": compared,
        "interpretation": [
            "Required groups 0..31, ignored groups 32..35 and order are declared review assumptions.",
            "Complete coverage is not synchronized measurement, physical topology or a verified complete BMS cycle.",
            "Missing head/tail groups are recording fragments, not established dropped CAN messages.",
            "Age history never fills missing voltage values or creates canonical measurement rows.",
            "All mutation cases are synthetic changes of a copy, never measured physical faults.",
        ],
    }
    (destination / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "complete_baseline_windows": baseline["complete_coverage_windows"],
                "reference_windows": compared,
            }
        )
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("dbc", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    campaign(args.log, args.dbc, args.profile, args.destination)


if __name__ == "__main__":
    main()
