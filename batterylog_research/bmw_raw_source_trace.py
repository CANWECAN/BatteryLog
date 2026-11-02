# Copyright 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Pinned BMW candidate signals with source lines and raw ticks; never aligned data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
from collections import Counter
from decimal import Decimal, localcontext
from pathlib import Path

from batterylog_research.bmw_clock_provenance_audit import (
    CSV_HEADER,
    HEX_ID,
    LOG_HEADER,
    SOURCE_COMMIT,
    pinned_bytes,
)

DBC_SHA256 = "667a43048f80fc6eb71a212bd90494379347a073d632056705374974eef73626"

# This table is specific to the byte-pinned DBC, not an accepted sensor mapping.
SIGNALS = {
    0x112: {
        "Battery_Current": (0, 16, "0.1", "-819.2", "Amps", "0", "819.2"),
        "Battery_Volts": (16, 16, "0.1", "0", "Volts", "0", "819"),
        "DC_link": (56, 8, "4", "0", "Volts", "0", "820"),
    },
    0x1FA: {"ST_DCSW_HVSTO": (12, 2, "1", "0", "status", "0", "3")},
}
STATE_LABELS = {0: "OPEN", 1: "PRECHRG", 2: "CLOSED", 3: "SNA"}
BLOCKERS = [
    "clock_units_and_jump_cause",
    "vehicle_hardware_firmware_binding",
    "measurement_nodes_current_path_and_sign",
    "raw_validity_and_stale_policy",
    "phase_meaning_command_feedback_and_latency",
    "sensor_timing_filtering_synchronization_and_age_bounds",
    "independently_justified_comparable_reference",
]


def _reader(raw: bytes, header: str, delimiter: str) -> csv.reader:
    reader = csv.reader(
        io.StringIO(raw.decode("utf-8-sig"), newline=""), delimiter=delimiter, strict=True
    )
    if next(reader, None) != header.split(delimiter):
        raise ValueError("Unexpected pinned representation header")
    return reader


def _trace_records(csv_raw: bytes, log_raw: bytes) -> dict:
    """Retain ordinal source records, including duplicate/backward clock evidence."""
    csv_reader = _reader(csv_raw, CSV_HEADER, ",")
    log_reader = _reader(log_raw, LOG_HEADER, "\t")
    frames, previous_selected = [], {}
    inspected = malformed = duplicate = backward = 0
    previous_tick = None
    previous_lines = (1, 1)
    largest_delta = None
    counts = Counter()
    for index, pair in enumerate(itertools.zip_longest(csv_reader, log_reader)):
        c_values, o_values = pair
        if c_values is None or o_values is None:
            raise ValueError("Different source record counts")
        if len(c_values) != 13 or len(o_values) != 11:
            raise ValueError("Unexpected source record width")
        c = dict(zip(CSV_HEADER.split(","), c_values, strict=True))
        o = dict(zip(LOG_HEADER.split("\t"), o_values, strict=True))
        csv_lines = [previous_lines[0] + 1, csv_reader.line_num]
        log_lines = [previous_lines[1] + 1, log_reader.line_num]
        previous_lines = (csv_reader.line_num, log_reader.line_num)
        tick, length = int(o["Time"]), int(o["Len"])
        if not 0 <= length <= 8:
            raise ValueError("Unexpected source DLC")
        payload = bytes.fromhex(o["Data"].strip().removeprefix("0x"))
        csv_payload = bytes(int(c[f"D{i}"], 16) for i in range(1, length + 1))
        if (int(c["Time Stamp"]), int(c["DLC"]), csv_payload) != (tick, length, payload):
            raise ValueError("Ordinal timestamp/DLC/payload mismatch")
        if len(payload) != length or not HEX_ID.fullmatch(o["CAN ID"].removeprefix("0x")):
            raise ValueError("Unexpected original ID or payload length")
        frame_id = int(o["CAN ID"], 16)
        csv_id_parseable = HEX_ID.fullmatch(c["ID"]) is not None
        if csv_id_parseable and int(c["ID"], 16) != frame_id:
            raise ValueError("Ordinal CAN ID mismatch")
        malformed += not csv_id_parseable
        inspected += 1
        if previous_tick is not None:
            delta = tick - previous_tick
            duplicate += delta == 0
            backward += delta < 0
            if largest_delta is None or delta > largest_delta["delta_ticks"]:
                largest_delta = {
                    "previous_source_record_index": index - 1,
                    "source_record_index": index,
                    "previous_ticks": previous_tick,
                    "ticks": tick,
                    "delta_ticks": delta,
                }
        previous_tick = tick
        if frame_id not in SIGNALS:
            continue
        if (o["Ch"], c["Bus"], c["Extended"], length) != ("0", "1", "0", 8):
            raise ValueError("Unexpected selected transport metadata")
        word = int.from_bytes(payload, "little")
        candidates = {}
        for name, (start, width, scale, offset, unit, low, high) in SIGNALS[frame_id].items():
            code = (word >> start) & ((1 << width) - 1)
            with localcontext() as context:
                context.prec = 32
                value = Decimal(code) * Decimal(scale) + Decimal(offset)
            candidates[name] = {
                "raw_code": code,
                "candidate_value_decimal": str(value),
                "candidate_unit": unit,
                "all_ones_code": code == (1 << width) - 1,
                "outside_dbc_declared_range": not Decimal(low) <= value <= Decimal(high),
                "physical_validity": "unknown",
            }
            if name == "ST_DCSW_HVSTO":
                candidates[name]["candidate_label"] = STATE_LABELS[code]
        frames.append(
            {
                "source_record_index": index,
                "csv_physical_lines": csv_lines,
                "log_physical_lines": log_lines,
                "raw_ticks": tick,
                "delta_from_previous_same_frame_ticks": (
                    None
                    if frame_id not in previous_selected
                    else tick - previous_selected[frame_id]
                ),
                "original_id_token": o["CAN ID"],
                "candidate_frame_id": frame_id,
                "payload_hex": payload.hex(),
                "original_metadata": {
                    key: o[key]
                    for key in (
                        "ParserFlags",
                        "Ch",
                        "Counter",
                        "T/R",
                        "Flags",
                        "Parser Name",
                        "default",
                    )
                },
                "csv_metadata": {key: c[key] for key in ("ID", "Extended", "Bus", "DLC")},
                "csv_id_parseable": csv_id_parseable,
                "acquisition_time_s": None,
                "sensor_age_s": None,
                "candidates": candidates,
            }
        )
        previous_selected[frame_id] = tick
        counts[str(frame_id)] += 1
    return {
        "records_inspected": inspected,
        "malformed_csv_id_tokens_not_repaired": malformed,
        "selected_frame_counts": dict(sorted(counts.items())),
        "clock_observations": {
            "duplicate_adjacent_raw_ticks": duplicate,
            "backward_steps": backward,
            "largest_adjacent_delta": largest_delta,
        },
        "frames": frames,
    }


def build_raw_source_trace(csv_path: Path, log_path: Path, dbc_path: Path) -> dict:
    """Read each bounded input once; no accepted-capture or clock override exists."""
    csv_raw, csv_pin = pinned_bytes(csv_path, "csv")
    log_raw, log_pin = pinned_bytes(log_path, "log")
    with dbc_path.open("rb") as stream:
        dbc_raw = stream.read(64001)
    if len(dbc_raw) != 64000 or hashlib.sha256(dbc_raw).hexdigest() != DBC_SHA256:
        raise ValueError("DBC bytes do not match the pinned source")
    trace = _trace_records(csv_raw, log_raw)
    return {
        "format": "batterylog-bmw-raw-source-trace-v1",
        "scope": "Pinned candidate byte trace; physical preparation blocked",
        "sources": {
            "csv": csv_pin,
            "log": log_pin,
            "dbc": {
                "commit": SOURCE_COMMIT,
                "path": "BMW i3/BMW-i3-PT-CAN2.dbc",
                "bytes": len(dbc_raw),
                "sha256": DBC_SHA256,
            },
        },
        "tick_unit": None,
        "seconds_per_tick": None,
        "aligned_rows_created": False,
        "curve_review_eligible": False,
        "physical_preparation_blockers": BLOCKERS.copy(),
        "candidate_encodings": {
            name: {
                "frame_id": frame_id,
                "start_bit": start,
                "width_bits": width,
                "byte_order": "little_endian",
                "is_signed": False,
                "scale": scale,
                "offset": offset,
                "unit": unit,
                "declared_min": low,
                "declared_max": high,
            }
            for frame_id, fields in SIGNALS.items()
            for name, (start, width, scale, offset, unit, low, high) in fields.items()
        },
        **trace,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--dbc", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_raw_source_trace(args.csv, args.log, args.dbc),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
