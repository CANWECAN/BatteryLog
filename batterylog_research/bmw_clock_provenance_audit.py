# SPDX-License-Identifier: Apache-2.0
"""Read-only provenance audit for one pinned BMW CSV / original-log pair.

This reports raw ticks and representation differences. It cannot authenticate
clock units, interpret opaque logger flags, or prepare an aligned physical curve.
Run with both original files; third-party captures are not bundled here.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import itertools
import json
import re
from pathlib import Path

REPOSITORY = "dalathegreat/EV-CANlogs"
SOURCE_COMMIT = "9cbfc24528d9dfb2923c532f987ce1f3c278908f"
SOURCE_FOLDER = "BMW i3/2017-60AH-REX-PT-CAN2-startcharge"
PINS = {
    "csv": (
        5348227,
        "d6bd56a3f0f60d7cfffa708a18b287c5802cc42fd5261e01b58d40e7c5c68ebf",
        "3b66c4239cc4537f8ac68c4a5c2a0f63378684c6",
    ),
    "log": (
        9909389,
        "e858df31719d6a2dfd914a9f254a6a411e2b79451ec76cd51b5ff673f8c79dda",
        "9e8aaad34a94c2b638405f2bfce5da60c2236a91",
    ),
}
CSV_HEADER = "Time Stamp,ID,Extended,Bus,DLC,D1,D2,D3,D4,D5,D6,D7,D8"
LOG_HEADER = "ParserFlags\tCh\tCounter\tT/R\tTime\tFlags\tCAN ID\tLen\tData\tParser Name\tdefault"
HEX_ID = re.compile(r"[0-9A-Fa-f]+")
STATE_SOURCE_LINES = {1880, 2124, 2486, 2575}


def pinned_bytes(path: Path, kind: str) -> tuple[bytes, dict[str, object]]:
    size, expected_digest, expected_blob = PINS[kind]
    with path.open("rb") as stream:
        raw = stream.read(size + 1)
    digest = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if (len(raw), digest, blob) != (size, expected_digest, expected_blob):
        raise ValueError(f"{kind} input does not match the pinned original bytes")
    return raw, {
        "repository": REPOSITORY,
        "commit": SOURCE_COMMIT,
        "path": f"{SOURCE_FOLDER}.{kind}",
        "bytes": len(raw),
        "sha256": digest,
        "git_blob": blob,
    }


def audit(csv_path: Path, log_path: Path) -> dict[str, object]:
    csv_raw, csv_pin = pinned_bytes(csv_path, "csv")
    log_raw, log_pin = pinned_bytes(log_path, "log")
    csv_reader = csv.DictReader(io.StringIO(csv_raw.decode("utf-8-sig")))
    log_reader = csv.DictReader(io.StringIO(log_raw.decode("utf-8-sig")), delimiter="\t")
    if csv_reader.fieldnames != CSV_HEADER.split(","):
        raise ValueError("Unexpected CSV header")
    if log_reader.fieldnames != LOG_HEADER.split("\t"):
        raise ValueError("Unexpected original-log header")
    counts: collections.Counter[str] = collections.Counter()
    deltas: collections.Counter[int] = collections.Counter()
    channels: collections.Counter[tuple[str, str]] = collections.Counter()
    metadata = {
        key: collections.Counter[str]()
        for key in ("ParserFlags", "T/R", "Flags", "Parser Name", "default")
    }
    csv_extended: collections.Counter[str] = collections.Counter()
    malformed_examples: list[dict[str, object]] = []
    flag_examples: list[dict[str, object]] = []
    state_rows: list[dict[str, object]] = []
    largest_deltas: list[dict[str, int]] = []
    previous: int | None = None
    first: int | None = None
    for line, (c, original) in enumerate(itertools.zip_longest(csv_reader, log_reader), start=2):
        if c is None or original is None:
            raise ValueError("Different record counts; ordinal comparison unavailable")
        counts["records"] += 1
        tick, original_tick = int(c["Time Stamp"]), int(original["Time"])
        length, original_length = int(c["DLC"]), int(original["Len"])
        payload = bytes(int(c[f"D{i}"], 16) for i in range(1, length + 1))
        original_payload = bytes.fromhex(original["Data"].strip().removeprefix("0x"))
        for key, matches in (
            ("timestamp", tick == original_tick),
            ("dlc", length == original_length),
            ("payload", payload == original_payload),
        ):
            counts[f"{key}_matches" if matches else f"{key}_mismatches"] += 1
        if HEX_ID.fullmatch(c["ID"]):
            counts[
                "id_matches" if int(c["ID"], 16) == int(original["CAN ID"], 16) else "id_mismatches"
            ] += 1
        else:
            counts["malformed_csv_id_tokens"] += 1
            if len(malformed_examples) < 5:
                malformed_examples.append(
                    {"line": line, "csv_token": c["ID"], "log_token": original["CAN ID"]}
                )
        channels[(original["Ch"], c["Bus"])] += 1
        csv_extended[c["Extended"]] += 1
        for key, counter in metadata.items():
            counter[original[key]] += 1
        if original["Flags"] and len(flag_examples) < 5:
            flag_examples.append(
                {
                    "line": line,
                    "opaque_log_flags": original["Flags"],
                    "csv_extended": c["Extended"],
                    "original_id": original["CAN ID"],
                    "original_payload": original["Data"],
                }
            )
        if first is None:
            first = tick
        if previous is not None:
            delta = tick - previous
            deltas[delta] += 1
            largest_deltas.append(
                {
                    "previous_line": line - 1,
                    "line": line,
                    "previous_ticks": previous,
                    "ticks": tick,
                    "delta_ticks": delta,
                }
            )
            largest_deltas.sort(key=lambda item: item["delta_ticks"], reverse=True)
            del largest_deltas[5:]
        previous = tick
        if line in STATE_SOURCE_LINES:
            state_rows.append(
                {
                    "line": line,
                    "ticks": tick,
                    "csv_id": c["ID"],
                    "log_id": original["CAN ID"],
                    "payload_hex": original_payload.hex(),
                }
            )
    return {
        "scope": "Pinned representation comparison; no physical clock authentication",
        "clock_unit_authenticated": False,
        "tick_unit": None,
        "seconds_per_tick": None,
        "curve_review_eligible": False,
        "blockers": [
            "Original logger/exporter identity, version and timestamp convention absent",
            "One large raw-tick discontinuity has no authenticated explanation",
            "Physical measurement contract and comparable reference remain separate gates",
        ],
        "sources": {"csv": csv_pin, "log": log_pin},
        "headers": {"csv": CSV_HEADER, "log": LOG_HEADER},
        "comparison_counts": dict(sorted(counts.items())),
        "channel_pairs": [
            {"log_ch": ch, "csv_bus": bus, "records": count}
            for (ch, bus), count in sorted(channels.items())
        ],
        "log_metadata_counts": {
            key: dict(sorted(counter.items())) for key, counter in metadata.items()
        },
        "csv_extended_counts": dict(sorted(csv_extended.items())),
        "malformed_csv_id_examples": malformed_examples,
        "opaque_log_flag_examples": flag_examples,
        "clock": {
            "first_ticks": first,
            "last_ticks": previous,
            "backward_steps": sum(n for delta, n in deltas.items() if delta < 0),
            "equal_adjacent_ticks": deltas[0],
            "positive_steps": sum(n for delta, n in deltas.items() if delta > 0),
            "delta_histogram": {str(k): v for k, v in sorted(deltas.items())},
            "largest_raw_deltas": largest_deltas,
        },
        "previously_reviewed_state_source_rows": state_rows,
        "source_mutated": False,
        "ids_repaired": False,
        "rows_sorted": False,
        "clock_rescaled_or_repaired": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.csv, args.log), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
