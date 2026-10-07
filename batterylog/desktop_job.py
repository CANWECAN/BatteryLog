"""Single CLI subprocess owned by the desktop launcher; no GUI dependency."""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import BinaryIO, cast

from jsonschema import Draft202012Validator, ValidationError

from .inspection import InspectionResult
from .models import AnalysisResult
from .result_validation import validate_result_semantics


@dataclass(frozen=True)
class DesktopOutcome:
    status: str
    message: str
    report: Path | None = None


@dataclass(frozen=True)
class DesktopInspectionOutcome:
    status: str
    message: str
    inspection: InspectionResult | None = None


_STATUS_BY_EXIT = {0: "PASS", 1: "FAIL", 3: "NOT_EVALUATED"}


@lru_cache(maxsize=2)
def _result_validator(version: int) -> Draft202012Validator:
    if version not in (8, 9):
        raise ValueError(f"Unsupported result schema version: {version!r}")
    schema = json.loads(
        files("batterylog").joinpath(f"schema/result-v{version}.json").read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema)


def _reject_non_json_number(token: str) -> None:
    raise ValueError(f"Non-JSON number: {token}")


def _validate_published_result(path: Path, exit_code: int) -> str:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_non_json_number
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise OSError(f"Analysis produced invalid result JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OSError("Analysis result JSON must be an object.")
    try:
        _result_validator(payload.get("schema_version")).validate(payload)
        result = cast(AnalysisResult, payload)
        validate_result_semantics(result)
        status = result["validation_status"]
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise OSError(f"Analysis produced an invalid result payload: {exc}") from exc
    expected = _STATUS_BY_EXIT[exit_code]
    if status != expected:
        raise OSError(
            f"Analysis process exit code {exit_code} disagrees with result status {status!r}."
        )
    return status


class DesktopJob:
    """Poll without blocking the UI; publish the report pair only after CLI completion."""

    def __init__(self, measurement: Path, output_parent: Path, config: Path | None = None):
        measurement = measurement.expanduser().resolve(strict=True)
        output_parent = output_parent.expanduser().resolve(strict=True)
        if not measurement.is_file() or measurement.suffix.lower() not in {".csv", ".mdf", ".mf4"}:
            raise ValueError("Select a CSV, MDF or MF4 measurement file.")
        if not output_parent.is_dir():
            raise ValueError("Select an existing output folder.")
        if config is not None:
            config = config.expanduser().resolve(strict=True)
            if not config.is_file():
                raise ValueError("Select a YAML configuration file, or leave it empty.")
        self.directory = Path(tempfile.mkdtemp(prefix="batterylog-", dir=output_parent))
        self._staging = self.directory / ".pending"
        self._stderr: BinaryIO | None = None
        self._cancel_at: float | None = None
        self._outcome: DesktopOutcome | None = None
        try:
            self._staging.mkdir()
            self._stderr = (self.directory / "stderr.log").open("w+b")
            command = [
                sys.executable,
                "-m",
                "batterylog",
                str(measurement),
                "--report",
                str(self._staging / "report.html"),
                "--json-out",
                str(self._staging / "result.json"),
            ]
            if config is not None:
                command.extend(["--config", str(config)])
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=self._stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32"
                else 0,
            )
        except BaseException:
            if self._stderr is not None:
                self._stderr.close()
            shutil.rmtree(self.directory)
            raise

    def cancel(self) -> None:
        if self._outcome is None and self._cancel_at is None:
            self._cancel_at = time.monotonic()
            self._process.terminate()

    def poll(self) -> DesktopOutcome | None:
        if self._outcome is not None:
            return self._outcome
        code = self._process.poll()
        if code is None:
            if self._cancel_at is not None and time.monotonic() - self._cancel_at >= 2:
                self._process.kill()
            return None
        assert self._stderr is not None
        try:
            with self._stderr:
                self._stderr.seek(0)
                error = self._stderr.read(8192).decode("utf-8", errors="replace").strip()
        except OSError as exc:
            code = 4
            error = f"Cannot read process diagnostics: {exc}"
        if self._cancel_at is not None:
            outcome = DesktopOutcome("CANCELLED", "Analysis cancelled. No report was published.")
        elif code not in {0, 1, 3}:
            outcome = DesktopOutcome("ERROR", error or f"Analysis process exited with code {code}.")
        else:
            try:
                for name in ("report.html", "result.json"):
                    if (
                        not (self._staging / name).is_file()
                        or not (self._staging / name).stat().st_size
                    ):
                        raise OSError(f"Analysis did not produce a complete {name}.")
                status = _validate_published_result(self._staging / "result.json", code)
                (self.directory / "stderr.log").unlink()
                # This destination belongs to our exclusively created run directory.
                self._staging.rename(self.directory / "results")
                message = {
                    "PASS": "The configured validation rules passed.",
                    "FAIL": "Configured validation rules failed. Open the report for details.",
                    "NOT_EVALUATED": (
                        "No validation conclusion was reached. Open the report for details."
                    ),
                }[status]
                outcome = DesktopOutcome(status, message, self.directory / "results/report.html")
            except OSError as exc:
                outcome = DesktopOutcome("ERROR", str(exc))
        if outcome.report is None:
            try:
                shutil.rmtree(self.directory)
            except OSError as exc:
                outcome = DesktopOutcome(
                    "ERROR", f"{outcome.message}\nCleanup failed for {self.directory}: {exc}"
                )
        self._outcome = outcome
        return outcome


def _validate_inspection_payload(payload: object, exit_code: int) -> InspectionResult:
    if not isinstance(payload, dict):
        raise OSError("Inspection JSON must be an object.")
    required = {
        "inspection_schema_version": 1,
        "scope": "channel_metadata_only",
        "analysis_performed": False,
    }
    for key, expected in required.items():
        if payload.get(key) != expected:
            raise OSError(f"Inspection payload has invalid {key!r}.")
    if payload.get("source_format") not in {"csv", "mf4"}:
        raise OSError("Inspection payload has invalid source_format.")
    if payload.get("time_basis") not in {"csv_column", "mdf_master"}:
        raise OSError("Inspection payload has invalid time_basis.")
    status = payload.get("metadata_status")
    if status not in {"OK", "ISSUES"}:
        raise OSError("Inspection payload has invalid metadata_status.")
    for key in ("channels", "bindings", "issues"):
        if not isinstance(payload.get(key), list):
            raise OSError(f"Inspection payload field {key!r} must be a list.")
    expected_exit = 0 if status == "OK" else 4
    if exit_code != expected_exit:
        raise OSError(
            f"Inspection process exit code {exit_code} disagrees with metadata status {status!r}."
        )
    return cast(InspectionResult, payload)


class DesktopInspectionJob:
    """Inspect source metadata in the CLI subprocess without blocking Tk."""

    def __init__(self, measurement: Path, config: Path | None = None):
        measurement = measurement.expanduser().resolve(strict=True)
        if not measurement.is_file() or measurement.suffix.lower() not in {".csv", ".mdf", ".mf4"}:
            raise ValueError("Select a CSV, MDF or MF4 measurement file.")
        if config is not None:
            config = config.expanduser().resolve(strict=True)
            if not config.is_file():
                raise ValueError("Select a YAML configuration file, or leave it empty.")
        self._directory = Path(tempfile.mkdtemp(prefix="batterylog-inspect-"))
        self._stdout: BinaryIO | None = None
        self._stderr: BinaryIO | None = None
        self._cancel_at: float | None = None
        self._outcome: DesktopInspectionOutcome | None = None
        command = [sys.executable, "-m", "batterylog", str(measurement), "--inspect"]
        if config is not None:
            command.extend(["--config", str(config)])
        try:
            self._stdout = (self._directory / "stdout.json").open("w+b")
            self._stderr = (self._directory / "stderr.log").open("w+b")
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=self._stdout,
                stderr=self._stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32"
                else 0,
            )
        except BaseException:
            if self._stdout is not None:
                self._stdout.close()
            if self._stderr is not None:
                self._stderr.close()
            shutil.rmtree(self._directory)
            raise

    def cancel(self) -> None:
        if self._outcome is None and self._cancel_at is None:
            self._cancel_at = time.monotonic()
            self._process.terminate()

    def poll(self) -> DesktopInspectionOutcome | None:
        if self._outcome is not None:
            return self._outcome
        code = self._process.poll()
        if code is None:
            if self._cancel_at is not None and time.monotonic() - self._cancel_at >= 2:
                self._process.kill()
            return None

        assert self._stdout is not None and self._stderr is not None
        try:
            with self._stdout, self._stderr:
                self._stdout.seek(0)
                self._stderr.seek(0)
                raw_output = self._stdout.read()
                error = self._stderr.read(8192).decode("utf-8", errors="replace").strip()
        except OSError as exc:
            outcome = DesktopInspectionOutcome("ERROR", f"Cannot read inspection output: {exc}")
        else:
            if self._cancel_at is not None:
                outcome = DesktopInspectionOutcome("CANCELLED", "Inspection cancelled.")
            elif code not in {0, 4}:
                outcome = DesktopInspectionOutcome(
                    "ERROR", error or f"Inspection process exited with code {code}."
                )
            elif not raw_output:
                outcome = DesktopInspectionOutcome(
                    "ERROR", error or "Inspection did not produce metadata JSON."
                )
            else:
                try:
                    payload = json.loads(
                        raw_output.decode("utf-8"), parse_constant=_reject_non_json_number
                    )
                    inspection = _validate_inspection_payload(payload, code)
                except (UnicodeError, ValueError, OSError) as exc:
                    outcome = DesktopInspectionOutcome(
                        "ERROR", error or f"Inspection produced invalid metadata JSON: {exc}"
                    )
                else:
                    outcome = DesktopInspectionOutcome(
                        inspection["metadata_status"],
                        "Channel metadata inspection completed.",
                        inspection,
                    )
        try:
            shutil.rmtree(self._directory)
        except OSError as exc:
            outcome = DesktopInspectionOutcome(
                "ERROR", f"{outcome.message}\nInspection cleanup failed: {exc}"
            )
        self._outcome = outcome
        return outcome
