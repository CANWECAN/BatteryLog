# SPDX-License-Identifier: Apache-2.0
"""Pinned BMW measurement-contract evidence; raw ticks, no alignment or diagnosis."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

import cantools

from batterylog_research.bmw_clock_provenance_audit import pinned_bytes

DBC_SHA256 = "667a43048f80fc6eb71a212bd90494379347a073d632056705374974eef73626"
FIELDS = {
    0x112: {"Battery_Current": (0, 16), "Battery_Volts": (16, 16), "DC_link": (56, 8)},
    0x1FA: {"ST_DCSW_HVSTO": (12, 2)},
}


def probe(csv_path: Path, dbc_path: Path) -> dict:
    raw, csv_pin = pinned_bytes(csv_path, "csv")
    dbc_raw = dbc_path.read_bytes()
    if len(dbc_raw) != 64000 or hashlib.sha256(dbc_raw).hexdigest() != DBC_SHA256:
        raise ValueError("DBC bytes do not match the pinned source")
    db = cantools.database.load_string(dbc_raw.decode(), database_format="dbc")
    definitions, values, clocks = {}, {}, {frame_id: [] for frame_id in FIELDS}
    for frame_id, names in FIELDS.items():
        message = db.get_message_by_frame_id(frame_id)
        if message.length != 8 or message.is_extended_frame:
            raise ValueError("Unexpected selected frame layout")
        for name, (start, width) in names.items():
            s = message.get_signal_by_name(name)
            if (s.start, s.length, s.byte_order, s.is_signed) != (
                start,
                width,
                "little_endian",
                False,
            ):
                raise ValueError("Unexpected selected signal layout")
            definitions[name] = {
                "frame_id": frame_id,
                "start_bit": start,
                "width_bits": width,
                "scale": str(s.scale),
                "offset": str(s.offset),
                "unit": s.unit,
                "declared_min": str(s.minimum),
                "declared_max": str(s.maximum),
                "comment": s.comment,
                "choices": {str(k): str(v) for k, v in (s.choices or {}).items()},
                "candidate_lsb": str(s.scale),
            }
            values[name] = Counter()
    malformed = selected = compared = negative_current = 0
    first_negative = []
    for line, row in enumerate(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))), 2):
        if not re.fullmatch(r"[0-9a-fA-F]+", row["ID"]):
            malformed += 1
            continue
        frame_id = int(row["ID"], 16)
        if frame_id not in FIELDS:
            continue
        if row["Bus"] != "1" or row["Extended"] != "0" or row["DLC"] != "8":
            raise ValueError("Unexpected selected transport metadata")
        data = bytes(int(row[f"D{i}"], 16) for i in range(1, 9))
        clocks[frame_id].append(int(row["Time Stamp"]))
        decoded = db.decode_message(frame_id, data, decode_choices=False)
        selected += 1
        for name, (start, width) in FIELDS[frame_id].items():
            bits = (int.from_bytes(data, "little") >> start) & ((1 << width) - 1)
            values[name][bits] += 1
            d = definitions[name]
            scaled = Decimal(bits) * Decimal(d["scale"]) + Decimal(d["offset"])
            if abs(float(scaled) - decoded[name]) > 1e-12:
                raise ValueError("Independent byte arithmetic disagrees with DBC decode")
            compared += 1
            if name == "Battery_Current" and scaled < 0:
                negative_current += 1
                if len(first_negative) < 5:
                    first_negative.append({"line": line, "raw": bits, "candidate_a": str(scaled)})
    observations = {}
    for name, counts in values.items():
        d = definitions[name]
        scale, offset = Decimal(d["scale"]), Decimal(d["offset"])
        low, high = Decimal(d["declared_min"]), Decimal(d["declared_max"])
        observations[name] = {
            "count": sum(counts.values()),
            "raw_min": min(counts),
            "raw_max": max(counts),
            "all_ones_count": counts[(1 << d["width_bits"]) - 1],
            "outside_declared_range_count": sum(
                n for bits, n in counts.items() if not low <= Decimal(bits) * scale + offset <= high
            ),
        }
    return {
        "scope": "Candidate encoding and metadata contradictions; physical acceptance blocked",
        "csv_source": csv_pin,
        "dbc_source": {
            "commit": csv_pin["commit"],
            "path": "BMW i3/BMW-i3-PT-CAN2.dbc",
            "bytes": len(dbc_raw),
            "sha256": DBC_SHA256,
        },
        "definitions": definitions,
        "observations": observations,
        "selected_frames": selected,
        "independent_value_comparisons": compared,
        "malformed_ids_not_repaired": malformed,
        "negative_current_samples": negative_current,
        "first_negative_current_examples": first_negative,
        "raw_tick_delta_histograms": {
            hex(k): {
                str(d): n
                for d, n in sorted(Counter(b - a for a, b in itertools.pairwise(t)).items())
            }
            for k, t in clocks.items()
        },
        "state_code_counts": {str(k): n for k, n in sorted(values["ST_DCSW_HVSTO"].items())},
        "tick_unit": None,
        "current_positive_direction": None,
        "measurement_nodes_authenticated": False,
        "raw_analog_validity_authenticated": False,
        "phase_latency_authenticated": False,
        "aligned_rows_created": False,
        "curve_review_eligible": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--dbc", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.csv, args.dbc), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
