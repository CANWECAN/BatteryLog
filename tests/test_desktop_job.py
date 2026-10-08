import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import batterylog.desktop_job as module
from batterylog.desktop_job import (
    DesktopBatchJob,
    DesktopBatchOutcome,
    DesktopInspectionJob,
    DesktopInspectionOutcome,
    DesktopJob,
    DesktopOutcome,
)

SAMPLE = Path(__file__).parents[1] / "examples/sample_battery_log.csv"
VALID_PASS = Path(__file__).with_name("golden") / "semantic_all_rules_pass.json"


def finish(job: DesktopJob) -> DesktopOutcome:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        outcome = job.poll()
        if outcome is not None:
            return outcome
        time.sleep(0.02)
    job.cancel()
    pytest.fail("Desktop worker did not finish within 30 seconds")


def finish_inspection(job: DesktopInspectionJob) -> DesktopInspectionOutcome:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        outcome = job.poll()
        if outcome is not None:
            return outcome
        time.sleep(0.02)
    job.cancel()
    pytest.fail("Desktop inspection worker did not finish within 30 seconds")


def finish_batch(job: DesktopBatchJob) -> DesktopBatchOutcome:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        outcome = job.poll()
        if outcome is not None:
            return outcome
        time.sleep(0.02)
    job.cancel()
    pytest.fail("Desktop batch worker did not finish within 60 seconds")


def test_real_batch_worker_preserves_cli_summary_and_unique_output(tmp_path):
    source = tmp_path / "measurements"
    nested = source / "nested"
    nested.mkdir(parents=True)
    (source / "a.csv").write_bytes(SAMPLE.read_bytes())
    (nested / "b.csv").write_bytes(SAMPLE.read_bytes())
    output_parent = tmp_path / "results"
    output_parent.mkdir()
    config = tmp_path / "validation.yaml"
    config.write_text("limits:\n  temperature:\n    max_c: 40\n", encoding="utf-8")

    first = DesktopBatchJob(source, output_parent, config, recursive=True)
    first_outcome = finish_batch(first)
    assert first_outcome.status == "FAIL"
    assert first_outcome.summary is not None
    assert [item["source"] for item in first_outcome.summary["files"]] == [
        "a.csv",
        "nested/b.csv",
    ]
    assert {item["status"] for item in first_outcome.summary["files"]} == {"FAIL"}
    assert first_outcome.summary_csv == first.directory / "summary.csv"
    assert first_outcome.summary_csv.is_file()
    assert first.directory.parent == output_parent
    assert first.directory.is_dir()

    second = DesktopBatchJob(source, output_parent, config, recursive=False)
    second_outcome = finish_batch(second)
    assert second_outcome.status == "FAIL"
    assert second_outcome.summary is not None
    assert [item["source"] for item in second_outcome.summary["files"]] == ["a.csv"]
    assert second.directory != first.directory
    assert first.directory.exists()


def test_batch_worker_rejects_output_inside_input(tmp_path):
    source = tmp_path / "measurements"
    source.mkdir()
    (source / "a.csv").write_bytes(SAMPLE.read_bytes())
    with pytest.raises(ValueError, match="outside the input folder"):
        DesktopBatchJob(source, source)


def test_batch_worker_keeps_valid_summary_when_one_file_errors(tmp_path):
    source = tmp_path / "measurements"
    source.mkdir()
    (source / "good.csv").write_bytes(SAMPLE.read_bytes())
    (source / "broken.csv").write_text("timestamp_s,temp_c\n0,25\n", encoding="utf-8")
    output_parent = tmp_path / "results"
    output_parent.mkdir()

    job = DesktopBatchJob(source, output_parent)
    outcome = finish_batch(job)
    assert outcome.status == "ERROR"
    assert outcome.summary is not None
    assert {item["source"]: item["status"] for item in outcome.summary["files"]} == {
        "broken.csv": "ERROR",
        "good.csv": "NOT_EVALUATED",
    }
    assert outcome.summary_csv is not None and outcome.summary_csv.is_file()
    assert "1 ERROR" in outcome.message


def test_batch_worker_config_error_has_no_false_summary(tmp_path):
    source = tmp_path / "measurements"
    source.mkdir()
    (source / "a.csv").write_bytes(SAMPLE.read_bytes())
    output_parent = tmp_path / "results"
    output_parent.mkdir()
    config = tmp_path / "broken.yaml"
    config.write_text("limits: [invalid]\n", encoding="utf-8")

    job = DesktopBatchJob(source, output_parent, config)
    outcome = finish_batch(job)
    assert outcome.status == "ERROR"
    assert outcome.summary is None
    assert outcome.summary_csv is None
    assert "must be a mapping" in outcome.message
    assert not job.directory.exists()


def test_batch_cancel_stops_worker_and_preserves_existing_summary(monkeypatch, tmp_path):
    source = tmp_path / "measurements"
    source.mkdir()
    (source / "a.csv").write_bytes(SAMPLE.read_bytes())
    output_parent = tmp_path / "results"
    output_parent.mkdir()
    ready = tmp_path / "ready"
    original = subprocess.Popen

    def waiting_worker(command, **kwargs):
        return original(
            [
                sys.executable,
                "-c",
                (f"import pathlib,time; pathlib.Path({str(ready)!r}).touch(); time.sleep(60)"),
            ],
            **kwargs,
        )

    monkeypatch.setattr(module.subprocess, "Popen", waiting_worker)
    job = DesktopBatchJob(source, output_parent)
    deadline = time.monotonic() + 5
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()
    job.directory.mkdir()
    summary = job.directory / "summary.csv"
    summary.write_text("source,status\na.csv,NOT_PROCESSED\n", encoding="utf-8")
    job.cancel()
    outcome = finish_batch(job)
    assert outcome.status == "CANCELLED"
    assert outcome.summary_csv == summary
    assert summary.is_file()
    assert job.directory.is_dir()


def test_real_inspection_worker_reports_channels_without_analysis(tmp_path):
    job = DesktopInspectionJob(SAMPLE)
    directory = job._directory
    outcome = finish_inspection(job)
    assert not directory.exists()
    assert outcome.status == "OK"
    assert outcome.inspection is not None
    assert outcome.inspection["analysis_performed"] is False
    assert outcome.inspection["source_format"] == "csv"
    assert [item["name"] for item in outcome.inspection["channels"]] == [
        "timestamp_s",
        "current_a",
        "soc_pct",
        "temp_c",
        "cell_1_v",
        "cell_2_v",
        "cell_3_v",
        "cell_4_v",
    ]
    assert {item["canonical"] for item in outcome.inspection["bindings"]} == {
        "timestamp_s",
        "temp_c",
        "cell_1_v",
        "cell_2_v",
        "cell_3_v",
        "cell_4_v",
    }


def test_real_inspection_worker_surfaces_selection_issues(tmp_path):
    broken = tmp_path / "broken.csv"
    broken.write_text("timestamp_s,temp_c\n0,25\n", encoding="utf-8")
    outcome = finish_inspection(DesktopInspectionJob(broken))
    assert outcome.status == "ISSUES"
    assert outcome.inspection is not None
    assert outcome.inspection["bindings"] == []
    assert outcome.inspection["issues"] == ["No cell voltage columns found"]


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
    "kind,status", [("all", "FAIL"), ("pass", "PASS"), ("short", "NOT_EVALUATED")]
)
def test_real_worker_preserves_failure_model_evidence(tmp_path, kind, status):
    source = SAMPLE.with_name("failure_models_demo.csv")
    config = tmp_path / "models.yaml"
    if kind == "all":
        config.write_bytes(SAMPLE.with_name("failure_models.example.yaml").read_bytes())
    else:
        duration = 2 if kind == "pass" else 20
        config.write_text(
            "schema_version: 7\nfailure_models:\n  max_gap_s: 2\n"
            f"  sustained_imbalance:\n    max_delta_v: 1\n    duration_s: {duration}\n",
            encoding="utf-8",
        )
    expected = json.loads(
        subprocess.run(
            [sys.executable, "-m", "batterylog", str(source), "--config", str(config)],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    )
    outcome = finish(DesktopJob(source, tmp_path, config))
    assert outcome.status == status
    assert outcome.report is not None
    payload = json.loads(outcome.report.with_name("result.json").read_text(encoding="utf-8"))
    assert payload == expected
    assert payload["schema_version"] == 9
    html = outcome.report.read_text(encoding="utf-8")
    assert hashlib.sha256(source.read_bytes()).hexdigest() in html
    assert hashlib.sha256(config.read_bytes()).hexdigest() in html
    if kind == "all":
        codes = {item["code"] for item in payload["failure_models"]["evaluations"]}
        assert codes == {
            "CELL_IMBALANCE_SUSTAINED",
            "TEMPERATURE_RISE_HIGH",
            "CELL_SAG_UNDER_LOAD",
            "BALANCING_INEFFECTIVE",
            "BALANCING_ACTIVE_TOO_LONG",
        }
        assert all(code in html for code in codes)
        assert sum(len(item["events"]) for item in payload["failure_models"]["evaluations"]) == 5


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


def fake_worker(monkeypatch, code=0, complete=True, stderr=b"", result_text=None):
    process = CompletedProcess(code)

    def popen(command, **kwargs):
        report = Path(command[command.index("--report") + 1])
        report.write_text("<html>partial or complete</html>")
        if complete:
            payload = VALID_PASS.read_text(encoding="utf-8") if result_text is None else result_text
            report.with_name("result.json").write_text(payload, encoding="utf-8")
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


@pytest.mark.parametrize("payload", ["{}", "[]", "not-json"])
def test_worker_never_publishes_invalid_result_payload(monkeypatch, tmp_path, payload):
    fake_worker(monkeypatch, code=0, result_text=payload)
    job = DesktopJob(SAMPLE, tmp_path)
    outcome = job.poll()
    assert outcome.status == "ERROR"
    assert outcome.report is None
    assert not job.directory.exists()


def test_worker_never_publishes_exit_status_mismatch(monkeypatch, tmp_path):
    fake_worker(monkeypatch, code=1)
    job = DesktopJob(SAMPLE, tmp_path)
    outcome = job.poll()
    assert outcome.status == "ERROR"
    assert "disagrees with result status" in outcome.message
    assert outcome.report is None
    assert not job.directory.exists()


@pytest.mark.parametrize(
    ("key", "value"), [("cells_detected", "not-an-integer"), ("unexpected_field", 123)]
)
def test_worker_never_publishes_schema_invalid_result(monkeypatch, tmp_path, key, value):
    payload = json.loads(VALID_PASS.read_text(encoding="utf-8"))
    payload[key] = value
    fake_worker(monkeypatch, code=0, result_text=json.dumps(payload))
    job = DesktopJob(SAMPLE, tmp_path)
    outcome = job.poll()
    assert outcome.status == "ERROR"
    assert outcome.report is None
    assert not job.directory.exists()


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_worker_never_publishes_non_json_numbers(monkeypatch, tmp_path, token):
    payload = VALID_PASS.read_text(encoding="utf-8").replace(
        '"max_cell_voltage_v": 4.25', f'"max_cell_voltage_v": {token}'
    )
    fake_worker(monkeypatch, code=0, result_text=payload)
    job = DesktopJob(SAMPLE, tmp_path)
    outcome = job.poll()
    assert outcome.status == "ERROR"
    assert "Non-JSON number" in outcome.message
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


def test_diagnostic_read_failure_is_an_error_and_cleans_outputs(monkeypatch, tmp_path):
    fake_worker(monkeypatch)
    job = DesktopJob(SAMPLE, tmp_path)
    original = job._stderr

    class BrokenLog:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            original.close()

        def seek(self, offset):
            raise OSError("diagnostic disk error")

    job._stderr = BrokenLog()
    outcome = job.poll()
    assert outcome.status == "ERROR"
    assert "diagnostic disk error" in outcome.message
    assert original.closed
    assert not job.directory.exists()


@pytest.mark.parametrize("ignore_sigint", [False, True])
def test_batch_cancel_finalizes_real_cli_summary(monkeypatch, tmp_path, ignore_sigint):
    source = tmp_path / "measurements"
    source.mkdir()
    for name in ("a.csv", "b.csv"):
        (source / name).write_bytes(SAMPLE.read_bytes())
    output_parent = tmp_path / "results"
    output_parent.mkdir()
    ready = tmp_path / "second-file-ready"
    original = subprocess.Popen

    def delayed_cli(command, **kwargs):
        # Run the actual worker/CLI, delaying only the second file to cancel deterministically.
        child = (
            "import runpy,signal,sys,time\n"
            f"if {ignore_sigint!r}: signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "from pathlib import Path\n"
            "import batterylog.batch as batch\n"
            "original = batch._analyze_file\n"
            "def delayed(source, *args):\n"
            "    if source.name == 'b.csv':\n"
            f"        Path({str(ready)!r}).touch()\n"
            "        while True: time.sleep(0.01)\n"
            "    return original(source, *args)\n"
            "batch._analyze_file = delayed\n"
            f"sys.argv = ['batterylog', *{command[3:]!r}]\n"
            f"runpy.run_module({command[2]!r}, run_name='__main__')\n"
        )
        return original([sys.executable, "-c", child], **kwargs)

    monkeypatch.setattr(module.subprocess, "Popen", delayed_cli)
    job = DesktopBatchJob(source, output_parent)
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            assert job._process.poll() is None
            time.sleep(0.02)
        assert ready.exists()
        completed = job.directory / "files/a.csv"
        json_before = (completed / "result.json").read_bytes()
        html_before = (completed / "report.html").read_bytes()
        job.cancel()
        outcome = finish_batch(job)
        assert outcome.status == "CANCELLED"
        assert outcome.summary_csv is not None
        assert job._process.returncode == 130
        assert job._process.stdin.closed
        job.cancel()
        with outcome.summary_csv.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert {row["source"]: row["status"] for row in rows} == {
            "a.csv": "NOT_EVALUATED",
            "b.csv": "NOT_PROCESSED",
        }
        assert (completed / "result.json").read_bytes() == json_before
        assert (completed / "report.html").read_bytes() == html_before
        assert not (job.directory / "files/b.csv").exists()
        assert not job._directory.exists()
        assert job.poll() is outcome
    finally:
        if job._process.poll() is None:
            job._process.kill()
            job._process.wait(timeout=5)
        for handle in (job._stdout, job._stderr, job._process.stdin):
            if handle is not None:
                handle.close()


@pytest.mark.parametrize("status", [[], {"unexpected": "status"}])
def test_batch_worker_handles_malformed_status_without_crashing_poll(monkeypatch, tmp_path, status):
    source = tmp_path / "input"
    source.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    original = subprocess.Popen
    payload = json.dumps(
        {
            "batch_schema_version": 1,
            "summary_csv": "summary.csv",
            "files": [{"source": "a.csv", "status": status}],
        }
    )

    def corrupt_summary(command, **kwargs):
        return original([sys.executable, "-c", f"print({payload!r})"], **kwargs)

    monkeypatch.setattr(module.subprocess, "Popen", corrupt_summary)
    job = DesktopBatchJob(source, output)
    try:
        outcome = finish_batch(job)
        assert outcome.status == "ERROR"
        assert "invalid file status" in outcome.message
        assert outcome.summary is None
        assert not job._directory.exists()
    finally:
        if job._directory.exists():
            module.shutil.rmtree(job._directory)


@pytest.mark.parametrize("field", ["source_format", "time_basis", "metadata_status"])
@pytest.mark.parametrize("invalid", [[], {"unexpected": "value"}])
def test_inspection_rejects_unhashable_enum_and_cleans_worker(monkeypatch, field, invalid):
    payload = {
        "inspection_schema_version": 1,
        "scope": "channel_metadata_only",
        "analysis_performed": False,
        "source_format": "csv",
        "time_basis": "csv_column",
        "metadata_status": "OK",
        "channels": [],
        "bindings": [],
        "issues": [],
    }
    payload[field] = invalid

    def fake_inspection_worker(command, **kwargs):
        kwargs["stdout"].write(json.dumps(payload).encode("utf-8"))
        return CompletedProcess(0)

    monkeypatch.setattr(module.subprocess, "Popen", fake_inspection_worker)
    job = DesktopInspectionJob(SAMPLE)
    directory = job._directory
    outcome = job.poll()
    assert outcome is not None and outcome.status == "ERROR"
    assert field in outcome.message
    assert outcome.inspection is None
    assert not directory.exists()
    assert job.poll() is outcome
