# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Review explicitly aligned precharge CSVs with caller-declared context and bands."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from batterylog_research.precharge_capture_review import review_precharge_capture

COLUMNS = (
    "timestamp_s",
    "precharge_active",
    "current_a",
    "pack_voltage_v",
    "dc_link_voltage_v",
)
CONTEXT_FIELDS = {
    "time_basis",
    "alignment_basis",
    "phase_basis",
    "current_path_and_sign",
    "voltage_nodes",
    "validity_policy",
    "acquisition_uncertainty",
    "procedure",
    "reference_justification",
}
REQUIRED = {
    "format",
    "capture_sha256",
    "input_kind",
    "measurement_context",
    "same_reference_for_all_spans",
    "max_gap_s",
    "envelope",
}
OPTIONAL = {"max_spans", "max_examples"}
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
MAX_CAPTURE_BYTES = 64 * 1024 * 1024
MAX_CONTEXT_BYTES = 1024 * 1024
MAX_ROWS = 1_000_000


def _snapshot(path, limit):
    with Path(path).open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{Path(path).name} exceeds the {limit}-byte input bound")
    return raw


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate context key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Nonstandard JSON number: {value}")


def _context(raw, capture_hash):
    try:
        data = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except RecursionError:
        raise ValueError("Context JSON nesting exceeds the parser limit") from None
    if not isinstance(data, dict) or not REQUIRED <= data.keys() <= REQUIRED | OPTIONAL:
        raise ValueError("Require exact precharge context fields")
    if data["format"] != "batterylog-precharge-aligned-v1":
        raise ValueError("Unsupported precharge context format")
    if (
        not isinstance(data["capture_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", data["capture_sha256"]) is None
        or data["capture_sha256"] != capture_hash
    ):
        raise ValueError("Context capture_sha256 does not match the analyzed CSV bytes")
    if data["input_kind"] not in ("authored_fixture", "producer_aligned_capture"):
        raise ValueError("Require an explicit supported input_kind")
    context = data["measurement_context"]
    if (
        not isinstance(context, dict)
        or context.keys() != CONTEXT_FIELDS
        or any(not isinstance(v, str) or not v.strip() for v in context.values())
    ):
        raise ValueError("Require all nonempty measurement-context declarations")
    if data["same_reference_for_all_spans"] is not True:
        raise ValueError("Explicitly justify the same reference for all selected spans")
    return data


def _decimal(token, label):
    token = token.strip()
    if NUMBER.fullmatch(token) is None:
        raise ValueError(f"{label} requires a numeric token or an allowed empty measurement")
    try:
        return Decimal(token)
    except InvalidOperation:
        raise ValueError(f"{label} has an unsupported decimal exponent") from None


def _binary64(value, label):
    result = float(value)
    if not math.isfinite(result) or (value != 0 and result == 0):
        raise ValueError(
            f"{label} cannot be represented as a finite non-underflowed binary64 value"
        )
    return result


def _capture(raw):
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    if tuple(next(reader, ())) != COLUMNS:
        raise ValueError("Require the exact ordered precharge CSV header")
    arrays = [[] for _ in COLUMNS]
    source_lines = []
    previous_time = None
    previous_line = reader.line_num
    for row in reader:
        if len(row) != len(COLUMNS):
            raise ValueError("Every CSV record must have exactly five fields")
        if len(source_lines) >= MAX_ROWS:
            raise ValueError(f"CSV exceeds the {MAX_ROWS}-row input bound")
        timestamp = _decimal(row[0], "timestamp_s")
        if previous_time is not None and timestamp < previous_time:
            raise ValueError("Original CSV timestamps decrease before binary64 conversion")
        previous_time = timestamp
        _binary64(timestamp, "timestamp_s")
        arrays[0].append(timestamp)
        phase = _decimal(row[1], "precharge_active") if row[1].strip() else None
        arrays[1].append(float(phase) if phase in (Decimal(0), Decimal(1)) else math.nan)
        for column in range(2, 5):
            value = row[column]
            arrays[column].append(
                _binary64(_decimal(value, COLUMNS[column]), COLUMNS[column])
                if value.strip()
                else math.nan
            )
        source_lines.append([previous_line + 1, reader.line_num])
        previous_line = reader.line_num
    if not source_lines:
        raise ValueError("Require at least one CSV data record")
    return (
        tuple(
            np.asarray(a, dtype=object if column == 0 else float) for column, a in enumerate(arrays)
        ),
        source_lines,
    )


def review_paths(capture, context, output):
    """Analyze byte snapshots; publish a complete new report without overwriting."""
    capture, context, output = Path(capture), Path(context), Path(output)
    csv_raw = _snapshot(capture, MAX_CAPTURE_BYTES)
    context_raw = _snapshot(context, MAX_CONTEXT_BYTES)
    capture_hash = hashlib.sha256(csv_raw).hexdigest()
    declaration = _context(context_raw, capture_hash)
    arrays, lines = _capture(csv_raw)
    result = review_precharge_capture(
        *arrays,
        declaration["envelope"],
        max_gap_s=declaration["max_gap_s"],
        max_spans=declaration.get("max_spans", 1000),
        max_examples=declaration.get("max_examples", 5),
    )
    for span in result["active_spans"]:
        start = span["source_active_start_index"]
        stop = span["source_active_stop_index_exclusive"]
        # Binary64 display fields remain compatible; decimal fields retain exact time.
        span["active_start_time_s_decimal"] = str(arrays[0][start])
        span["active_end_time_s_decimal"] = str(arrays[0][stop - 1])
        bracket = None
        if span["observed_start_bracket_s"] is not None:
            bracket = [str(arrays[0][start - 1]), str(arrays[0][start])]
        span["observed_start_bracket_s_decimal"] = bracket
        span["source_active_csv_line_range_inclusive"] = [lines[start][0], lines[stop - 1][1]]
        for example in span["examples"]:
            example["source_csv_line_range_inclusive"] = lines[example["sample_index"]]
    directory = Path(__file__).parent
    source_names = (
        "precharge_file_review.py",
        "precharge_capture_review.py",
        "precharge_curve_review.py",
    )
    report = {
        "scope": "aligned_file_observations_only",
        "physical_measurement_acceptance": "caller_declarations_not_authenticated",
        "production_decisions_changed": False,
        "capture": {
            "name": capture.name,
            "sha256": capture_hash,
            "bytes": len(csv_raw),
            "data_records": len(lines),
            "columns": list(COLUMNS),
            "time_arithmetic": "binary64_durations_after_exact_decimal_timestamp_subtraction",
        },
        "context": {
            "name": context.name,
            "sha256": hashlib.sha256(context_raw).hexdigest(),
            "bytes": len(context_raw),
            "declaration": declaration,
        },
        "implementation_sha256": {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in source_names
        },
        "review": result,
    }
    payload = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    with TemporaryDirectory(prefix=".batterylog-precharge-", dir=output.parent) as temporary:
        staged = Path(temporary) / "report.json"
        staged.write_bytes(payload)
        os.link(staged, output)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        review_paths(args.csv, args.context, args.output)
    except (ValueError, OSError, csv.Error) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
