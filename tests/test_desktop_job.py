import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import batterylog.desktop_job as module
from batterylog.desktop_job import DesktopJob, DesktopOutcome

SAMPLE = Path(__file__).parents[1] / "examples/sample_battery_log.csv"


def finish(job: DesktopJob) -> DesktopOutcome:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        outcome = job.poll()
        if outcome is not None:
            return outcome
        time.sleep(0.02)
    job.cancel()
    pytest.fail("Desktop worker did not finish within 30 seconds")


@pytest.mark.parametrize("limit,status", [(50, "PASS"), (40, "FAIL"), (None, "NOT_EVALUATED")])
def test_real_worker_preserves_cli_results_and_evidence(tmp_path, limit, status):
    source = tmp_path / "ölçüm $data.CSV"
    source.write_bytes(SAMPLE.read_bytes())
    config = None
    if limit is not None:
        config = tmp_path / "ayar.yaml"
        config.write_text(f"limits:\n  temperature:\n    max_c: {limit}\n")
    cli_args = [sys.executable, "-m", "batterylog", str(source)]
    if config:
        cli_args.extend(["--config", str(config)])
    expected = json.loads(
        subprocess.run(cli_args, capture_output=True, text=True, check=False).stdout
    )
    job = DesktopJob(source, tmp_path, config)
    assert not (job.directory / "results").exists()
    outcome = finish(job)
    assert outcome.status == status
    assert outcome.report and outcome.report.is_file()
    payload = json.loads(outcome.report.with_name("result.json").read_text())
    assert payload == expected
    assert hashlib.sha256(source.read_bytes()).hexdigest() in outcome.report.read_text()
    if config:
        assert hashlib.sha256(config.read_bytes()).hexdigest() in outcome.report.read_text()
    assert sorted(p.name for p in job.directory.iterdir()) == ["results"]
    assert job.poll() is outcome
    job.cancel()
    assert job.poll() is outcome
    assert source.read_bytes() == SAMPLE.read_bytes()
    second = finish(DesktopJob(source, tmp_path, config))
    assert second.report != outcome.report
    assert outcome.report.exists()


@pytest.mark.parametrize(
    "kind", ["missing", "directory", "unsupported", "bad-output", "bad-config"]
)
def test_invalid_paths_do_not_create_output(tmp_path, kind):
    source, output, config = SAMPLE, tmp_path, None
    if kind == "missing":
        source = tmp_path / "missing.csv"
    elif kind == "directory":
        source = tmp_path / "folder.csv"
        source.mkdir()
    elif kind == "unsupported":
        source = tmp_path / "source.txt"
        source.touch()
    elif kind == "bad-output":
        output = tmp_path / "not-a-folder"
        output.touch()
    else:
        config = tmp_path
    before = set(tmp_path.iterdir())
    with pytest.raises((ValueError, OSError)):
        DesktopJob(source, output, config)
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize("kind", ["measurement", "config"])
def test_cli_input_errors_are_shown_without_partial_reports(tmp_path, kind):
    source, config = SAMPLE, None
    if kind == "measurement":
        source = tmp_path / "broken.csv"
        source.write_text("timestamp_s,temp_c\n0,25\n")
    else:
        config = tmp_path / "broken.yaml"
        config.write_text("limits: [invalid]\n")
    job = DesktopJob(source, tmp_path, config)
    outcome = finish(job)
    assert outcome.status == "ERROR"
    assert outcome.message
    assert outcome.report is None
    assert not job.directory.exists()


class CompletedProcess:
    def __init__(self, code):
        self.code = code
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True


def fake_worker(monkeypatch, code=0, complete=True, stderr=b""):
    process = CompletedProcess(code)

    def popen(command, **kwargs):
        report = Path(command[command.index("--report") + 1])
        report.write_text("<html>partial or complete</html>")
        if complete:
            report.with_name("result.json").write_text("{}")
        kwargs["stderr"].write(stderr)
        return process

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    return process


@pytest.mark.parametrize("code,complete", [(4, True), (0, False), (2, True), (-9, True)])
def test_failed_or_incomplete_worker_never_publishes(monkeypatch, tmp_path, code, complete):
    fake_worker(monkeypatch, code, complete)
    job = DesktopJob(SAMPLE, tmp_path)
    outcome = job.poll()
    assert outcome.status == "ERROR"
    assert outcome.report is None
    assert not job.directory.exists()


def test_cancel_wins_before_completed_result_is_observed(monkeypatch, tmp_path):
    process = fake_worker(monkeypatch)
    job = DesktopJob(SAMPLE, tmp_path)
    job.cancel()
    job.cancel()
    assert process.terminated
    assert job.poll().status == "CANCELLED"
    assert not job.directory.exists()


def test_spawn_failure_removes_owned_directory(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise OSError("cannot start worker")

    monkeypatch.setattr(module.subprocess, "Popen", fail)
    with pytest.raises(OSError, match="cannot start"):
        DesktopJob(SAMPLE, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_diagnostics_are_bounded_and_invalid_utf8_is_displayable(monkeypatch, tmp_path):
    fake_worker(monkeypatch, code=4, stderr=b"\xff" + b"a" * 100_000)
    job = DesktopJob(SAMPLE, tmp_path)
    outcome = job.poll()
    assert outcome.status == "ERROR"
    assert len(outcome.message) == 8192
    assert outcome.message.startswith("\ufffd")


def test_publish_failure_removes_partial_files(monkeypatch, tmp_path):
    fake_worker(monkeypatch)
    job = DesktopJob(SAMPLE, tmp_path)

    def fail(*args):
        raise OSError("publish denied")

    monkeypatch.setattr(Path, "rename", fail)
    assert job.poll().message == "publish denied"
    assert not job.directory.exists()


def test_cleanup_failure_is_visible(monkeypatch, tmp_path):
    fake_worker(monkeypatch, code=4)
    job = DesktopJob(SAMPLE, tmp_path)

    def fail(*args):
        raise OSError("cleanup denied")

    with monkeypatch.context() as patch:
        patch.setattr(module.shutil, "rmtree", fail)
        assert "cleanup denied" in job.poll().message
        assert str(job.directory) in job.poll().message
    module.shutil.rmtree(job.directory)


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX signal escalation; Windows terminate is immediate"
)
def test_cancel_kills_real_worker_that_ignores_terminate(monkeypatch, tmp_path):
    original = subprocess.Popen
    ready = tmp_path / "ready"

    def spawn(command, **kwargs):
        return original(
            [
                sys.executable,
                "-c",
                (
                    "import signal,time,pathlib; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    f"pathlib.Path({str(ready)!r}).touch(); time.sleep(60)"
                ),
            ],
            **kwargs,
        )

    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    job = DesktopJob(SAMPLE, tmp_path)
    deadline = time.monotonic() + 5
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()
    job.cancel()
    assert job.poll() is None
    outcome = finish(job)
    assert outcome.status == "CANCELLED"
    assert not job.directory.exists()
