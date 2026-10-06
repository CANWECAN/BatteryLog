import hashlib
import json
import time
from pathlib import Path

import pytest

from batterylog.desktop_demo import create_demo
from batterylog.desktop_job import DesktopJob


def test_demo_runs_real_analysis_with_two_explained_violations(tmp_path):
    existing = tmp_path / "measurement.csv"
    existing.write_text("user data", encoding="utf-8")
    demo = create_demo(tmp_path)
    source = demo / "synthetic_demo.csv"
    config = demo / "validation.yaml"
    before = (source.read_bytes(), config.read_bytes())
    job = DesktopJob(source, demo, config)
    deadline = time.monotonic() + 30
    outcome = None
    while time.monotonic() < deadline:
        outcome = job.poll()
        if outcome is not None:
            break
        time.sleep(0.02)
    assert outcome is not None
    assert outcome.status == "FAIL"
    assert outcome.report is not None
    result = json.loads(outcome.report.with_name("result.json").read_text(encoding="utf-8"))
    assert result["rows_analyzed"] == 5
    assert result["cells_detected"] == 4
    assert result["max_temperature_c"] == 48
    assert result["max_delta_v"] == pytest.approx(0.1)
    assert {v["code"] for v in result["violations"]} == {
        "CELL_IMBALANCE_HIGH",
        "TEMPERATURE_HIGH",
    }
    assert len(result["violations"]) == 2
    html = outcome.report.read_text(encoding="utf-8")
    assert hashlib.sha256(before[0]).hexdigest() in html
    assert hashlib.sha256(before[1]).hexdigest() in html
    assert (source.read_bytes(), config.read_bytes()) == before
    assert existing.read_text(encoding="utf-8") == "user data"
    second = create_demo(tmp_path)
    assert second != demo
    assert (second / "synthetic_demo.csv").read_bytes() == before[0]
    assert (second / "validation.yaml").read_bytes() == before[1]


def test_partial_demo_creation_is_removed(monkeypatch, tmp_path):
    original = Path.write_text

    def fail_on_config(path, *args, **kwargs):
        if path.name == "validation.yaml":
            raise OSError("cannot write demo config")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_on_config)
    with pytest.raises(OSError, match="cannot write demo config"):
        create_demo(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_demo_creation_reports_cleanup_failure(monkeypatch, tmp_path):
    from batterylog import desktop_demo

    def fail_write(*args, **kwargs):
        raise OSError("cannot write demo")

    def fail_cleanup(*args, **kwargs):
        raise OSError("cannot remove demo")

    monkeypatch.setattr(Path, "write_text", fail_write)
    monkeypatch.setattr(desktop_demo.shutil, "rmtree", fail_cleanup)
    with pytest.raises(OSError, match="Demo cleanup failed for") as exc:
        create_demo(tmp_path)
    assert str(tmp_path) in str(exc.value)


def test_demo_requires_existing_directory(tmp_path):
    file = tmp_path / "file"
    file.touch()
    with pytest.raises(ValueError, match="existing folder"):
        create_demo(file)
    with pytest.raises(OSError):
        create_demo(tmp_path / "missing")
    assert list(tmp_path.iterdir()) == [file]
