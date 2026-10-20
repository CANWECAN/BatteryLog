# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Reproduce the first real CAN-to-BatteryLog bridge and independent checks."""

from __future__ import annotations

import argparse
import io
import json
import math
from collections import Counter
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator

from batterylog import DataQualityConfig, ValidationLimits, validate_result_semantics
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.loaders.csv import CsvPathLoader
from batterylog_research.can_prepare import prepare_paths, prepare_stream, read_frames, sha256

LOG_SHA = "709dd42efa4c43cc97cfc5cd05a488641b22949c9db3697c11c4b0cd588c36b4"
DBC_SHA = "d54df533fc82f3dab11ddd0f5ae4d846f22c0a24b111d8cba2b93e79caf60151"
LIMITS = ValidationLimits(cell_min_v=2.5, cell_max_v=4.2, imbalance_max_v=0.1, temperature_max_c=55)
QUALITY = DataQualityConfig("exclude_invalid_rows")


def independent_decoders(log, dbc):
    import can
    import canmatrix.formats
    import cantools

    database = cantools.database.load_file(dbc, strict=True)
    matrix = canmatrix.formats.loadp_flat(str(dbc))
    frames = values = raw_compared = zero_status_frames = 0
    maximum = 0.0
    by_id = Counter()
    multiplex = Counter()
    with log.open() as source, can.CanutilsLogReader(str(log)) as native:
        for ours, other in zip(read_frames(source), native, strict=True):
            if (
                ours.frame_id != other.arbitration_id
                or ours.extended != other.is_extended_id
                or ours.data != bytes(other.data)
                or float(ours.timestamp) != other.timestamp
            ):
                raise AssertionError(f"Raw parser mismatch at source line {ours.line}")
            raw_compared += 1
            if ours.frame_id not in (0x132, 0x332, 0x401):
                continue
            a = database.get_message_by_frame_id(ours.frame_id).decode(
                ours.data, decode_choices=False, allow_truncated=False, allow_excess=False
            )
            b = matrix.frame_by_id(
                canmatrix.ArbitrationId(ours.frame_id, extended=ours.extended)
            ).decode(ours.data)
            if a.keys() != b.keys():
                raise AssertionError("Independent decoder signal identity mismatch")
            for name, value in a.items():
                difference = abs(value - float(b[name].phys_value))
                maximum = max(maximum, difference)
                if not math.isclose(value, float(b[name].phys_value), rel_tol=0, abs_tol=1e-12):
                    raise AssertionError(f"Independent decode mismatch: {name}")
                values += 1
            frames += 1
            by_id[f"0x{ours.frame_id:X}"] += 1
            if ours.frame_id == 0x401:
                multiplex[str(ours.data[0])] += 1
                if ours.data[0] >= 32 and ours.data[1] == 0:
                    zero_status_frames += 1
    return {
        "raw_frames_compared_with_python_can": raw_compared,
        "decoded_frames_compared_with_canmatrix": frames,
        "signal_values_compared": values,
        "absolute_tolerance": 1e-12,
        "relative_tolerance": 0,
        "maximum_absolute_difference": maximum,
        "frames_by_selected_identifier": dict(by_id),
        "brick_multiplex_counts": dict(sorted(multiplex.items(), key=lambda item: int(item[0]))),
        "selectors_ge_32_with_zero_status_frames": zero_status_frames,
    }


def manual_canonical_reference(log):
    """Selected little-endian fields, extracted directly without either DBC decoder."""
    rows, context, temperature, origin = [], None, None, None
    for line in log.read_text().splitlines():
        time, bus, payload = line.split()
        timestamp = Decimal(time[1:-1])
        if origin is None:
            origin = timestamp
        identifier, hex_data = payload.split("#")
        raw = bytes.fromhex(hex_data)
        if bus != "can0":
            continue
        if identifier == "132":
            context = (
                timestamp,
                int.from_bytes(raw[0:2], "little") * 0.01,
                int.from_bytes(raw[2:4], "little", signed=True) * -0.1,
            )
        elif identifier == "332" and raw[0] & 3 == 0:
            temperature = (timestamp, raw[2] * 0.5 - 40, raw[3] * 0.5 - 40)
        elif identifier == "401" and raw[0] == 8:
            cells = [int.from_bytes(raw[i : i + 2], "little") * 0.0001 for i in (2, 4, 6)]
            temps = (
                temperature[1:]
                if temperature and timestamp - temperature[0] <= Decimal("2.1")
                else (float("nan"), float("nan"))
            )
            pack = (
                (context[2], context[1])
                if context and timestamp - context[0] <= Decimal("0.05")
                else (float("nan"), float("nan"))
            )
            rows.append([float(timestamp - origin), *cells, *temps, *pack])
    return np.array(rows)


def validate_analysis(canonical, destination):
    frame = pd.read_csv(canonical)
    full = _analyze_battery_frame(frame, limits=LIMITS, data_quality=QUALITY)
    schema = json.loads(
        (Path(__file__).parents[1] / "batterylog/schema/result-v8.json").read_text()
    )
    validator = Draft202012Validator(schema)
    validator.validate(full)
    validate_result_semantics(full)
    matches, strict_errors = [], []
    for chunk in (1, 7, 65536):
        result = analyze_measurement_loader(
            CsvPathLoader(canonical, chunk_rows=chunk), limits=LIMITS, data_quality=QUALITY
        )
        validator.validate(result)
        validate_result_semantics(result)
        if json.dumps(result, sort_keys=True) != json.dumps(full, sort_keys=True):
            raise AssertionError(f"CAN-prepared result differs at CSV chunk size {chunk}")
        matches.append(chunk)
        try:
            analyze_measurement_loader(CsvPathLoader(canonical, chunk_rows=chunk), limits=LIMITS)
        except ValueError as exc:
            strict_errors.append(str(exc))
        else:
            raise AssertionError("Missing initial temperature was silently filled")
    if len(set(strict_errors)) != 1:
        raise AssertionError("Chunk-dependent strict input rejection")
    if (full["rows_input"], full["rows_analyzed"], full["rows_excluded"]) != (6, 5, 1):
        raise AssertionError("Unexpected real-source row accounting")
    if full["validation_status"] != "FAIL" or full["violations"]:
        raise AssertionError("Unexpected threshold/data-quality accounting")
    (destination / "analysis.json").write_text(json.dumps(full, indent=2, allow_nan=False) + "\n")
    return {
        "chunk_sizes_matching_fullframe_exactly": matches,
        "strict_rejection": strict_errors[0],
        "rows_input": full["rows_input"],
        "rows_analyzed": full["rows_analyzed"],
        "rows_excluded": full["rows_excluded"],
        "validation_status": full["validation_status"],
        "engineering_violation_events": len(full["violations"]),
        "data_quality_events": full["data_quality"]["events"],
        "result_sha256": sha256(destination / "analysis.json"),
        "interpretation": "FAIL is caused by missing source temperature; no configured threshold events.",
    }


def hostile_source_checks(log, dbc, profile, output):
    import cantools

    database = cantools.database.load_file(dbc, strict=True)
    settings = json.loads(profile.read_text())
    lines = log.read_text().splitlines(keepends=True)
    anchor = next(i for i, s in enumerate(lines) if " 401#" in s)
    failures = {}
    for name in ("backwards_time", "truncated_selected_payload"):
        changed = lines.copy()
        if name == "backwards_time":
            position = 65535
            changed[position] = "(1.000000) " + changed[position].split(") ", 1)[1]
        else:
            position = anchor
            changed[position] = changed[position].split("#", 1)[0] + "#08\n"
        try:
            prepare_stream(
                io.StringIO("".join(changed)), database, settings, io.StringIO(), io.StringIO()
            )
        except ValueError as exc:
            failures[name] = {"source_line": position + 1, "error": str(exc)}
        else:
            raise AssertionError(f"Corrupt source accepted: {name}")
    missing = [s for s in lines if not (" 332#" in s and int(s.split("#")[1][:2], 16) & 3 == 0)]
    csv_output = io.StringIO()
    preparation = prepare_stream(
        io.StringIO("".join(missing)), database, settings, csv_output, io.StringIO()
    )
    frame = pd.read_csv(io.StringIO(csv_output.getvalue()))
    result = _analyze_battery_frame(frame, limits=LIMITS, data_quality=QUALITY)
    if (
        result["rows_analyzed"] != 0
        or result["rows_excluded"] != 6
        or result["validation_status"] != "FAIL"
    ):
        raise AssertionError("Absent temperature messages produced a successful analysis")
    failures["temperature_messages_removed"] = {
        "synthetic_mutation": True,
        "removed_frames": len(lines) - len(missing),
        "anchor_rows_retained": preparation["counts"]["anchor_rows"],
        "rows_analyzed": result["rows_analyzed"],
        "rows_excluded": result["rows_excluded"],
        "validation_status": result["validation_status"],
    }
    wrong = output / "wrong.dbc"
    wrong.write_bytes(dbc.read_bytes() + b"\n")
    try:
        prepare_paths(log, wrong, profile, output / "wrong-output")
    except ValueError as exc:
        failures["different_dbc_hash"] = str(exc)
    else:
        raise AssertionError("Undeclared DBC version accepted")
    wrong.unlink()
    return failures


def campaign(log, dbc, profile, output):
    if sha256(log) != LOG_SHA or sha256(dbc) != DBC_SHA:
        raise ValueError("Source bytes are not the pinned first CAN campaign")
    output.mkdir()
    report = prepare_paths(log, dbc, profile, output / "prepared")
    canonical = output / "prepared/canonical.csv"
    reference = manual_canonical_reference(log)
    actual = pd.read_csv(canonical).to_numpy()
    np.testing.assert_allclose(actual, reference, rtol=0, atol=1e-12, equal_nan=True)
    summary = {
        "scope": "research_first_real_can_campaign",
        "source_log": {
            "repository": "dalathegreat/EV-CANlogs",
            "commit": "9cbfc24528d9dfb2923c532f987ce1f3c278908f",
            "path": "Tesla/Model 3/tesla-model3-battery-only.log.log",
            "license": "GPL-3.0",
            "bytes": log.stat().st_size,
            "sha256": LOG_SHA,
            "git_blob_sha1": "30dc20c125a60ce5615b55238eb8fbb9008f4f7a",
        },
        "source_dbc": {
            "repository": "joshwardell/model3dbc",
            "commit": "c56c113c353d09b1a5dd57677461f02fe8b7c6ca",
            "path": "Model3CAN.dbc",
            "license": "MIT",
            "bytes": dbc.stat().st_size,
            "sha256": DBC_SHA,
            "git_blob_sha1": "2e030e798dc32b076794e2f57e36d620e3d4775a",
        },
        "environment": {
            p: version(p) for p in ("cantools", "canmatrix", "python-can", "pandas", "numpy")
        },
        "preparation": report,
        "independent_decoders": independent_decoders(log, dbc),
        "manual_reference": {
            "anchor_rows": len(reference),
            "values_including_missing": int(reference.size),
            "absolute_tolerance": 1e-12,
        },
        "native_analysis": validate_analysis(canonical, output),
        "hostile_checks": hostile_source_checks(log, dbc, profile, output),
        "interpretation": [
            "Publisher-labeled vehicle recording plus community DBC; OEM firmware compatibility is unverified.",
            "Agreement of decoders authenticates neither the DBC's physical meaning nor hardware readings.",
            "Only Brick24/25/26 and BMS-reported temperature extrema are prepared for the engine.",
            "No full-stack sum rule, physical temporal model or current-direction rule is enabled.",
            "Raw source and DBC are not committed; provenance and small derived summaries are retained.",
            "Native Windows, live CAN adapter, CAN FD, ISO-TP, counters/checksums and long capture remain open.",
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {"frames": report["counts"]["frames_input"], "analysis": summary["native_analysis"]}
        )
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("dbc", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    campaign(options.log, options.dbc, options.profile, options.output)


if __name__ == "__main__":
    main()
