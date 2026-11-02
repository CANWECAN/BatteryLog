# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Pinned two-vehicle CSV/DBC compatibility review with independent byte references."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from batterylog_research.can_capture_review import review_paths
from batterylog_research.can_prepare import sha256

SOURCE_COMMIT = "9cbfc24528d9dfb2923c532f987ce1f3c278908f"
SOURCES = {
    "ex30-battery.csv": {
        "path": "Geely SEA platform/Volvo EX30/EX30_battery_only.csv",
        "bytes": 6457305,
        "sha256": "a6d1cd20e186a1c0018fa17b09cb053bc93d9374c52649edc940b8293c4f81d2",
        "git_blob": "dba882cf9069c08b4b4a88dfb78f0fd4aa4f1737",
    },
    "Geely-SEA-platform.dbc": {
        "path": "Geely SEA platform/Geely-SEA-platform.dbc",
        "bytes": 4124,
        "sha256": "e0b5c25bbba12a6b9fe7cab2279b7b07bf52e4a621ba00cc1d5d78ab2dc6f79c",
        "git_blob": "eee935e6d2b40619d42e24e5fb57c2edf881ceb9",
    },
    "bmw-charge.csv": {
        "path": "BMW i3/2017-60AH-REX-PT-CAN2-startcharge.csv",
        "bytes": 5348227,
        "sha256": "d6bd56a3f0f60d7cfffa708a18b287c5802cc42fd5261e01b58d40e7c5c68ebf",
        "git_blob": "3b66c4239cc4537f8ac68c4a5c2a0f63378684c6",
    },
    "BMW-i3-PT-CAN2.dbc": {
        "path": "BMW i3/BMW-i3-PT-CAN2.dbc",
        "bytes": 64000,
        "sha256": "667a43048f80fc6eb71a212bd90494379347a073d632056705374974eef73626",
        "git_blob": "ef3336686ea9021c161d31116646ba36f2f14527",
    },
}


def verify_sources(directory):
    for name, expected in SOURCES.items():
        source = directory / name
        data = source.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if (
            len(data) != expected["bytes"]
            or sha256(source) != expected["sha256"]
            or blob != expected["git_blob"]
        ):
            raise ValueError(f"Pinned source identity mismatch: {name}")


def manual_reference(source, dbc, vehicle):
    """Separate CSV accounting and explicit byte arithmetic, no review parser use.

    References implement the candidate DBC, not authenticated vehicle semantics.
    Untimed EX30 frame type remains unknown. No canonical units are invented.
    """
    import cantools

    database = cantools.database.load_file(dbc, strict=True)
    records = invalid_ids = values = fully_decoded = 0
    selected, selectors = Counter(), Counter()
    maximum_difference = 0.0
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        for row in rows:
            records += 1
            token = row["ID"]
            if re.fullmatch(r"[0123456789abcdefABCDEF]{1,8}", token) is None:
                invalid_ids += 1
                continue
            identifier = int(token, 16)
            if vehicle == "ex30":
                if identifier != 0x142:
                    continue
                data = bytes(int(t, 16) for t in row["Data Bytes"].split())
                group = data[0]
                selectors[group] += 1
                selected[identifier] += 1
                if group > 3:
                    continue  # Missing DBC branch, never derive it from a comment.
                voltage_name = [
                    "pack_voltage",
                    "cell_max_voltage",
                    "cell_min_voltage",
                    "cellvoltages",
                ][group]
                expected = {
                    "mux_142": group,
                    voltage_name: int.from_bytes(data[3:5], "big"),
                }
                if group == 3:
                    expected["cellvoltage_number"] = data[2]
            else:
                if identifier not in {0x112, 0x1FA, 0x426}:
                    continue
                selected[identifier] += 1
                assert row["Extended"] == "0" and row["DLC"] == "8"
                data = bytes(int(row[f"D{i}"], 16) for i in range(1, 9))
                if identifier == 0x112:
                    expected = {
                        "Battery_Current": int.from_bytes(data[:2], "little") * 0.1 - 819.2,
                        "Battery_Volts": int.from_bytes(data[2:4], "little") * 0.1,
                    }
                elif identifier == 0x1FA:
                    expected = dict(
                        zip(
                            [
                                "AVL_TEMP_HVSTO",
                                "AVL_TEMP_HTEX_HVSTO",
                                "AVL_TEMP_HVSTO_MIN",
                                "AVL_TEMP_HVSTO_MAX",
                            ],
                            [b - 50 for b in data[4:8]],
                            strict=True,
                        )
                    )
                else:
                    raise AssertionError(
                        "Pinned capture unexpectedly contains the undecoded cell blob message"
                    )
            decoded = database.get_message_by_frame_id(identifier).decode(
                data, decode_choices=False, allow_truncated=False, allow_excess=False
            )
            for name, reference in expected.items():
                difference = abs(decoded[name] - reference)
                if not math.isclose(decoded[name], reference, rel_tol=0, abs_tol=1e-12):
                    raise AssertionError(f"Independent byte mismatch: record {records}, {name}")
                maximum_difference = max(maximum_difference, difference)
                values += 1
            fully_decoded += 1
    return {
        "records_input": records,
        "invalid_identifier_tokens": invalid_ids,
        "selected_counts": {f"0x{k:X}": v for k, v in sorted(selected.items())},
        "selectors": {str(k): v for k, v in sorted(selectors.items())},
        "fully_decoded_frames": fully_decoded,
        "manual_signal_values_compared": values,
        "maximum_absolute_difference": maximum_difference,
    }


def run(directory, output):
    directory, output = Path(directory), Path(output)
    if output.exists():
        raise ValueError("Campaign directory already exists")
    verify_sources(directory)
    output.mkdir(parents=True)
    campaign = {
        "scope": "second_vehicle_can_compatibility_not_native_battery_analysis",
        "source_repository": "https://github.com/dalathegreat/EV-CANlogs",
        "source_commit": SOURCE_COMMIT,
        "source_license": "GPL-3.0; original captures/DBCs are not copied into Research",
        "sources": SOURCES,
        "limits": [
            "Different vehicles from the same public collection, not independent collector/OEM validation.",
            "Decoder and byte agreement verifies candidate DBC arithmetic only, not source/firmware matching.",
            "Neither recording has a verified complete canonical battery mapping and acquisition timeline.",
        ],
        "vehicles": {},
    }
    for vehicle, log, dbc, layout, ids in [
        ("ex30", "ex30-battery.csv", "Geely-SEA-platform.dbc", "id_payload", [0x142]),
        ("bmw_i3", "bmw-charge.csv", "BMW-i3-PT-CAN2.dbc", "indexed_csv", [0x112, 0x1FA, 0x426]),
    ]:
        report = review_paths(
            directory / log,
            directory / dbc,
            output / f"{vehicle}.json",
            layout=layout,
            selected_ids=ids,
        )
        reference = manual_reference(
            directory / log, directory / dbc, "ex30" if vehicle == "ex30" else "bmw"
        )
        counts = report["counts"]
        assert reference["records_input"] == counts["records_input"]
        assert reference["invalid_identifier_tokens"] == counts["malformed_records"]
        assert sum(reference["selected_counts"].values()) == counts["selected_frames"]
        assert reference["fully_decoded_frames"] == counts["selected_frames_decoded_by_both"]
        if vehicle == "ex30":
            assert reference["selectors"] == report["selectors_observed"]["0x142"]
        for cid, count in reference["selected_counts"].items():
            assert count == report["records_by_identifier"][cid]
        assert not report["analysis_preparation_eligible"]
        campaign["vehicles"][vehicle] = {"review": report, "independent_byte_reference": reference}
    verify_sources(directory)
    campaign["totals"] = {
        "records_input": sum(
            v["review"]["counts"]["records_input"] for v in campaign["vehicles"].values()
        ),
        "dual_decoder_values_compared": sum(
            v["review"]["counts"]["independent_signal_values_compared"]
            for v in campaign["vehicles"].values()
        ),
        "manual_byte_values_compared": sum(
            v["independent_byte_reference"]["manual_signal_values_compared"]
            for v in campaign["vehicles"].values()
        ),
    }
    (output / "summary.json").write_text(json.dumps(campaign, indent=2, allow_nan=False) + "\n")
    return campaign


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_directory", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.source_directory, args.output_directory)["totals"]))


if __name__ == "__main__":
    main()
