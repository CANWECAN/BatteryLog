"""Sequential directory analysis using the existing evidence-report workflow."""

import csv
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Literal, TypedDict

from batterylog.analysis.report_series import DEFAULT_REPORT_SERIES_MAX_POINTS
from batterylog.analysis.service import AnalysisService
from batterylog.reporting import (
    FileEvidence,
    build_report_metadata,
    verify_file_unchanged,
    write_html_report,
    write_json_result,
)
from batterylog.reporting.evidence import capture_file_backed_snapshot

BatchStatus = Literal["PASS", "FAIL", "NOT_EVALUATED", "ERROR", "NOT_PROCESSED"]


class BatchFileSummary(TypedDict):
    source: str
    status: BatchStatus
    source_sha256: str | None
    rows_input: int | None
    rows_analyzed: int | None
    rows_excluded: int | None
    violation_events: int | None
    data_quality_events: int | None
    max_cell_voltage_v: float | None
    max_delta_v: float | None
    max_temperature_c: float | None
    result_json: str | None
    report_html: str | None
    error: str | None


class BatchSummary(TypedDict):
    batch_schema_version: Literal[1]
    config_sha256: str | None
    summary_csv: str
    files: list[BatchFileSummary]


def _pending_summary(source: str) -> BatchFileSummary:
    return {
        "source": source,
        "status": "NOT_PROCESSED",
        "source_sha256": None,
        "rows_input": None,
        "rows_analyzed": None,
        "rows_excluded": None,
        "violation_events": None,
        "data_quality_events": None,
        "max_cell_voltage_v": None,
        "max_delta_v": None,
        "max_temperature_c": None,
        "result_json": None,
        "report_html": None,
        "error": None,
    }


def _write_summary(items: list[BatchFileSummary], path: Path) -> None:
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=".summary.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=list(items[0]))
            writer.writeheader()
            for item in items:
                writer.writerow(
                    {
                        key: "'" + value
                        if isinstance(value, str)
                        and value.startswith(("=", "+", "-", "@", "\t", "\r"))
                        else value
                        for key, value in item.items()
                    }
                )
        temporary.replace(path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _analyze_file(
    source: Path,
    destination: Path,
    service: AnalysisService,
    config_evidence: FileEvidence | None,
    relative: str,
) -> BatchFileSummary:
    with capture_file_backed_snapshot(source) as snapshot:
        output = service.analyze_file(
            snapshot.handle,
            source_name=source.name,
            report_max_points=DEFAULT_REPORT_SERIES_MAX_POINTS,
        )
        metadata = build_report_metadata(snapshot.evidence, config_evidence)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=destination.parent, prefix=".batterylog-") as temporary:
            staging = Path(temporary) / "completed"
            staging.mkdir()
            write_json_result(output.result, staging / "result.json")
            write_html_report(
                output.result,
                staging / "report.html",
                metadata=metadata,
                series=output.report_series,
            )
            verify_file_unchanged(source, snapshot.evidence)
            staging.rename(destination)

        result = output.result
        return {
            "source": relative,
            "status": result["validation_status"],
            "source_sha256": snapshot.evidence.sha256,
            "rows_input": result["rows_input"],
            "rows_analyzed": result["rows_analyzed"],
            "rows_excluded": result["rows_excluded"],
            "violation_events": len(result["violations"]),
            "data_quality_events": len(result["data_quality"]["events"]),
            "max_cell_voltage_v": result["max_cell_voltage_v"],
            "max_delta_v": result["max_delta_v"],
            "max_temperature_c": result["max_temperature_c"],
            "result_json": f"{relative}/result.json",
            "report_html": f"{relative}/report.html",
            "error": None,
        }


def analyze_directory(
    input_directory: str | Path,
    output_directory: str | Path,
    *,
    service: AnalysisService,
    recursive: bool = False,
    config_evidence: FileEvidence | None = None,
) -> BatchSummary:
    """Write per-file reports and a small summary; preserve frozen result-v8.

    Output must be a new directory outside the input tree. Files are discovered
    once and processed sequentially with one effective service configuration.
    Expected input/report errors affect only their file. Interruption propagates;
    the CSV lists untouched files as NOT_PROCESSED and retains completed reports.
    Configuration evidence describes the caller's captured YAML, if supplied.
    """
    if not isinstance(service, AnalysisService):
        raise TypeError("service must be an AnalysisService instance")
    source_root = Path(input_directory).resolve()
    target_root = Path(output_directory).resolve()
    if not source_root.is_dir():
        raise ValueError("Batch input must be an existing directory")
    if target_root.is_relative_to(source_root):
        raise ValueError("Batch output must be outside the input directory")
    if target_root.exists():
        raise ValueError("Batch output directory already exists; choose a new directory")

    candidates = source_root.rglob("*") if recursive else source_root.iterdir()
    sources = sorted(
        (
            path
            for path in candidates
            if path.is_file() and path.suffix.lower() in {".csv", ".mf4", ".mdf"}
        ),
        key=lambda path: path.relative_to(source_root).as_posix(),
    )
    if not sources:
        raise ValueError("Batch input contains no CSV, MDF or MF4 files")

    items = [_pending_summary(path.relative_to(source_root).as_posix()) for path in sources]
    target_root.mkdir(parents=True)
    try:
        for index, source in enumerate(sources):
            relative = items[index]["source"]
            try:
                items[index] = _analyze_file(
                    source, target_root / relative, service, config_evidence, relative
                )
            except (ImportError, OSError, TypeError, ValueError) as exc:
                items[index]["status"] = "ERROR"
                items[index]["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        _write_summary(items, target_root / "summary.csv")

    return {
        "batch_schema_version": 1,
        "config_sha256": config_evidence.sha256 if config_evidence is not None else None,
        "summary_csv": "summary.csv",
        "files": items,
    }
