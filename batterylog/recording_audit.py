"""Audit declared CSV recording coverage independently of engineering results."""

import csv
import io
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, Literal, TypedDict

from .inspection import inspect_measurement
from .loaders.csv import _validate_header
from .reporting.evidence import capture_file_backed_snapshot, verify_file_unchanged

CoverageStatus = Literal["COMPLETE", "INCOMPLETE", "NOT_EVALUATED", "ERROR"]
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_STATUSES: tuple[CoverageStatus, ...] = ("ERROR", "INCOMPLETE", "NOT_EVALUATED", "COMPLETE")


class CoverageIssue(TypedDict):
    code: str
    detail: str
    count: int
    first_row: int | None
    channel: str | None


class RecordingCoverage(TypedDict):
    id: str
    path: str
    coverage_status: CoverageStatus
    file_status: CoverageStatus
    channel_status: CoverageStatus
    time_status: CoverageStatus
    source_sha256: str | None
    source_size_bytes: int | None
    rows: int
    expected_channels: list[str] | None
    observed_channels: list[str]
    missing_channels: list[str]
    valid_samples: dict[str, int]
    expected_time: dict[str, str] | None
    observed_time: dict[str, str | int | None]
    inspection_metadata_status: str | None
    inspection_issues: list[str]
    issues: list[CoverageIssue]


class RecordingAuditResult(TypedDict):
    recording_audit_schema_version: Literal[1]
    scope: Literal["declared_csv_recording_coverage"]
    coverage_status: CoverageStatus
    engineering_analysis_performed: Literal[False]
    sensor_acquisition_freshness: Literal["NOT_EVALUATED"]
    plan_sha256: str | None
    recordings: list[RecordingCoverage]
    issues: list[CoverageIssue]


@dataclass(frozen=True)
class _Window:
    column: str
    start: Fraction
    end: Fraction
    gap: Fraction
    tolerance: Fraction


@dataclass(frozen=True)
class _Recording:
    id: str
    path: str
    channels: tuple[str, ...] | None
    window: _Window | None


def _issue(
    issues: list[CoverageIssue],
    code: str,
    detail: str,
    *,
    row: int | None = None,
    channel: str | None = None,
) -> None:
    for issue in issues:
        if issue["code"] == code and issue["channel"] == channel:
            issue["count"] += 1
            return
    issues.append(
        {"code": code, "detail": detail, "count": 1, "first_row": row, "channel": channel}
    )


def _status(statuses: list[CoverageStatus]) -> CoverageStatus:
    return next(status for status in _STATUSES if status in statuses)


def _exact_seconds(value: object, field: str) -> Fraction:
    if not isinstance(value, str) or len(value) > 256 or not _DECIMAL.fullmatch(value):
        raise ValueError(f"{field} must be a finite decimal string (at most 256 characters)")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} is not a supported decimal") from exc
    if abs(number.adjusted()) > 128 or abs(int(number.as_tuple().exponent)) > 128:
        raise ValueError(f"{field} exceeds the supported decimal exponent range [-128, 128]")
    return Fraction(number)


def _decimal_text(value: Fraction) -> str:
    # Decimal source values have only factors 2 and 5 in their denominators.
    # This precision suffices for exact finite division; no binary64 conversion.
    with localcontext() as context:
        context.prec = len(str(abs(value.numerator))) + len(str(value.denominator)) + 2
        return str(Decimal(value.numerator) / Decimal(value.denominator))


def _object(value: object, required: set[str], allowed: set[str], field: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")  # noqa: TRY004 - malformed JSON data uses ValueError
    if required - value.keys() or value.keys() - allowed:
        raise ValueError(f"{field}: missing or unknown field(s)")
    return value


def _name(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f"{field} must be a nonempty string without control characters")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_plan(data: bytes) -> list[_Recording]:
    raw = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    root = _object(
        raw,
        {"recording_plan_schema_version", "recordings"},
        {"recording_plan_schema_version", "recordings"},
        "plan",
    )
    if (
        type(root["recording_plan_schema_version"]) is not int
        or root["recording_plan_schema_version"] != 1
    ):
        raise ValueError("recording_plan_schema_version must be integer 1")
    if not isinstance(root["recordings"], list) or not root["recordings"]:
        raise ValueError("recordings must be a nonempty array")
    recordings: list[_Recording] = []
    ids: set[str] = set()
    paths: set[str] = set()
    for index, item in enumerate(root["recordings"]):
        entry = _object(
            item,
            {"id", "path"},
            {"id", "path", "expected_channels", "time"},
            f"recordings[{index}]",
        )
        recording_id = _name(entry["id"], "id")
        path = _name(entry["path"], "path")
        pure = PurePosixPath(path)
        if (
            pure.is_absolute()
            or PureWindowsPath(path).drive
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or pure.suffix.lower() != ".csv"
            or ":" in path
        ):
            raise ValueError("path must be an exact relative POSIX CSV path without traversal")
        if recording_id in ids or path.casefold() in paths:
            raise ValueError("Duplicate recording id or case-insensitive path")
        ids.add(recording_id)
        paths.add(path.casefold())
        channels = None
        if "expected_channels" in entry:
            values = entry["expected_channels"]
            if not isinstance(values, list) or not values:
                raise ValueError("expected_channels must be a nonempty array")
            channels = tuple(_name(value, "expected_channels") for value in values)
            if len(set(channels)) != len(channels):
                raise ValueError("expected_channels must be unique")
        window = None
        if "time" in entry:
            fields = {"column", "unit", "start_s", "end_s", "max_gap_s", "boundary_tolerance_s"}
            time = _object(entry["time"], fields, fields, "time")
            if time["unit"] != "s":
                raise ValueError("time.unit must explicitly be 's'; no unit inference/conversion")
            column = _name(time["column"], "time.column")
            start = _exact_seconds(time["start_s"], "time.start_s")
            end = _exact_seconds(time["end_s"], "time.end_s")
            gap = _exact_seconds(time["max_gap_s"], "time.max_gap_s")
            tolerance = _exact_seconds(time["boundary_tolerance_s"], "time.boundary_tolerance_s")
            if start >= end or gap <= 0 or tolerance < 0 or 2 * tolerance >= end - start:
                raise ValueError(
                    "time requires start < end, gap > 0, and 0 <= 2*tolerance < duration"
                )
            window = _Window(column, start, end, gap, tolerance)
        recordings.append(_Recording(recording_id, path, channels, window))
    return recordings


def _entry(recording: _Recording) -> RecordingCoverage:
    window = recording.window
    return {
        "id": recording.id,
        "path": recording.path,
        "coverage_status": "NOT_EVALUATED",
        "file_status": "NOT_EVALUATED",
        "channel_status": "NOT_EVALUATED",
        "time_status": "NOT_EVALUATED",
        "source_sha256": None,
        "source_size_bytes": None,
        "rows": 0,
        "expected_channels": list(recording.channels) if recording.channels else None,
        "observed_channels": [],
        "missing_channels": [],
        "valid_samples": {},
        "expected_time": None
        if window is None
        else {
            "column": window.column,
            "unit": "s",
            "start_s": _decimal_text(window.start),
            "end_s": _decimal_text(window.end),
            "max_gap_s": _decimal_text(window.gap),
            "boundary_tolerance_s": _decimal_text(window.tolerance),
        },
        "observed_time": {},
        "inspection_metadata_status": None,
        "inspection_issues": [],
        "issues": [],
    }


def _finite_sample(value: str) -> bool:
    text = value.strip()
    if not _DECIMAL.fullmatch(text):
        return False
    try:
        return Decimal(text).is_finite()
    except InvalidOperation:
        return False


def _scan(handle: BinaryIO, recording: _Recording, result: RecordingCoverage) -> None:
    text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
    try:
        _scan_text(text, recording, result)
    finally:
        text.detach()


def _scan_text(text: io.TextIOBase, recording: _Recording, result: RecordingCoverage) -> None:
    reader = csv.reader(text, strict=True)
    header = _validate_header(next(reader, []))
    if header != result["observed_channels"]:
        raise ValueError("Source header changed between inspection and snapshot")
    channels = recording.channels
    window = recording.window
    positions = {name: header.index(name) for name in channels or () if name in header}
    missing = [name for name in channels or () if name not in positions]
    result["missing_channels"] = missing
    result["valid_samples"] = dict.fromkeys(positions, 0)
    result["file_status"] = "COMPLETE"
    result["channel_status"] = "NOT_EVALUATED" if channels is None else "COMPLETE"
    for name in missing:
        _issue(
            result["issues"], "MISSING_CHANNEL", "Expected source channel is absent", channel=name
        )
        result["channel_status"] = "INCOMPLETE"
    if channels is None:
        _issue(result["issues"], "CHANNEL_EXPECTATION_UNDECLARED", "Channel coverage not declared")
    time_index = header.index(window.column) if window and window.column in header else None
    result["time_status"] = "NOT_EVALUATED" if window is None else "COMPLETE"
    if window is None:
        _issue(result["issues"], "TIME_EXPECTATION_UNDECLARED", "Time coverage not declared")
    elif time_index is None:
        result["time_status"] = "INCOMPLETE"
        _issue(
            result["issues"],
            "MISSING_TIME_COLUMN",
            "Declared source clock is absent",
            channel=window.column,
        )
    first: Fraction | None = None
    last: Fraction | None = None
    previous: Fraction | None = None
    largest_gap = Fraction(0)
    valid_times = 0
    for row in reader:
        result["rows"] += 1
        row_number = reader.line_num
        if len(row) != len(header):
            raise ValueError(
                f"CSV row ending at line {row_number} has {len(row)} fields; expected {len(header)}"
            )
        for name, position in positions.items():
            if _finite_sample(row[position]):
                result["valid_samples"][name] += 1
            else:
                result["channel_status"] = "INCOMPLETE"
                _issue(
                    result["issues"],
                    "INVALID_CHANNEL_SAMPLE",
                    "Expected sample is not finite numeric data",
                    row=row_number,
                    channel=name,
                )
        if window is None or time_index is None:
            continue
        try:
            current = _exact_seconds(row[time_index].strip(), "source timestamp")
        except ValueError:
            result["time_status"] = "INCOMPLETE"
            _issue(
                result["issues"],
                "INVALID_TIMESTAMP",
                "Source timestamp is not supported finite decimal seconds",
                row=row_number,
                channel=window.column,
            )
            previous = None
            continue
        valid_times += 1
        if first is None:
            first = current
        last = current
        if previous is not None:
            interval = current - previous
            if interval <= 0:
                result["time_status"] = "INCOMPLETE"
                _issue(
                    result["issues"],
                    "CLOCK_NOT_INCREASING",
                    "Timestamps must strictly increase; no sorting or repair",
                    row=row_number,
                    channel=window.column,
                )
            elif previous < window.end and current > window.start:
                largest_gap = max(largest_gap, interval)
                if interval > window.gap:
                    result["time_status"] = "INCOMPLETE"
                    _issue(
                        result["issues"],
                        "TIME_GAP",
                        "An interval overlapping the expected window exceeds max_gap_s",
                        row=row_number,
                        channel=window.column,
                    )
        previous = current
    if result["rows"] == 0:
        result["file_status"] = "INCOMPLETE"
        _issue(result["issues"], "NO_SAMPLES", "Header metadata alone is not a recording")
    for name, count in result["valid_samples"].items():
        if count == 0:
            result["channel_status"] = "INCOMPLETE"
            _issue(
                result["issues"],
                "NO_VALID_SAMPLES",
                "Expected channel has no valid samples",
                channel=name,
            )
    if window is not None and time_index is not None:
        result["observed_time"] = {
            "first_s": None if first is None else _decimal_text(first),
            "last_s": None if last is None else _decimal_text(last),
            "valid_timestamps": valid_times,
            "largest_gap_s": _decimal_text(largest_gap),
        }
        if (
            valid_times < 2
            or first is None
            or last is None
            or first > window.start + window.tolerance
            or last < window.end - window.tolerance
        ):
            result["time_status"] = "INCOMPLETE"
            _issue(
                result["issues"],
                "WINDOW_NOT_COVERED",
                "Recording does not bracket the declared window within tolerance",
            )


def audit_recordings(
    input_directory: str | Path,
    *,
    plan: str | Path | None = None,
) -> RecordingAuditResult:
    """Check explicit recording expectations without running engineering analysis.

    Missing expectations stay NOT_EVALUATED. Invalid plans raise ValueError;
    per-record I/O/CSV errors are retained as ERROR. Inputs are never repaired.
    File identity uses resolved paths and filesystem identity, not equal hashes.
    """
    root = Path(input_directory).resolve()
    if not root.is_dir():
        raise ValueError("input_directory must be an existing directory")
    output: RecordingAuditResult = {
        "recording_audit_schema_version": 1,
        "scope": "declared_csv_recording_coverage",
        "coverage_status": "NOT_EVALUATED",
        "engineering_analysis_performed": False,
        "sensor_acquisition_freshness": "NOT_EVALUATED",
        "plan_sha256": None,
        "recordings": [],
        "issues": [],
    }
    if plan is None:
        _issue(output["issues"], "PLAN_UNDECLARED", "No recording expectation was supplied")
        return output
    plan_path = Path(plan)
    with capture_file_backed_snapshot(plan_path) as snapshot:
        recordings = _parse_plan(snapshot.handle.read())
        verify_file_unchanged(plan_path, snapshot.evidence)
        output["plan_sha256"] = snapshot.evidence.sha256
    resolved: list[Path | None] = []
    source: Path | None
    identities: dict[tuple, int] = {}
    assigned_files: dict[Path, tuple[int, int]] = {}
    conflicts: set[int] = set()
    # Preflight every assignment before scanning, so BOTH aliases remain unqualified.
    for recording in recordings:
        result = _entry(recording)
        output["recordings"].append(result)
        try:
            source = (root / recording.path).resolve()
            if not source.is_relative_to(root):
                raise ValueError("Recording resolves outside input_directory")
            if not source.exists():
                result["file_status"] = "INCOMPLETE"
                _issue(result["issues"], "MISSING_FILE", "Expected CSV file is absent")
                resolved.append(None)
                continue
            if not source.is_file():
                raise ValueError("Recording must be a regular file")
            stat = source.stat()
            assigned_files[source] = (stat.st_dev, stat.st_ino)
            identity = (stat.st_dev, stat.st_ino) if stat.st_ino else (str(source).casefold(),)
            if identity in identities:
                conflicts.update((identities[identity], len(resolved)))
            else:
                identities[identity] = len(resolved)
            resolved.append(source)
        except (OSError, ValueError) as exc:
            result["file_status"] = "ERROR"
            _issue(result["issues"], "SOURCE_ERROR", str(exc))
            resolved.append(None)
    for index, (recording, source, result) in enumerate(
        zip(recordings, resolved, output["recordings"], strict=True)
    ):
        if index in conflicts:
            result["file_status"] = "ERROR"
            _issue(
                result["issues"],
                "AMBIGUOUS_FILE_IDENTITY",
                "Multiple recording ids refer to the same physical file",
            )
        elif source is not None:
            try:
                inventory = inspect_measurement(source)
                result["observed_channels"] = [item["name"] for item in inventory["channels"]]
                result["inspection_metadata_status"] = inventory["metadata_status"]
                result["inspection_issues"] = inventory["issues"]
                with capture_file_backed_snapshot(source) as snapshot:
                    result["source_sha256"] = snapshot.evidence.sha256
                    result["source_size_bytes"] = snapshot.evidence.size_bytes
                    _scan(snapshot.handle, recording, result)
                    verify_file_unchanged(source, snapshot.evidence)
                current_stat = source.stat()
                if (current_stat.st_dev, current_stat.st_ino) != assigned_files[source]:
                    raise ValueError("Physical recording file changed after assignment")
                if (root / recording.path).resolve() != source:
                    raise ValueError("Recording assignment changed during audit")
            except (OSError, ValueError, csv.Error) as exc:
                result["file_status"] = "ERROR"
                _issue(result["issues"], "SOURCE_ERROR", str(exc))
        result["coverage_status"] = _status(
            [
                result["file_status"],
                result["channel_status"],
                result["time_status"],
            ]
        )
    output["coverage_status"] = _status([item["coverage_status"] for item in output["recordings"]])
    return output
