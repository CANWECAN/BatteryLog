# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Pinned CAN precharge source inventory, not aligned curves or physical diagnosis."""

from __future__ import annotations

import argparse
import bisect
import json
import math
from collections import Counter, defaultdict
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from batterylog_research.can_capture_review import CaptureIssue, read_capture
from batterylog_research.can_prepare import publish_new_file, read_frames, sha256
from batterylog_research.can_second_validation import SOURCES, verify_sources

LOG_SHA = "709dd42efa4c43cc97cfc5cd05a488641b22949c9db3697c11c4b0cd588c36b4"
DBC_SHA = "d54df533fc82f3dab11ddd0f5ae4d846f22c0a24b111d8cba2b93e79caf60151"

# Authored, explicit little-endian references for these pinned candidate DBCs.
# frame_id -> signal -> (start, width, signed, scale, offset, role)
FIELDS = {
    "model3": {
        0x132: {
            "BattVoltage132": (0, 16, False, 0.01, 0, "measurement"),
            "SmoothBattCurrent132": (16, 16, True, -0.1, 0, "measurement"),
        },
        0x20A: {
            "HVP_packContNegativeState": (0, 3, False, 1, 0, "reported_state"),
            "HVP_packContPositiveState": (3, 3, False, 1, 0, "reported_state"),
        },
        0x22A: {
            "HVP_pcsControlRequest": (16, 2, False, 1, 0, "command"),
            "HVP_dcLinkVoltageRequest": (0, 16, True, 0.1, 0, "setpoint"),
            "HVP_dcLinkVoltageFiltered": (20, 11, True, 1, 0, "measurement"),
        },
    },
    "bmw": {
        0x112: {
            "Battery_Current": (0, 16, False, 0.1, -819.2, "measurement"),
            "Battery_Volts": (16, 16, False, 0.1, 0, "measurement"),
            "DC_link": (56, 8, False, 4, 0, "measurement"),
        },
        0x1FA: {
            "ST_DCSW_HVSTO": (12, 2, False, 1, 0, "reported_state"),
        },
    },
    "ex30": {},
}


def manual_value(data, spec):
    start, width, signed, scale, offset, _ = spec
    raw = (int.from_bytes(data, "little") >> start) & (2**width - 1)
    if signed and raw >= 2 ** (width - 1):
        raw -= 2**width
    return raw, raw * scale + offset


def audit_stream(source, database, *, vehicle):
    """Retain raw codes/times; neighbours are evidence, never aligned samples."""
    fields = FIELDS[vehicle]
    layout = {"bmw": "indexed_csv", "ex30": "id_payload"}.get(vehicle)
    frames = read_frames(source) if vehicle == "model3" else read_capture(source, layout)
    counts = Counter(
        dict.fromkeys(
            (
                "records_input",
                "malformed_records",
                "valid_transport_records",
                "selected_frames_decoded",
                "independent_values_compared",
                "reported_code_transitions",
                "precharge_label_observations",
            ),
            0,
        )
    )
    by_id, issues, signals, transitions, previous = Counter(), [], {}, [], {}
    phase_examples, measurements = [], defaultdict(list)
    for frame in frames:
        counts["records_input"] += 1
        if isinstance(frame, CaptureIssue):
            counts["malformed_records"] += 1
            if len(issues) < 10:
                issues.append({"source_line": frame.line, "reason": frame.reason})
            continue
        counts["valid_transport_records"] += 1
        by_id[f"0x{frame.frame_id:X}"] += 1
        if frame.frame_id not in fields:
            continue
        if frame.extended is not False:
            raise ValueError(f"Selected frame type mismatch at source line {frame.line}")
        message = database.get_message_by_frame_id(frame.frame_id)
        decoded = message.decode(
            frame.data, decode_choices=False, allow_truncated=False, allow_excess=False
        )
        decoded_raw = message.decode(
            frame.data,
            scaling=False,
            decode_choices=False,
            allow_truncated=False,
            allow_excess=False,
        )
        counts["selected_frames_decoded"] += 1
        clock = str(frame.timestamp) if vehicle == "model3" else frame.clock_ticks
        record = {
            "source_line": frame.line,
            "recorded_clock": clock,
            "frame_id": f"0x{frame.frame_id:X}",
            "bus": frame.bus,
        }
        measured = {}
        for name, spec in fields[frame.frame_id].items():
            signal = message.get_signal_by_name(name)
            start, width, signed, scale, offset, role = spec
            if (
                signal.start,
                signal.length,
                signal.is_signed,
                signal.scale,
                signal.offset,
                signal.byte_order,
            ) != (start, width, signed, scale, offset, "little_endian"):
                raise ValueError(f"Candidate DBC layout differs for {name}")
            raw, value = manual_value(frame.data, spec)
            if raw != decoded_raw[name] or not math.isclose(
                value, decoded[name], rel_tol=0, abs_tol=1e-12
            ):
                raise AssertionError(f"Independent byte reference mismatch: {name}")
            counts["independent_values_compared"] += 1
            key = f"{frame.bus}/0x{frame.frame_id:X}/{name}"
            stats = signals.setdefault(
                key,
                {
                    "role": role,
                    "unit_as_declared": signal.unit,
                    "samples": 0,
                    "min": value,
                    "max": value,
                    "all_ones_bit_patterns": 0,
                    "choices_as_declared": {
                        str(k): str(v) for k, v in (signal.choices or {}).items()
                    },
                    "raw_code_counts": {},
                },
            )
            stats["samples"] += 1
            stats["min"], stats["max"] = min(stats["min"], value), max(stats["max"], value)
            # Count a bit pattern without assigning invalidity or dropping it.
            stats["all_ones_bit_patterns"] += (raw & (2**width - 1)) == 2**width - 1
            if role == "measurement":
                measured[name] = {"raw": raw, "value_as_declared": value}
            if role in {"reported_state", "command"}:
                code = str(raw)
                stats["raw_code_counts"][code] = stats["raw_code_counts"].get(code, 0) + 1
                observation = {
                    **record,
                    "signal": name,
                    "raw_code": raw,
                    "label_as_declared": str((signal.choices or {}).get(raw, "")),
                }
                prior = previous.get(key)
                if prior is not None and prior["raw_code"] != raw:
                    counts["reported_code_transitions"] += 1
                    if len(transitions) < 20:
                        transitions.append({"previous": prior, "current": observation})
                previous[key] = observation
                if "PRECH" in observation["label_as_declared"].upper():
                    counts["precharge_label_observations"] += 1
                    if len(phase_examples) < 10:
                        phase_examples.append(observation)
        if measured:
            measurements[frame.bus].append({**record, "measurements": measured})
    for observation in phase_examples:
        neighbours = measurements[observation["bus"]]
        lines = [r["source_line"] for r in neighbours]
        index = bisect.bisect_left(lines, observation["source_line"])
        observation["preceding_measurement_frame"] = neighbours[index - 1] if index else None
        observation["following_measurement_frame"] = (
            neighbours[index] if index < len(neighbours) else None
        )
    if not counts["records_input"]:
        raise ValueError("Empty source inventory")
    return {
        "vehicle": vehicle,
        "scope": "candidate_dbc_source_inventory_only",
        "curve_review_eligible": False,
        "production_decisions_changed": False,
        "clock_basis": "recorded_candump_decimal"
        if vehicle == "model3"
        else "unverified_integer_ticks"
        if vehicle == "bmw"
        else "absent",
        "counts": dict(counts),
        "frames_by_identifier": dict(sorted(by_id.items())),
        "signals": signals,
        "malformed_examples": issues,
        "reported_code_transition_examples": transitions,
        "precharge_label_examples": phase_examples,
        "neighbours_are_aligned_measurements": False,
    }


def run(directory, output):
    import cantools

    directory, output = Path(directory), Path(output)
    if output.exists():
        raise ValueError("Output already exists")
    verify_sources(directory)
    for name, expected in (("model3.log", LOG_SHA), ("Model3CAN.dbc", DBC_SHA)):
        if sha256(directory / name) != expected:
            raise ValueError(f"Pinned source identity mismatch: {name}")
    identities = {
        name: sha256(directory / name) for name in [*SOURCES, "model3.log", "Model3CAN.dbc"]
    }
    report = {
        "scope": "pinned_precharge_can_source_eligibility_audit",
        "script_sha256": sha256(Path(__file__)),
        "input_sha256": identities,
        "runtime": {"cantools": version("cantools")},
        "physical_validation": False,
        "curve_review_executed": False,
        "sources": [],
    }
    for vehicle, name, dbc in (
        ("model3", "model3.log", "Model3CAN.dbc"),
        ("bmw", "bmw-charge.csv", "BMW-i3-PT-CAN2.dbc"),
        ("ex30", "ex30-battery.csv", "Geely-SEA-platform.dbc"),
    ):
        database = cantools.database.load_file(directory / dbc, strict=True)
        with (directory / name).open(encoding="utf-8-sig", newline="") as source:
            report["sources"].append(audit_stream(source, database, vehicle=vehicle))
    if any(sha256(directory / name) != digest for name, digest in identities.items()):
        raise ValueError("Source changed during inventory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="precharge-source-", dir=output.parent) as temporary:
        staging = Path(temporary) / "result.json"
        staging.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        publish_new_file(staging, output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_directory", type=Path)
    parser.add_argument("new_output_file", type=Path)
    args = parser.parse_args()
    report = run(args.source_directory, args.new_output_file)
    print(
        json.dumps(
            {
                "sources": [
                    {"vehicle": s["vehicle"], "counts": s["counts"]} for s in report["sources"]
                ]
            },
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
