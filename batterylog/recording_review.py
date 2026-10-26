"""Publish source-linked recording coverage and engineering evidence together."""

import json
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, TypedDict
from urllib.parse import quote

from .analysis.service import AnalysisService
from .batch import BatchFileSummary, _analyze_file, _pending_summary
from .recording_audit import RecordingAuditResult, RecordingCoverage, audit_recordings
from .reporting.evidence import FileEvidence, sha256_file


class ReviewedRecording(TypedDict):
    recording: RecordingCoverage
    engineering: BatchFileSummary | None


class RecordingReview(TypedDict):
    recording_review_schema_version: Literal[1]
    audit: RecordingAuditResult
    engineering_requested: bool
    engineering_status: Literal["PASS", "FAIL", "NOT_EVALUATED", "ERROR"]
    config_sha256: str | None
    recordings: list[ReviewedRecording]
    review_json: str
    report_html: str


def _engineering_status(
    records: list[ReviewedRecording],
) -> Literal["PASS", "FAIL", "NOT_EVALUATED", "ERROR"]:
    statuses = {
        item["engineering"]["status"] if item["engineering"] else "NOT_EVALUATED"
        for item in records
    }
    if statuses & {"ERROR", "NOT_PROCESSED"}:
        return "ERROR"
    if "FAIL" in statuses:
        return "FAIL"
    if not statuses or "NOT_EVALUATED" in statuses:
        return "NOT_EVALUATED"
    return "PASS"


def _cells(values: list[object]) -> str:
    return "".join(f"<td>{escape(str(value))}</td>" for value in values)


def render_recording_review(review: RecordingReview) -> str:
    """Render a self-contained overview; engineering reports remain separate files."""
    audit = review["audit"]
    sections: list[str] = []
    for item in review["recordings"]:
        record = item["recording"]
        engineering = item["engineering"]
        links = "Not evaluated"
        if engineering:
            links = (
                " ".join(
                    f'<a href="{escape(quote(path, safe="/"), quote=True)}">{label}</a>'
                    for path, label in (
                        (engineering["result_json"], "Analysis JSON"),
                        (engineering["report_html"], "Analysis HTML"),
                    )
                    if path
                )
                or "No completed engineering report"
            )
        criteria = (
            "<table><tbody>"
            + "".join(
                "<tr>" + _cells([label, value]) + "</tr>"
                for label, value in (
                    ("Source", record["path"]),
                    ("Source SHA-256", record["source_sha256"] or "Not captured"),
                    ("Recording coverage", record["coverage_status"]),
                    ("File", record["file_status"]),
                    ("Channels", record["channel_status"]),
                    ("Time", record["time_status"]),
                    ("Engineering", engineering["status"] if engineering else "NOT_EVALUATED"),
                    ("Rows", record["rows"]),
                )
            )
            + "</tbody></table>"
        )
        issue_rows = "".join(
            "<tr>"
            + _cells(
                [
                    issue["code"],
                    issue["channel"] or "",
                    issue["first_row"] or "",
                    issue["count"],
                    issue["detail"],
                ]
            )
            + "</tr>"
            for issue in record["issues"]
        )
        issues = (
            "<table><thead><tr><th>Issue</th><th>Channel</th><th>First CSV line</th>"
            "<th>Count</th><th>Details</th></tr></thead><tbody>" + issue_rows + "</tbody></table>"
            if issue_rows
            else "<p>No declared-coverage defects were recorded.</p>"
        )
        evidence = escape(
            json.dumps(
                {
                    "expected_channels": record["expected_channels"],
                    "observed_channels": record["observed_channels"],
                    "missing_channels": record["missing_channels"],
                    "valid_samples": record["valid_samples"],
                    "expected_time": record["expected_time"],
                    "observed_time": record["observed_time"],
                    "inspection_metadata_status": record["inspection_metadata_status"],
                    "inspection_issues": record["inspection_issues"],
                },
                indent=2,
                ensure_ascii=True,
                allow_nan=False,
            )
        )
        error = (
            f"<p>Engineering error: {escape(engineering['error'])}</p>"
            if engineering and engineering["error"]
            else ""
        )
        sections.append(
            f"<section><h2>{escape(record['id'])}</h2>{criteria}<p>{links}</p>{error}"
            f"{issues}<details><summary>Expected and observed evidence</summary><pre>{evidence}"
            "</pre></details></section>"
        )
    global_issues = escape(json.dumps(audit["issues"], indent=2, allow_nan=False))
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>BatteryLog Recording Review</title><style>"
        "body{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:auto;padding:24px;"
        "line-height:1.5;color:#172033;background:#fff}section{margin:28px 0;border-top:1px solid #bbb}"
        "table{border-collapse:collapse;width:100%;display:block;overflow:auto}"
        "th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top;"
        "overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
        ".status{padding:16px;border:2px solid #475569;border-radius:8px}"
        "@media print{details{display:block}body{padding:0}}</style></head><body>"
        '<h1>BatteryLog Recording Review</h1><div class="status">'
        f"<p>Recording coverage: <strong>{escape(audit['coverage_status'])}</strong></p>"
        f"<p>Engineering: <strong>{escape(review['engineering_status'])}</strong></p></div>"
        "<p>Recording completeness and engineering acceptance are independent. "
        "COMPLETE does not establish battery safety or prove that the physical test occurred. "
        "Sensor acquisition freshness remains NOT_EVALUATED.</p>"
        f"<p>Plan SHA-256: <code>{escape(audit['plan_sha256'] or 'Not supplied')}</code></p>"
        f"<p>Engineering config SHA-256: <code>{escape(review['config_sha256'] or 'Not supplied')}</code></p>"
        '<p><a href="review.json">Full recording review JSON</a></p>'
        f"<pre>{global_issues}</pre>" + "".join(sections) + "</body></html>"
    )


def review_recordings(
    input_directory: str | Path,
    output_directory: str | Path,
    *,
    plan: str | Path | None = None,
    service: AnalysisService | None = None,
    config_evidence: FileEvidence | None = None,
) -> RecordingReview:
    """Publish one complete review directory or no directory on failure/cancel.

    Only explicitly planned CSVs are considered. Original engineering result
    schemas and renderers are reused. No engineering service means coverage-only.
    """
    if service is not None and not isinstance(service, AnalysisService):
        raise TypeError("service must be an AnalysisService or None")
    if config_evidence is not None and service is None:
        raise ValueError("config_evidence requires an engineering service")
    root = Path(input_directory).resolve()
    target = Path(output_directory).resolve()
    if target.is_relative_to(root):
        raise ValueError("Review output must be outside the input directory")
    if target.exists():
        raise ValueError("Review output already exists; choose a new directory")
    audit = audit_recordings(root, plan=plan)
    review: RecordingReview = {
        "recording_review_schema_version": 1,
        "audit": audit,
        "engineering_requested": service is not None,
        "engineering_status": "NOT_EVALUATED",
        "config_sha256": config_evidence.sha256 if config_evidence else None,
        "recordings": [],
        "review_json": "review.json",
        "report_html": "review.html",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent, prefix=".batterylog-review-") as temporary:
        completed = Path(temporary) / "completed"
        completed.mkdir()
        for record in audit["recordings"]:
            engineering = None
            if (
                service is not None
                and record["source_sha256"] is not None
                and record["file_status"] != "ERROR"
            ):
                try:
                    engineering = _analyze_file(
                        root / record["path"],
                        completed / "files" / record["path"],
                        service,
                        config_evidence,
                        record["path"],
                    )
                except (ImportError, OSError, TypeError, ValueError) as exc:
                    engineering = _pending_summary(record["path"])
                    engineering["status"] = "ERROR"
                    engineering["error"] = f"{type(exc).__name__}: {exc}"
                if (
                    engineering["source_sha256"] is not None
                    and engineering["source_sha256"] != record["source_sha256"]
                ):
                    raise ValueError(
                        f"Source changed between coverage and engineering analysis: {record['path']}"
                    )
            review["recordings"].append({"recording": record, "engineering": engineering})
        review["engineering_status"] = _engineering_status(review["recordings"])
        (completed / "review.json").write_text(
            json.dumps(review, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (completed / "review.html").write_text(render_recording_review(review), encoding="utf-8")
        if plan is not None and sha256_file(plan) != audit["plan_sha256"]:
            raise ValueError("Recording plan changed during review")
        for record in audit["recordings"]:
            if (
                record["source_sha256"] is not None
                and sha256_file(root / record["path"]) != record["source_sha256"]
            ):
                raise ValueError(f"Recording source changed during review: {record['path']}")
        if target.exists():
            raise ValueError("Review output appeared during processing")
        completed.rename(target)
    return review
