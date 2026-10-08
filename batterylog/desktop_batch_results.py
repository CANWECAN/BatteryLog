"""Read-only desktop rows from a completed JSON summary or a retained batch CSV."""

import csv
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .desktop_job import DesktopBatchOutcome

_STATUSES = {"PASS", "FAIL", "NOT_EVALUATED", "ERROR", "NOT_PROCESSED"}
_COLUMNS = {"source", "status", "violation_events", "error", "report_html"}


@dataclass(frozen=True)
class DesktopBatchRow:
    source: str
    status: str
    violation_events: int | None
    error: str | None
    report: Path | None


def _report_path(directory: Path, value: object) -> Path | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise OSError("Batch report path must be a string or empty.")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or relative.parts[0] != "files"
        or relative.name != "report.html"
    ):
        raise OSError("Batch report path must refer to an HTML report inside this run.")
    # Keep row construction free of per-report filesystem reads for large batches.
    # The launcher resolves symlinks and rechecks containment before opening a report.
    root = directory.absolute()
    report = root.joinpath(*relative.parts)
    if not report.is_relative_to(root):
        raise OSError("Batch report path leaves the output directory.")
    return report


def _row(directory: Path, item: dict[str, object], *, from_csv: bool) -> DesktopBatchRow:
    source, status = item.get("source"), item.get("status")
    if not isinstance(source, str) or not source:
        raise OSError("Batch row must name its source file.")
    if not isinstance(status, str) or status not in _STATUSES:
        raise OSError("Batch row has an invalid outcome.")
    count = item.get("violation_events")
    if from_csv:
        if count == "":
            count = None
        elif isinstance(count, str) and count.isascii() and count.isdecimal():
            try:
                count = int(count)
            except ValueError as exc:
                raise OSError("Batch row has an invalid violation count.") from exc
        else:
            raise OSError("Batch row has an invalid violation count.")
    if count is not None and (type(count) is not int or count < 0):
        raise OSError("Batch row has an invalid violation count.")
    error = item.get("error")
    if error is not None and not isinstance(error, str):
        raise OSError("Batch row diagnostic must be text or empty.")
    report_value = item.get("report_html")
    report = _report_path(directory, report_value)
    if from_csv and isinstance(report_value, str) and report is not None:
        # CSV escaping is ambiguous for names that already start with an apostrophe.
        # A completed report's path identifies the original source without guessing.
        actual_source = report_value[len("files/") : -len("/report.html")]
        escaped = (
            "'" + actual_source
            if actual_source.startswith(("=", "+", "-", "@", "\t", "\r"))
            else actual_source
        )
        if source != escaped:
            raise OSError("Batch CSV source disagrees with its report path.")
        source = actual_source
    elif report is not None and report_value != f"files/{source}/report.html":
        raise OSError("Batch source disagrees with its report path.")
    if status in {"ERROR", "NOT_PROCESSED"}:
        report = None
    return DesktopBatchRow(source, status, count, error or None, report)


def read_batch_rows(outcome: DesktopBatchOutcome) -> list[DesktopBatchRow]:
    """Keep unknown counts unknown and never infer results from leftover HTML files."""
    if outcome.summary is not None:
        return [
            _row(outcome.output_directory, dict(item), from_csv=False)
            for item in outcome.summary["files"]
        ]
    if outcome.summary_csv is None:
        return []
    try:
        with outcome.summary_csv.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames is None or not _COLUMNS.issubset(reader.fieldnames):
                raise OSError("Retained batch summary is missing required columns.")
            if len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise OSError("Retained batch summary has duplicate columns.")
            rows = []
            for item in reader:
                if None in item:
                    raise OSError("Retained batch summary has extra CSV fields.")
                if any(item.get(name) is None for name in _COLUMNS):
                    raise OSError("Retained batch summary has missing CSV fields.")
                rows.append(_row(outcome.output_directory, dict(item), from_csv=True))
            return rows
    except (UnicodeError, csv.Error) as exc:
        raise OSError(f"Cannot read retained batch summary: {exc}") from exc
