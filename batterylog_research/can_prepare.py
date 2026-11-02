# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Research preparation of classic candump+DBC measurements with explicit sample ages."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory

LINE = re.compile(
    r"\(([0-9]{1,18}(?:\.[0-9]{1,9})?)\) ([A-Za-z0-9_.:-]+) "
    r"([0-9A-Fa-f]{3}|[0-9A-Fa-f]{8})#([0-9A-Fa-f]{0,16})\Z"
)
CELL = re.compile(r"cell_([1-9][0-9]*)_v\Z")
TEMP = re.compile(r"temp_([1-9][0-9]*)_c\Z")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class Frame:
    line: int
    timestamp: Decimal
    bus: str
    frame_id: int
    extended: bool
    data: bytes


def read_frames(source):
    previous = None
    for number, line in enumerate(source, 1):
        match = LINE.fullmatch(line.rstrip("\r\n"))
        if match is None or len(match[4]) % 2:
            raise ValueError(f"Invalid classic candump data frame at source line {number}")
        timestamp = Decimal(match[1])
        frame_id = int(match[3], 16)
        extended = len(match[3]) == 8
        if frame_id > (0x1FFFFFFF if extended else 0x7FF):
            raise ValueError(f"CAN identifier out of range at source line {number}")
        if previous is not None and timestamp < previous:
            raise ValueError(f"CAN timestamp decreases at source line {number}")
        previous = timestamp
        yield Frame(number, timestamp, match[2], frame_id, extended, bytes.fromhex(match[4]))


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"Invalid {label} keys; expected {', '.join(expected)}")


def _identifier(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0x1FFFFFFF:
        raise ValueError("frame_id must be an integer CAN identifier")
    return value


def load_profile(path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate CAN profile key: {key!r}")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f"Nonstandard CAN profile number: {value}")

    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=unique_keys,
        parse_constant=reject_constant,
    )


def validate_multiplexers(message):
    # cantools selects a decode branch using its decoded selector value. Require
    # raw identity conversion so scaling cannot silently select another branch.
    for signal in message.signals:
        if signal.is_multiplexer and (
            signal.is_signed or signal.is_float or signal.scale != 1 or signal.offset != 0
        ):
            raise ValueError(
                f"Message {message.name!r} requires a raw unsigned integer multiplexer: "
                f"{signal.name!r}"
            )


def publish_new_file(staging, output):
    # Both paths are on the destination filesystem. Linking the fully written
    # file is atomic and refuses an existing name, including a concurrent writer.
    os.link(staging, output)


def exact_timestamps(function):
    @wraps(function)
    def isolated(*args, **kwargs):
        # The parser admits <=27 significant digits. Isolate arithmetic from
        # caller rounding, exponent limits and traps without changing their context.
        with localcontext(Context(prec=28)):
            return function(*args, **kwargs)

    return isolated


def _raw_exclusions(item, signal):
    if "invalid_raw_values" not in item:
        return frozenset()
    values = item["invalid_raw_values"]
    if not isinstance(values, list) or not values or signal.is_float:
        raise ValueError("invalid_raw_values requires nonempty integer codes on an integer signal")
    minimum = -(2 ** (signal.length - 1)) if signal.is_signed else 0
    maximum = 2 ** (signal.length - int(signal.is_signed)) - 1
    if any(
        isinstance(v, bool) or not isinstance(v, int) or not minimum <= v <= maximum for v in values
    ):
        raise ValueError("invalid_raw_values must use integers within the DBC raw signedness/width")
    if len(set(values)) != len(values):
        raise ValueError("Duplicate invalid_raw_values")
    return frozenset(values)


def compile_profile(database, profile):
    _keys(profile, ("bus", "dbc_sha256", "anchor", "signals"), "profile")
    if not isinstance(profile["bus"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", profile["bus"]):
        raise ValueError("Invalid profile bus")
    if not isinstance(profile["dbc_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", profile["dbc_sha256"]
    ):
        raise ValueError("Invalid profile DBC hash")
    anchor = profile["anchor"]
    _keys(anchor, ("frame_id", "extended", "multiplexer_signal", "multiplexer_value"), "anchor")
    anchor_id = _identifier(anchor["frame_id"])
    if not isinstance(anchor["extended"], bool):
        raise TypeError("Anchor extended must be boolean")
    if not anchor["extended"] and anchor_id > 0x7FF:
        raise ValueError("Standard anchor identifier out of range")
    anchor_message = database.get_message_by_frame_id(
        anchor_id, force_extended_id=anchor["extended"]
    )
    if anchor_message.is_extended_frame != anchor["extended"]:
        raise ValueError("Anchor standard/extended identifier mismatch")
    selector = anchor["multiplexer_signal"]
    mux_value = anchor["multiplexer_value"]
    if selector is None:
        if mux_value is not None or anchor_message.is_multiplexed():
            raise ValueError("Multiplexed anchor requires an explicit selector/value")
    else:
        if (
            not isinstance(selector, str)
            or isinstance(mux_value, bool)
            or not isinstance(mux_value, int)
        ):
            raise ValueError("Invalid anchor multiplexer")
        signal = anchor_message.get_signal_by_name(selector)
        if not signal.is_multiplexer or signal.multiplexer_signal is not None:
            raise ValueError("Anchor selector must be a top-level multiplexer")
        if not 0 <= mux_value < 2**signal.length:
            raise ValueError("Anchor selector value out of range")
    if not isinstance(profile["signals"], list) or not profile["signals"]:
        raise ValueError("Missing profile signals")
    seen_columns, seen_sources, messages, signals = set(), set(), {}, []
    for item in profile["signals"]:
        keys = ("column", "frame_id", "extended", "signal", "max_age_s")
        if isinstance(item, dict) and "invalid_raw_values" in item:
            keys += ("invalid_raw_values",)
        _keys(item, keys, "signal")
        column = item["column"]
        if not isinstance(column, str):
            raise TypeError("Signal column must be a canonical name")
        if CELL.fullmatch(column) or column == "pack_voltage_v":
            units = {"V"}
        elif TEMP.fullmatch(column):
            units = {"C", "degC", "°C"}
        elif column == "pack_current_a":
            units = {"A"}
        else:
            raise ValueError(f"Unsupported canonical measurement column {column!r}")
        frame_id = _identifier(item["frame_id"])
        if not isinstance(item["extended"], bool):
            raise TypeError("Signal extended must be boolean")
        if not item["extended"] and frame_id > 0x7FF:
            raise ValueError("Standard signal identifier out of range")
        message = database.get_message_by_frame_id(frame_id, force_extended_id=item["extended"])
        if message.is_extended_frame != item["extended"] or message.is_fd or message.is_container:
            raise ValueError("Signal message must be the declared classic CAN data-frame type")
        if not isinstance(item["signal"], str):
            raise TypeError("Signal name must be a string")
        signal = message.get_signal_by_name(item["signal"])
        if signal.is_multiplexer or signal.unit not in units:
            raise ValueError(f"Incompatible DBC unit/type for {column!r}: {signal.unit!r}")
        invalid_raw = _raw_exclusions(item, signal)
        age = item["max_age_s"]
        try:
            finite_age = math.isfinite(age)
        except (TypeError, OverflowError):
            finite_age = False
        if isinstance(age, bool) or not isinstance(age, (int, float)) or not finite_age or age < 0:
            raise ValueError("max_age_s must be a finite non-negative number")
        key = (frame_id, item["extended"])
        identity = (*key, item["signal"])
        if column in seen_columns or identity in seen_sources:
            raise ValueError("Duplicate canonical column or DBC signal assignment")
        if CELL.fullmatch(column):
            if key != (anchor_id, anchor["extended"]) or age != 0:
                raise ValueError("Selected brick voltages must come from the same anchor frame")
            if signal.multiplexer_signal is not None and (
                signal.multiplexer_signal != selector or mux_value not in signal.multiplexer_ids
            ):
                raise ValueError("Selected brick is not in the anchor multiplex group")
        seen_columns.add(column)
        seen_sources.add(identity)
        messages[key] = message
        signals.append((column, key, signal, Decimal(str(age)), invalid_raw))
    if not any(CELL.fullmatch(c) for c in seen_columns) or not any(
        TEMP.fullmatch(c) for c in seen_columns
    ):
        raise ValueError("At least one anchor brick and one temperature measurement are required")
    messages[(anchor_id, anchor["extended"])] = anchor_message
    for message in messages.values():
        validate_multiplexers(message)
    return anchor, messages, signals


@exact_timestamps
def prepare_stream(source, database, profile, csv_output, evidence_output):
    from cantools.database.errors import DecodeError

    anchor, messages, signals = compile_profile(database, profile)
    writer = csv.writer(csv_output, lineterminator="\n")
    writer.writerow(["timestamp_s", *(s[0] for s in signals)])
    cache, counts, missing, maximum_ages = {}, Counter(), Counter(), {}
    id_counts, origin, previous = Counter(), None, None
    previous_anchor_time = previous_csv_time = None
    raw_required = {key for _, key, _, _, codes in signals if codes}
    invalid_counts = Counter()
    for frame in read_frames(source):
        if origin is None:
            origin = frame.timestamp
        if frame.timestamp == previous:
            counts["duplicate_adjacent_timestamps"] += 1
        previous = frame.timestamp
        counts["frames_input"] += 1
        id_counts[f"{'extended' if frame.extended else 'standard'}:0x{frame.frame_id:X}"] += 1
        if frame.bus != profile["bus"]:
            counts["other_bus_frames"] += 1
            continue
        key = (frame.frame_id, frame.extended)
        if key not in messages:
            counts["unselected_identifier_frames"] += 1
            continue
        message = messages[key]
        try:
            decoded = message.decode(
                frame.data, decode_choices=False, allow_truncated=False, allow_excess=False
            )
            raw_decoded = (
                message.decode(
                    frame.data,
                    scaling=False,
                    decode_choices=False,
                    allow_truncated=False,
                    allow_excess=False,
                )
                if key in raw_required
                else {}
            )
        except (ValueError, DecodeError) as exc:
            raise ValueError(f"DBC decode failed at source line {frame.line}: {exc}") from exc
        counts["decoded_selected_frames"] += 1
        for column, source_key, signal, _, invalid_raw in signals:
            if source_key != key or signal.name not in decoded:
                continue
            value = decoded[signal.name]
            raw_value = raw_decoded.get(signal.name) if invalid_raw else None
            if invalid_raw and (isinstance(raw_value, bool) or not isinstance(raw_value, int)):
                raise ValueError(f"Invalid raw integer decode at source line {frame.line}")
            if invalid_raw and raw_value in invalid_raw:
                # An invalid newest record replaces the previous valid cache
                # entry; never backfill through a declared raw rejection.
                cache[column] = (frame, None, raw_value)
                invalid_counts[column] += 1
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(
                    f"Non-finite/non-numeric decoded value at source line {frame.line}"
                )
            cache[column] = (frame, value, raw_value)
        if key != (anchor["frame_id"], anchor["extended"]):
            continue
        if (
            anchor["multiplexer_signal"] is not None
            and decoded.get(anchor["multiplexer_signal"]) != anchor["multiplexer_value"]
        ):
            counts["unselected_anchor_multiplex_frames"] += 1
            continue
        counts["anchor_rows"] += 1
        csv_time = float(frame.timestamp - origin)
        if (
            previous_anchor_time is not None
            and frame.timestamp > previous_anchor_time
            and csv_time <= previous_csv_time
        ):
            raise ValueError(f"CAN CSV timestamp precision lost at source line {frame.line}")
        previous_anchor_time, previous_csv_time = frame.timestamp, csv_time
        row, evidence = [csv_time], {}
        for column, _, _, max_age, invalid_raw in signals:
            record = cache.get(column)
            measurement, value, raw_value = record if record else (None, None, None)
            age = frame.timestamp - measurement.timestamp if measurement else None
            usable = age is not None and age <= max_age and value is not None
            if CELL.fullmatch(column):
                usable = usable and measurement.line == frame.line
            row.append(value if usable else "")
            if not usable:
                missing[column] += 1
            else:
                maximum_ages[column] = max(maximum_ages.get(column, 0.0), float(age))
            evidence[column] = {
                "source_line": measurement.line if measurement else None,
                "source_timestamp": str(measurement.timestamp) if measurement else None,
                "age_s": float(age) if age is not None else None,
                "usable": bool(usable),
            }
            if invalid_raw:
                evidence[column]["raw_value"] = raw_value
                evidence[column]["raw_value_rejected"] = raw_value in invalid_raw
        writer.writerow(row)
        evidence_output.write(
            json.dumps(
                {
                    "anchor_data_row": counts["anchor_rows"],
                    "anchor_source_line": frame.line,
                    "anchor_source_timestamp": str(frame.timestamp),
                    "measurements": evidence,
                },
                allow_nan=False,
            )
            + "\n"
        )
    if not counts["frames_input"] or not counts["anchor_rows"]:
        raise ValueError("No matching CAN anchor frames")
    report = {
        "scope": "research_classic_can_explicit_age_preparation",
        "diagnostic_claim": False,
        "origin_timestamp_as_recorded": str(origin),
        "recorded_duration_s": float(previous - origin),
        "counts": dict(counts),
        "frames_by_identifier": dict(sorted(id_counts.items())),
        "missing_or_expired_values_by_column": dict(missing),
        "maximum_accepted_sample_age_s_by_column": maximum_ages,
        "profile": profile,
        "limits": [
            "Bounded previous-sample association is explicit preparation, not simultaneous acquisition.",
            "No look-ahead, interpolation, future samples or expired-value filling.",
            "Brick channels are same-frame voltage groups, not a complete series stack.",
            "Temperature extrema are aggregate BMS channels, not fixed local sensors.",
            "No application checksum, counter, sentinel or hardware calibration is authenticated.",
        ],
    }
    if raw_required:
        report["declared_invalid_raw_values_observed_by_column"] = dict(invalid_counts)
        report["limits"].append(
            "Raw exclusions are declared profile codes, not authenticated manufacturer invalid codes or physical faults."
        )
    return report


def prepare_paths(log_path, dbc_path, profile_path, output_dir):
    import cantools

    paths = [Path(p) for p in (log_path, dbc_path, profile_path)]
    log_path, dbc_path, profile_path = paths
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ValueError("Output directory already exists")
    hashes = [sha256(p) for p in paths]
    profile = load_profile(profile_path)
    if not isinstance(profile, dict) or profile.get("dbc_sha256") != hashes[1]:
        raise ValueError("DBC SHA-256 does not match the declared profile")
    database = cantools.database.load_file(dbc_path, strict=True)
    with TemporaryDirectory(prefix=".can-prepare-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        with (
            log_path.open(encoding="utf-8", newline="") as source,
            (staging / "canonical.csv").open("w", encoding="utf-8", newline="") as csv_output,
            (staging / "alignment.jsonl").open(
                "w", encoding="utf-8", newline="\n"
            ) as evidence_output,
        ):
            report = prepare_stream(source, database, profile, csv_output, evidence_output)
        if hashes != [sha256(p) for p in paths]:
            raise ValueError("CAN source, DBC or profile changed during preparation")
        report["source_sha256"], report["dbc_sha256"], report["profile_sha256"] = hashes
        report["canonical_sha256"] = sha256(staging / "canonical.csv")
        report["alignment_sha256"] = sha256(staging / "alignment.jsonl")
        (staging / "preparation.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
        )
        staging.rename(output_dir)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("dbc", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output_dir", type=Path)
    options = parser.parse_args()
    report = prepare_paths(options.log, options.dbc, options.profile, options.output_dir)
    print(json.dumps(report["counts"]))


if __name__ == "__main__":
    main()
