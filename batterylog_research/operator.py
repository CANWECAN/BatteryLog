# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Run supported Research file workflows and publish one complete output directory."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory

from batterylog import AnalysisService
from batterylog.analysis.report_series import DEFAULT_REPORT_SERIES_MAX_POINTS
from batterylog.config import load_validation_config_bytes
from batterylog.reporting import (
    build_report_metadata,
    capture_file_snapshot,
    verify_file_unchanged,
    write_html_report,
    write_json_result,
)
from batterylog.reporting.evidence import capture_file_evidence
from batterylog_research import can_prepare, precharge_file_review, precharge_html

CAN_LIMITS = [
    "Previous-sample association is not simultaneous acquisition; inspect prepared/alignment.jsonl.",
    "Held context samples can distort derivatives and hide short pulses; temporal models are disabled here.",
    "Brick voltage groups are not a complete series stack; pack/cell-sum comparison is unsupported here.",
    "No adapter, measurement calibration, physical fault or production acceptance is authenticated.",
]
PRECHARGE_LIMITS = [
    "Phase, alignment, measurement paths and reference bands are caller declarations, not authenticated.",
    "A completed review is not a physical acceptance or a PASS decision.",
    "Inspect report.html and review.json for gaps, missing coverage and source-linked observations.",
]


def _json(path, value):
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _new_output(output):
    output = Path(output).absolute()
    if os.path.lexists(output):
        raise ValueError("Output path already exists; choose a new directory")
    if not output.parent.is_dir():
        raise ValueError("Output parent must be an existing directory")
    return output


def _sources(paths):
    return {role: capture_file_evidence(path) for role, path in paths.items()}


def _verify_sources(paths, evidence):
    for role, path in paths.items():
        verify_file_unchanged(path, evidence[role])


def _index(staging, workflow, status, limits):
    links = [
        path.relative_to(staging).as_posix()
        for path in sorted(staging.rglob("*"))
        if path.is_file()
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>BatteryLog Research review</title>"
        "<style>body{font:16px system-ui;max-width:70rem;margin:2rem auto;padding:0 1rem}"
        "li{margin:.6rem 0}code{overflow-wrap:anywhere}</style>"
        "<h1>BatteryLog Research review</h1>"
        f"<p>Workflow: {escape(workflow)}. Outcome: <strong>{escape(status)}</strong>.</p>"
        "<h2>Interpretation</h2><ul>"
        + "".join(f"<li>{escape(item)}</li>" for item in limits)
        + "</ul><h2>Outputs</h2><ul>"
        + "".join(
            f'<li><a href="{escape(name, quote=True)}">{escape(name)}</a></li>' for name in links
        )
        + '</ul><p><a href="manifest.json">manifest.json</a> records input hashes, '
        "applied configuration and output hashes.</p></html>"
    )


def _finish(staging, output, paths, evidence, *, workflow, status, exit_code, limits, details):
    _verify_sources(paths, evidence)
    manifest = {
        "format": "batterylog-research-operator-v1",
        "workflow": workflow,
        "status": status,
        "exit_code": exit_code,
        "sources": {role: asdict(item) for role, item in evidence.items()},
        "limits": limits,
        **details,
    }
    # The manifest and index are entry points, not self-authenticating signatures.
    index = _index(staging, workflow, status, limits)
    (staging / "index.html").write_text(index, encoding="utf-8", newline="\n")
    manifest["outputs_sha256"] = {
        path.relative_to(staging).as_posix(): can_prepare.sha256(path)
        for path in sorted(staging.rglob("*"))
        if path.is_file()
    }
    _json(staging / "manifest.json", manifest)
    _verify_sources(paths, evidence)
    _new_output(output)
    staging.rename(output)
    return manifest


def review_can(log, dbc, profile, config, output_dir):
    """Prepare classic CAN and run Core static rules with explicit YAML thresholds."""
    paths = {
        "log": Path(log),
        "dbc": Path(dbc),
        "profile": Path(profile),
        "config": Path(config),
    }
    output = _new_output(output_dir)
    evidence = _sources(paths)
    config_snapshot = capture_file_snapshot(paths["config"])
    if config_snapshot.evidence.sha256 != evidence["config"].sha256:
        raise ValueError("Config changed before analysis")
    effective = load_validation_config_bytes(config_snapshot.data, source_name=paths["config"].name)
    if effective.signals is not None:
        raise ValueError(
            "Prepared CAN uses canonical columns; config signal remapping is unsupported"
        )
    if effective.failure_models is not None:
        raise ValueError(
            "Temporal failure models are unsupported on held CAN rows; use source-clock analysis"
        )
    if effective.limits.pack_voltage_cell_sum_max_delta_v is not None:
        raise ValueError(
            "Pack/cell-sum comparison requires a qualified complete stack, not brick groups"
        )
    with TemporaryDirectory(prefix=".research-operator-", dir=output.parent) as temporary:
        staging = Path(temporary) / "completed"
        staging.mkdir()
        prepared = can_prepare.prepare_paths(
            paths["log"], paths["dbc"], paths["profile"], staging / "prepared"
        )
        for role, key in (
            ("log", "source_sha256"),
            ("dbc", "dbc_sha256"),
            ("profile", "profile_sha256"),
        ):
            if prepared[key] != evidence[role].sha256:
                raise ValueError(f"{role} changed before preparation")
        canonical = staging / "prepared" / "canonical.csv"
        analyzed = AnalysisService(effective).analyze_path(
            canonical, report_max_points=DEFAULT_REPORT_SERIES_MAX_POINTS
        )
        metadata = build_report_metadata(capture_file_evidence(canonical), evidence["config"])
        write_json_result(analyzed.result, staging / "result.json")
        write_html_report(
            analyzed.result,
            staging / "report.html",
            metadata=metadata,
            series=analyzed.report_series,
        )
        status = analyzed.result["validation_status"]
        return _finish(
            staging,
            output,
            paths,
            evidence,
            workflow="can",
            status=status,
            exit_code={"PASS": 0, "FAIL": 1, "NOT_EVALUATED": 3}[status],
            limits=CAN_LIMITS,
            details={
                "effective_config": asdict(effective),
                "core_version": metadata.batterylog_version,
                "implementation_sha256": {
                    "operator.py": can_prepare.sha256(Path(__file__)),
                    "can_prepare.py": can_prepare.sha256(Path(can_prepare.__file__)),
                },
            },
        )


def review_precharge(capture, context, output_dir):
    """Review the existing strict aligned-file contract; no inferred phase or units."""
    paths = {"capture": Path(capture), "context": Path(context)}
    output = _new_output(output_dir)
    evidence = _sources(paths)
    with TemporaryDirectory(prefix=".research-operator-", dir=output.parent) as temporary:
        staging = Path(temporary) / "completed"
        staging.mkdir()
        reviewed = precharge_file_review.review_paths(
            paths["capture"], paths["context"], staging / "review.json"
        )
        for role in paths:
            if reviewed[role]["sha256"] != evidence[role].sha256:
                raise ValueError(f"{role} changed before precharge review")
        capture_raw = precharge_file_review._snapshot(
            paths["capture"], precharge_file_review.MAX_CAPTURE_BYTES
        )
        (staging / "report.html").write_text(
            precharge_html.render_precharge_html(reviewed, capture_raw),
            encoding="utf-8",
            newline="\n",
        )
        return _finish(
            staging,
            output,
            paths,
            evidence,
            workflow="precharge",
            status="OBSERVATIONS_RECORDED",
            exit_code=0,
            limits=PRECHARGE_LIMITS,
            details={
                "implementation_sha256": {
                    "operator.py": can_prepare.sha256(Path(__file__)),
                    **reviewed["implementation_sha256"],
                    "precharge_html.py": can_prepare.sha256(Path(precharge_html.__file__)),
                },
            },
        )


def main(argv=None, *, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    subcommands = parser.add_subparsers(dest="workflow", required=True)
    can = subcommands.add_parser(
        "can", help="Prepare classic CAN, analyze and write Core HTML/JSON"
    )
    for name in ("log", "dbc", "profile", "config"):
        can.add_argument(f"--{name}", type=Path, required=True)
    precharge = subcommands.add_parser("precharge", help="Review explicitly aligned precharge CSV")
    precharge.add_argument("--csv", type=Path, required=True)
    precharge.add_argument("--context", type=Path, required=True)
    for command in (can, precharge):
        command.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.workflow == "can":
            manifest = review_can(args.log, args.dbc, args.profile, args.config, args.output_dir)
        else:
            manifest = review_precharge(args.csv, args.context, args.output_dir)
    except (ImportError, OSError, TypeError, ValueError, csv.Error) as error:
        hint = (
            "; install batterylog[can] for CAN backends"
            if args.workflow == "can" and isinstance(error, ImportError)
            else ""
        )
        print(f"error: {error}{hint}", file=sys.stderr)
        return 4
    print(
        json.dumps(
            {
                "workflow": manifest["workflow"],
                "status": manifest["status"],
                "output_dir": str(args.output_dir),
            }
        )
    )
    return manifest["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
