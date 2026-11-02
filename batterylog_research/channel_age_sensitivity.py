# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Authored CAN sampling/age experiments; no physical calibration or fault labels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from batterylog_research.can_prepare import prepare_stream, publish_new_file, sha256

DBC = """VERSION ""
NS_ :
BS_:
BU_: Author
BO_ 256 Brick: 2 Author
 SG_ V : 0|16@1+ (0.001,0) [0|65.535] "V" Author
BO_ 512 Context: 2 Author
 SG_ T : 0|16@1+ (0.01,-40) [-40|615.35] "C" Author
"""


def _records(anchor_ms, context_ms, phase_ms, kind, context_first):
    if any(type(value) is not int or not 1 <= value <= 1000 for value in (anchor_ms, context_ms)):
        raise ValueError("Periods must be integer milliseconds in [1, 1000]")
    if type(phase_ms) is not int or not 0 <= phase_ms < context_ms:
        raise ValueError("Phase must be within the context period")
    if kind not in {"ramp", "pulse"} or type(context_first) is not bool:
        raise ValueError("Require an authored ramp/pulse and explicit source order")
    rows = [(t, 1 if context_first else 0, "anchor", 3500) for t in range(0, 1001, anchor_ms)]
    rows += [
        (
            t,
            0 if context_first else 1,
            "context",
            6000 + t if kind == "ramp" else 12000 if 430 <= t < 470 else 6000,
        )
        for t in range(phase_ms, 1001, context_ms)
    ]
    return sorted(rows)


def _core(frame):
    from batterylog import DataQualityConfig, FailureModelConfig, TemperatureRiseConfig
    from batterylog.analysis.core import _analyze_battery_frame

    result = _analyze_battery_frame(
        frame,
        data_quality=DataQualityConfig("exclude_invalid_rows"),
        failure_models=FailureModelConfig(
            0.25, temperature_rise=TemperatureRiseConfig(1200, 0.001)
        ),
    )
    rate = next(
        e for e in result["failure_models"]["evaluations"] if e["code"] == "TEMPERATURE_RISE_HIGH"
    )
    return {
        "rows_input": result["rows_input"],
        "rows_analyzed": result["rows_analyzed"],
        "rows_excluded": result["rows_excluded"],
        "rate_status": rate["status"],
        "rate_evaluated_samples": rate["evaluated_samples"],
        "rate_event_count": len(rate["events"]),
        "maximum_violating_rise_c_per_min": max(
            (e["measured_value"] for e in rate["events"]), default=None
        ),
    }


def prepare_case(
    *,
    anchor_ms=10,
    context_ms=100,
    phase_ms=0,
    max_age_s=0.1,
    kind="ramp",
    context_first=True,
    analyze=False,
):
    import cantools

    records = _records(anchor_ms, context_ms, phase_ms, kind, context_first)
    lines = []
    for tick, _, channel, raw in records:
        timestamp = f"{1674587734 + tick // 1000}.{(tick % 1000) * 1000000:09d}"
        identifier = "100" if channel == "anchor" else "200"
        lines.append(f"({timestamp}) can0 {identifier}#{raw.to_bytes(2, 'little').hex()}\n")
    text = "".join(lines)
    profile = {
        "bus": "can0",
        "dbc_sha256": hashlib.sha256(DBC.encode()).hexdigest(),
        "anchor": {
            "frame_id": 256,
            "extended": False,
            "multiplexer_signal": None,
            "multiplexer_value": None,
        },
        "signals": [
            {
                "column": "cell_1_v",
                "frame_id": 256,
                "extended": False,
                "signal": "V",
                "max_age_s": 0,
            },
            {
                "column": "temp_1_c",
                "frame_id": 512,
                "extended": False,
                "signal": "T",
                "max_age_s": max_age_s,
            },
        ],
    }
    output, trace = io.StringIO(), io.StringIO()
    prepare_stream(
        io.StringIO(text),
        cantools.database.load_string(DBC, database_format="dbc", strict=True),
        profile,
        output,
        trace,
    )
    actual = list(csv.DictReader(io.StringIO(output.getvalue())))
    proofs = [json.loads(line) for line in trace.getvalue().splitlines()]
    anchors = [index for index, record in enumerate(records) if record[2] == "anchor"]
    usable_values, sources, observed_ages = [], set(), []
    if len(actual) != len(anchors):
        raise ValueError("Anchor row count mismatch")
    for row, proof, index in zip(actual, proofs, anchors, strict=True):
        # Brute-force earlier-record search, independent of prepare_stream's cache.
        earlier = [i for i in range(index) if records[i][2] == "context"]
        chosen = earlier[-1] if earlier else None
        age = Decimal(records[index][0] - records[chosen][0]) / 1000 if chosen is not None else None
        usable = chosen is not None and age <= Decimal(str(max_age_s))
        expected = records[chosen][3] / 100 - 40 if usable else None
        evidence = proof["measurements"]["temp_1_c"]
        if (
            evidence["source_line"] != (chosen + 1 if chosen is not None else None)
            or evidence["usable"] != usable
            or proof["anchor_source_line"] != index + 1
        ):
            raise ValueError("Source-order/age oracle mismatch")
        if age is not None and not math.isclose(evidence["age_s"], float(age), abs_tol=1e-12):
            raise ValueError("Reported source age mismatch")
        if expected is None:
            if row["temp_1_c"] != "":
                raise ValueError("Missing/expired measurement was filled")
        elif not math.isclose(float(row["temp_1_c"]), expected, rel_tol=0, abs_tol=1e-10):
            raise ValueError("Decoded measurement differs from the authored raw byte oracle")
        else:
            usable_values.append(float(row["temp_1_c"]))
            sources.add(chosen + 1)
            observed_ages.append(float(age))
    result = {
        "anchor_ms": anchor_ms,
        "context_ms": context_ms,
        "phase_ms": phase_ms,
        "max_age_s": max_age_s,
        "kind": kind,
        "context_first": context_first,
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "canonical_sha256": hashlib.sha256(output.getvalue().encode()).hexdigest(),
        "anchor_rows": len(actual),
        "usable_temperature_rows": len(usable_values),
        "missing_or_expired_rows": len(actual) - len(usable_values),
        "unique_used_context_frames": len(sources),
        "reused_context_rows": len(usable_values) - len(sources),
        "maximum_accepted_age_s": max(observed_ages, default=None),
        "maximum_prepared_temperature_c": max(usable_values, default=None),
        "prepared_rows_above_55_c": sum(v > 55 for v in usable_values),
    }
    if analyze:
        import pandas as pd

        result["prepared_core"] = _core(pd.read_csv(io.StringIO(output.getvalue())))
        contexts = [(r[0] / 1000, r[3] / 100 - 40) for r in records if r[2] == "context"]
        result["context_clock_core"] = _core(
            pd.DataFrame(
                {
                    "timestamp_s": [r[0] for r in contexts],
                    "temp_1_c": [r[1] for r in contexts],
                    "cell_1_v": [3.5] * len(contexts),
                }
            )
        )
    return result


def run_campaign():
    cases = [
        prepare_case(
            anchor_ms=anchor,
            context_ms=context,
            phase_ms=phase,
            max_age_s=age,
            kind=kind,
            context_first=order,
        )
        for anchor in (10, 20, 50)
        for context in (20, 50, 100, 200)
        for phase in (0, context // 2)
        for age in (0, 0.005, 0.01, 0.05, 0.1, 0.2)
        for kind in ("ramp", "pulse")
        for order in (True, False)
    ]
    return {
        "scope": "authored_sampling_and_channel_age_sensitivity",
        "physical_calibration": False,
        "production_decisions_changed": False,
        "case_count": len(cases),
        "oracle_mismatches": 0,
        "cases": cases,
        "showcases": {
            "ramp_hold": prepare_case(analyze=True),
            "pulse_missed": prepare_case(kind="pulse", phase_ms=0, analyze=True),
            "pulse_observed": prepare_case(kind="pulse", phase_ms=50, analyze=True),
            "short_age": prepare_case(max_age_s=0.01, analyze=True),
        },
        "implementation_sha256": {
            name: sha256(Path(__file__).parent / name)
            for name in ("channel_age_sensitivity.py", "can_prepare.py")
        },
        "limits": [
            "One-second authored signals and illustrative 1200 C/min/55 C values are not calibration.",
            "Association age does not establish synchronized acquisition or observability between samples.",
            "More prepared rows do not create more independent context measurements.",
            "Core evaluations describe supplied prepared rows; they are not physical fault labels.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run_campaign()
    with TemporaryDirectory(prefix=".age-study-", dir=args.output.parent) as temporary:
        staged = Path(temporary) / "report.json"
        staged.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        publish_new_file(staged, args.output)
    print(json.dumps({"case_count": report["case_count"], "oracle_mismatches": 0}))


if __name__ == "__main__":
    main()
