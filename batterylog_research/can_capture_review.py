# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Review raw CAN CSV/DBC compatibility; emit diagnostics, never battery measurements."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from batterylog_research.can_prepare import publish_new_file, sha256

HEX = re.compile(r"[0-9A-Fa-f]{1,8}\Z")
BYTE = re.compile(r"[0-9A-Fa-f]{1,2}\Z")
INTEGER = re.compile(r"[0-9]{1,18}\Z")
LAYOUTS = {
    "id_payload": ["ID", "Data Bytes"],
    "indexed_csv": ["Time Stamp", "ID", "Extended", "Bus", "DLC", *(f"D{i}" for i in range(1, 9))],
}


@dataclass(frozen=True)
class CaptureFrame:
    line: int
    frame_id: int
    data: bytes
    extended: bool | None
    bus: int | None
    clock_ticks: int | None


@dataclass(frozen=True)
class CaptureIssue:
    line: int
    reason: str
    detail: str


def _integer(value, label):
    if not INTEGER.fullmatch(value):
        raise ValueError(f"Invalid integer {label}: {value!r}")
    return int(value)


def read_capture(source, layout):
    """Retain every logical record as a frame or explicit issue with source line."""
    if layout not in LAYOUTS:
        raise ValueError("Unsupported capture layout")
    reader = csv.reader(source, strict=True)
    header = next(reader, None)
    if header != LAYOUTS[layout]:
        raise ValueError(f"Capture header does not match declared {layout} layout")
    last_line, previous_clock = reader.line_num, None
    for values in reader:
        line = last_line + 1
        last_line = reader.line_num
        reason = "INVALID_CAPTURE_RECORD"
        try:
            if len(values) != len(header):
                raise ValueError(f"Record width {len(values)} does not match header {len(header)}")
            fields = dict(zip(header, values, strict=True))
            ticks = bus = extended = None
            if layout == "indexed_csv":
                ticks = _integer(fields["Time Stamp"], "clock ticks")
                decreasing = previous_clock is not None and ticks < previous_clock
                previous_clock = ticks  # Invalid ID/payload must not hide source clock order.
                if decreasing:
                    reason = "CAPTURE_CLOCK_DECREASES"
                    raise ValueError("Recorded clock ticks decrease")
                ext = fields["Extended"]
                if ext not in {"0", "1"}:
                    raise ValueError("Extended flag must be 0 or 1")
                extended = ext == "1"
                bus = _integer(fields["Bus"], "bus")
            identifier = fields["ID"]
            if not HEX.fullmatch(identifier):
                raise ValueError(f"Invalid hexadecimal CAN identifier: {identifier!r}")
            frame_id = int(identifier, 16)
            if frame_id > (0x7FF if extended is False else 0x1FFFFFFF):
                raise ValueError("CAN identifier outside declared frame-type range")
            if layout == "id_payload":
                tokens = fields["Data Bytes"].split()
                if len(tokens) > 8 or any(not BYTE.fullmatch(t) for t in tokens):
                    raise ValueError("Invalid classic CAN payload bytes")
            else:
                dlc = _integer(fields["DLC"], "DLC")
                if dlc > 8:
                    raise ValueError("Only classic CAN payloads up to 8 bytes are supported")
                tokens = [fields[f"D{i}"] for i in range(1, dlc + 1)]
                if any(not BYTE.fullmatch(t) for t in tokens):
                    raise ValueError("Missing or invalid byte within declared DLC")
                # This source layout uses zero/empty padding after the actual payload.
                padding = [fields[f"D{i}"] for i in range(dlc + 1, 9)]
                if any(t not in {"", "0", "00"} for t in padding):
                    raise ValueError("Nonzero data outside declared DLC is ambiguous")
            yield CaptureFrame(
                line, frame_id, bytes(int(t, 16) for t in tokens), extended, bus, ticks
            )
        except ValueError as exc:
            yield CaptureIssue(line, reason, str(exc))


def review_stream(source, database, matrix, *, layout, selected_ids):
    import canmatrix
    from cantools.database.errors import DecodeError

    if not selected_ids or len(set(selected_ids)) != len(selected_ids):
        raise ValueError("Select unique DBC message identifiers")
    selected = {cid: database.get_message_by_frame_id(cid) for cid in selected_ids}
    counts = Counter(
        dict.fromkeys(
            (
                "records_input",
                "syntactically_valid_frames",
                "malformed_records",
                "unselected_frames",
                "selected_frames",
                "selected_frame_type_mismatches",
                "strict_dbc_decode_rejections",
                "canmatrix_returned_fields_after_strict_rejection",
                "selected_frames_decoded_by_both",
                "independent_signal_values_compared",
            ),
            0,
        )
    )
    issues, decode_examples, extrema = [], [], {}
    ids, errors_by_reason, mux_counts, all_ones, range_counts = (
        Counter(),
        Counter(),
        {},
        Counter(),
        Counter(),
    )
    clock_min = clock_max = None
    maximum_difference = 0.0
    for item in read_capture(source, layout):
        counts["records_input"] += 1
        if isinstance(item, CaptureIssue):
            counts["malformed_records"] += 1
            errors_by_reason[item.reason] += 1
            if len(issues) < 10:
                issues.append(
                    {"source_line": item.line, "reason": item.reason, "detail": item.detail}
                )
            continue
        counts["syntactically_valid_frames"] += 1
        ids[item.frame_id] += 1
        if item.clock_ticks is not None:
            clock_min = item.clock_ticks if clock_min is None else min(clock_min, item.clock_ticks)
            clock_max = item.clock_ticks if clock_max is None else max(clock_max, item.clock_ticks)
        if item.frame_id not in selected:
            counts["unselected_frames"] += 1
            continue
        message = selected[item.frame_id]
        counts["selected_frames"] += 1
        if item.extended is not None and item.extended != message.is_extended_frame:
            counts["selected_frame_type_mismatches"] += 1
            continue
        frame = matrix.frame_by_id(
            canmatrix.ArbitrationId(item.frame_id, extended=message.is_extended_frame)
        )
        try:
            decoded = message.decode(
                item.data, decode_choices=False, allow_truncated=False, allow_excess=False
            )
            raw = message.decode(
                item.data,
                scaling=False,
                decode_choices=False,
                allow_truncated=False,
                allow_excess=False,
            )
        except (ValueError, DecodeError) as exc:
            counts["strict_dbc_decode_rejections"] += 1
            # Characterize a second decoder's partial result; never accept it as a full decode.
            try:
                partial = frame.decode(item.data)
            except (ValueError, canmatrix.DecodingFrameLength):
                partial = None
            if partial:
                counts["canmatrix_returned_fields_after_strict_rejection"] += 1
            if len(decode_examples) < 10:
                decode_examples.append(
                    {
                        "source_line": item.line,
                        "frame_id": item.frame_id,
                        "strict_error": str(exc),
                        "other_decoder_field_names": sorted(partial)
                        if partial is not None
                        else None,
                    }
                )
            selectors = [s for s in message.signals if s.is_multiplexer]
            if (
                len(item.data) == message.length
                and len(selectors) == 1
                and selectors[0].start == 0
                and selectors[0].length == 8
                and selectors[0].byte_order == "little_endian"
            ):
                mux_counts.setdefault(f"0x{item.frame_id:X}", Counter())[item.data[0]] += 1
            continue
        other = frame.decode(item.data)
        if decoded.keys() != other.keys():
            raise AssertionError(f"Decoder signal-set disagreement at source line {item.line}")
        for name, value in decoded.items():
            precise_reference = other[name].phys_value
            # Large raw integer fields must not lose bits through binary64 comparison.
            if isinstance(value, int) and value != precise_reference:
                raise AssertionError(
                    f"Decoder integer disagreement at source line {item.line}: {name}"
                )
            reference = float(precise_reference)
            if (
                not math.isfinite(value)
                or not math.isfinite(reference)
                or not math.isclose(value, reference, rel_tol=0, abs_tol=1e-12)
            ):
                raise AssertionError(
                    f"Decoder value disagreement at source line {item.line}: {name}"
                )
            maximum_difference = max(maximum_difference, abs(value - reference))
            counts["independent_signal_values_compared"] += 1
            signal = message.get_signal_by_name(name)
            key = f"0x{item.frame_id:X}.{name}"
            e = extrema.setdefault(
                key, {"min": value, "max": value, "unit_as_declared": signal.unit}
            )
            e["min"], e["max"] = min(e["min"], value), max(e["max"], value)
            if signal.is_multiplexer:
                mux_counts.setdefault(f"0x{item.frame_id:X}", Counter())[int(raw[name])] += 1
            if not signal.is_signed and raw[name] == 2**signal.length - 1:
                all_ones[key] += 1
            if (signal.minimum is not None and value < signal.minimum) or (
                signal.maximum is not None and value > signal.maximum
            ):
                range_counts[key] += 1
        counts["selected_frames_decoded_by_both"] += 1
    if not counts["records_input"]:
        raise ValueError("Empty CAN capture")
    observed = set(ids)
    blockers = [
        "No verified canonical cell/temperature mapping or acquisition alignment is declared."
    ]
    if layout == "id_payload":
        blockers += [
            "Source has no timestamps.",
            "Source has no bus or standard/extended frame-type metadata.",
        ]
    else:
        blockers.append(
            "Clock tick unit is not authenticated; no seconds or sample ages are inferred."
        )
    if counts["malformed_records"]:
        blockers.append(
            "Malformed transport records are present; they are counted, not repaired or imported."
        )
    if counts["strict_dbc_decode_rejections"]:
        blockers.append("The selected DBC does not fully decode all selected frames.")
    if counts["selected_frame_type_mismatches"]:
        blockers.append("Selected identifiers include a frame type different from the DBC.")
    if set(selected) - observed:
        blockers.append("Some selected DBC identifiers are absent from this capture.")
    return {
        "scope": "research_can_capture_compatibility_review",
        "diagnostic_claim": False,
        "layout": layout,
        "counts": dict(counts),
        "records_by_identifier": {f"0x{k:X}": n for k, n in sorted(ids.items())},
        "malformed_by_reason": dict(errors_by_reason),
        "malformed_examples": issues,
        "strict_decode_rejection_examples": decode_examples,
        "selected_identifiers_not_observed": [
            f"0x{i:X}" for i in selected_ids if i not in observed
        ],
        "selectors_observed": {
            cid: {str(k): n for k, n in sorted(v.items())} for cid, v in mux_counts.items()
        },
        "decoded_extrema_as_declared": extrema,
        "unsigned_all_ones_raw_observations": dict(all_ones),
        "outside_dbc_declared_range_observations": dict(range_counts),
        "independent_comparison": {
            "absolute_tolerance": 1e-12,
            "relative_tolerance": 0,
            "maximum_absolute_difference": maximum_difference,
        },
        "recorded_clock_tick_range": [clock_min, clock_max] if clock_min is not None else None,
        "analysis_preparation_eligible": False,
        "analysis_blockers": blockers,
        "interpretation_limits": [
            "A frame or partial decoder result is not a complete battery measurement row.",
            "All-ones bit patterns and DBC-range observations are review context, not authenticated invalid codes or faults.",
            "Declared DBC units/ranges may be incomplete or inconsistent; no normalization or clipping is applied.",
            "Malformed records are retained in accounting; only valid records undergo diagnostic decoding.",
            "No canonical CSV, invented timestamps, vehicle transmission or battery health result is produced.",
        ],
    }


def review_paths(log, dbc, output, *, layout, selected_ids):
    import canmatrix.formats
    import cantools

    log, dbc, output = map(Path, (log, dbc, output))
    if output.exists():
        raise ValueError("Capture review output already exists")
    hashes = [sha256(log), sha256(dbc)]
    database = cantools.database.load_file(dbc, strict=True)
    matrix = canmatrix.formats.loadp_flat(str(dbc))
    with log.open(encoding="utf-8-sig", newline="") as source:
        result = review_stream(source, database, matrix, layout=layout, selected_ids=selected_ids)
    if hashes != [sha256(log), sha256(dbc)]:
        raise ValueError("Capture review inputs changed during processing")
    result["source_sha256"], result["dbc_sha256"] = hashes
    with TemporaryDirectory(prefix=".capture-review-", dir=output.parent) as temporary:
        staging = Path(temporary) / "review.json"
        staging.write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
        )
        publish_new_file(staging, output)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("dbc", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--layout", choices=LAYOUTS, required=True)
    parser.add_argument("--frame-id", type=lambda s: int(s, 0), action="append", required=True)
    args = parser.parse_args()
    result = review_paths(
        args.log, args.dbc, args.output, layout=args.layout, selected_ids=args.frame_id
    )
    print(json.dumps(result["counts"]))


if __name__ == "__main__":
    main()
