"""Single CLI subprocess owned by the desktop launcher; no GUI dependency."""

import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class DesktopOutcome:
    status: str
    message: str
    report: Path | None = None


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
        self._stderr.seek(0)
        error = self._stderr.read(8192).decode("utf-8", errors="replace").strip()
        self._stderr.close()
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
                (self.directory / "stderr.log").unlink()
                # This destination belongs to our exclusively created run directory.
                self._staging.rename(self.directory / "results")
                status, message = {
                    0: ("PASS", "The configured validation rules passed."),
                    1: ("FAIL", "Configured validation rules failed. Open the report for details."),
                    3: (
                        "NOT_EVALUATED",
                        "No validation conclusion was reached. Open the report for details.",
                    ),
                }[code]
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
