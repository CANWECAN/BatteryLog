# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Reproducible synthetic CAN file stress at an exact freshness boundary."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path

from batterylog_research.can_prepare import prepare_paths, sha256

DBC = """VERSION ""
NS_ :
BS_:
BU_: Test
BO_ 256 Brick: 8 Test
 SG_ Mux M : 0|8@1+ (1,0) [0|1] "" Test
 SG_ V0 m0 : 8|16@1+ (0.001,0) [0|65.535] "V" Test
 SG_ V1 m0 : 24|16@1+ (0.001,0) [0|65.535] "V" Test
 SG_ Other m1 : 8|16@1+ (0.001,0) [0|65.535] "V" Test
BO_ 512 Context: 4 Test
 SG_ T : 0|8@1+ (1,-40) [-40|215] "C" Test
 SG_ I : 8|16@1- (0.1,0) [-3276.8|3276.7] "A" Test
"""


def run(destination, *, cycles=125_000, invalid_every=None):
    if isinstance(cycles, bool) or not isinstance(cycles, int):
        raise TypeError("cycles must be a positive integer")
    if cycles <= 0:
        raise ValueError("cycles must be a positive integer")
    if invalid_every is not None and (
        isinstance(invalid_every, bool) or not isinstance(invalid_every, int) or invalid_every <= 0
    ):
        raise ValueError("invalid_every must be a positive integer when declared")
    destination = Path(destination)
    destination.mkdir()
    log, dbc, profile_path = [destination / p for p in ("stress.log", "stress.dbc", "profile.json")]
    dbc.write_text(DBC, encoding="utf-8", newline="\n")
    profile = {
        "bus": "can0",
        "dbc_sha256": sha256(dbc),
        "anchor": {
            "frame_id": 0x100,
            "extended": False,
            "multiplexer_signal": "Mux",
            "multiplexer_value": 0,
        },
        "signals": [
            {
                "column": column,
                "frame_id": cid,
                "extended": False,
                "signal": signal,
                "max_age_s": age,
            }
            for column, cid, signal, age in (
                ("cell_1_v", 0x100, "V0", 0),
                ("cell_2_v", 0x100, "V1", 0),
                ("temp_1_c", 0x200, "T", 0.05),
                ("pack_current_a", 0x200, "I", 0.05),
            )
        ],
    }
    if invalid_every is not None:
        profile["signals"][2]["invalid_raw_values"] = [255]
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8", newline="\n")
    with log.open("w", encoding="utf-8", newline="") as output:
        for cycle in range(cycles):
            t = 1_674_587_734 + cycle
            temperature = "FF" if invalid_every is not None and cycle % invalid_every == 0 else "3C"
            output.write(
                f"({t}.000000000) can0 200#{temperature}F6FF00\n"
                f"({t}.050000000) can0 100#00AC0D100E000000\n"
                f"({t}.050000001) can0 100#00AC0D100E000000\n"
                f"({t}.100000000) can0 100#01A00F0000000000\n"
            )
    start = time.perf_counter()
    report = prepare_paths(log, dbc, profile_path, destination / "prepared")
    preparation_s = time.perf_counter() - start
    csv_path = destination / "prepared/canonical.csv"
    evidence_path = destination / "prepared/alignment.jsonl"
    checked_rows = 0
    with (
        csv_path.open(encoding="utf-8", newline="") as source,
        evidence_path.open(encoding="utf-8") as proof,
    ):
        rows = csv.DictReader(source)
        for index, (row, line) in enumerate(zip(rows, proof, strict=True)):
            cycle, expired = divmod(index, 2)
            raw_rejected = invalid_every is not None and cycle % invalid_every == 0
            # Reference values come directly from the authored bytes above,
            # with integer source-line formulas; no DBC decoder or cache oracle.
            time_s = cycle + (0.050000001 if expired else 0.05)
            if not math.isclose(float(row["timestamp_s"]), time_s, rel_tol=0, abs_tol=1e-10):
                raise AssertionError(f"Stress timestamp disagreement at row {index + 1}")
            for column, expected in (("cell_1_v", 3.5), ("cell_2_v", 3.6)):
                if not math.isclose(float(row[column]), expected, rel_tol=0, abs_tol=1e-12):
                    raise AssertionError(f"Stress byte value disagreement: {column}")
            expected_context = (
                "" if expired or raw_rejected else "20",
                "" if expired else "-1.0",
            )
            if (row["temp_1_c"], row["pack_current_a"]) != expected_context:
                raise AssertionError(f"Stress freshness disagreement at row {index + 1}")
            evidence = json.loads(line)
            anchor_line = cycle * 4 + 2 + expired
            if evidence["anchor_source_line"] != anchor_line:
                raise AssertionError("Stress anchor source identity disagreement")
            for column in ("cell_1_v", "cell_2_v"):
                entry = evidence["measurements"][column]
                if entry["source_line"] != anchor_line or not entry["usable"]:
                    raise AssertionError("Stress same-frame identity disagreement")
            for column in ("temp_1_c", "pack_current_a"):
                entry = evidence["measurements"][column]
                usable = not expired and not (column == "temp_1_c" and raw_rejected)
                if entry["source_line"] != cycle * 4 + 1 or entry["usable"] != usable:
                    raise AssertionError("Stress context source identity disagreement")
            if invalid_every is not None:
                entry = evidence["measurements"]["temp_1_c"]
                if entry["raw_value"] != (255 if raw_rejected else 60) or (
                    entry["raw_value_rejected"] != raw_rejected
                ):
                    raise AssertionError("Stress declared raw validity disagreement")
            checked_rows += 1
    expected_counts = {
        "frames_input": cycles * 4,
        "decoded_selected_frames": cycles * 4,
        "anchor_rows": cycles * 2,
        "unselected_anchor_multiplex_frames": cycles,
    }
    if checked_rows != cycles * 2 or report["counts"] != expected_counts:
        raise AssertionError("Stress frame accounting disagreement")
    rejected_records = (cycles + invalid_every - 1) // invalid_every if invalid_every else 0
    if report["missing_or_expired_values_by_column"] != {
        "temp_1_c": cycles + rejected_records,
        "pack_current_a": cycles,
    }:
        raise AssertionError("Stress expired-value accounting disagreement")
    if invalid_every is not None and report["declared_invalid_raw_values_observed_by_column"] != {
        "temp_1_c": rejected_records
    }:
        raise AssertionError("Stress declared raw rejection accounting disagreement")
    result = {
        "scope": "synthetic_can_exact_freshness_boundary_file_stress",
        "diagnostic_claim": False,
        "cycles": cycles,
        "frames_input": cycles * 4,
        "canonical_rows_checked_independently": checked_rows,
        "frames_at_exact_age_boundary": cycles,
        "frames_one_nanosecond_past_age_boundary": cycles,
        "declared_invalid_every_cycles": invalid_every,
        "declared_raw_invalid_context_frames": rejected_records,
        "preparation_elapsed_s": preparation_s,
        "elapsed_including_reference_checks_s": time.perf_counter() - start,
        "files": {
            name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for name, path in (
                ("input", log),
                ("canonical", csv_path),
                ("alignment", evidence_path),
            )
        },
        "limits": [
            "Synthetic authored frames, not vehicle measurements or physical fault labels.",
            "Elapsed time characterizes this host and excludes source generation.",
            "No sustained live adapter, driver, capture synchronization or fault accuracy claim.",
        ],
    }
    (destination / "summary.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--cycles", type=int, default=125_000)
    parser.add_argument("--invalid-every", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.destination, cycles=args.cycles, invalid_every=args.invalid_every),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
