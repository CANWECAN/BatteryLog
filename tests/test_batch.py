import csv
import hashlib
import json
from pathlib import Path

import pytest

import batterylog.batch as batch_module
from batterylog import (
    AnalysisService,
    DataQualityConfig,
    ValidationConfig,
    ValidationLimits,
    analyze_directory,
)
from batterylog.__main__ import run
from batterylog.reporting import render_json_result

HEADER = "timestamp_s,cell_1_v,temp_c\n"


def _source(root: Path, name: str, rows: str = "0,3.5,25\n") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def _service(**limits) -> AnalysisService:
    return AnalysisService(ValidationConfig(limits=ValidationLimits(**limits)))


def _csv(root: Path) -> list[dict[str, str]]:
    with (root / "summary.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_batch_preserves_per_file_results_and_reports_complete_evidence(tmp_path):
    source = tmp_path / "logs"
    first = _source(source, "a.csv")
    second = _source(source, "b.CSV", "0,4.5,25\n1,3.5,25\n")
    bad = _source(source, "c.csv", "0,bad,25\n")
    out = tmp_path / "results"
    service = _service(cell_max_v=4.2)

    summary = analyze_directory(source, out, service=service)

    assert summary["batch_schema_version"] == 1
    assert summary["summary_csv"] == "summary.csv"
    assert [item["source"] for item in summary["files"]] == ["a.csv", "b.CSV", "c.csv"]
    assert [item["status"] for item in summary["files"]] == ["PASS", "FAIL", "ERROR"]
    for path, item in zip((first, second), summary["files"]):
        expected = service.analyze_path(path).result
        result_path = out / item["result_json"]
        assert result_path.read_text() == render_json_result(expected)
        assert item["rows_input"] == expected["rows_input"]
        assert item["rows_excluded"] == 0
        assert item["violation_events"] == len(expected["violations"])
        assert item["max_cell_voltage_v"] == expected["max_cell_voltage_v"]
        assert item["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        html = (out / item["report_html"]).read_text()
        assert item["source_sha256"] in html
        assert "<svg " in html
    error = summary["files"][2]
    assert "cell_1_v" in error["error"]
    assert error["result_json"] is error["report_html"] is error["rows_analyzed"] is None
    assert not (out / "files" / bad.name).exists()
    csv_rows = _csv(out)
    assert [row["status"] for row in csv_rows] == ["PASS", "FAIL", "ERROR"]
    assert csv_rows[2]["rows_input"] == ""
    assert not list(out.rglob(".batterylog-*"))
    assert not list(out.glob(".summary.*"))


@pytest.mark.parametrize("recursive", [False, True])
def test_discovery_is_sorted_and_preserves_duplicate_basenames(tmp_path, recursive):
    source = tmp_path / "logs"
    _source(source, "same.csv")
    _source(source, "nested/same.csv", "0,4.5,25\n")
    (source / "notes.txt").write_text("not a measurement")
    out = tmp_path / "results"
    summary = analyze_directory(source, out, service=_service(cell_max_v=4.2), recursive=recursive)
    names = ["nested/same.csv", "same.csv"] if recursive else ["same.csv"]
    assert [item["source"] for item in summary["files"]] == names
    assert (out / "files/nested/same.csv/report.html").exists() is recursive
    assert (out / "files/same.csv/report.html").is_file()


@pytest.mark.parametrize("name", ["summary.csv", "summary.csv/run.csv", "files/summary.csv"])
def test_source_names_cannot_collide_with_batch_outputs(tmp_path, name):
    source = tmp_path / "logs"
    measurement = _source(source, name)
    before = measurement.read_bytes()
    out = tmp_path / "results"
    summary = analyze_directory(source, out, service=_service(cell_max_v=4.2), recursive=True)
    item = summary["files"][0]
    assert item["source"] == name
    assert item["status"] == "PASS"
    assert item["result_json"] == f"files/{name}/result.json"
    assert item["report_html"] == f"files/{name}/report.html"
    result = json.loads((out / item["result_json"]).read_text())
    assert result["rows_input"] == 1
    assert result["max_cell_voltage_v"] == 3.5
    assert (out / item["report_html"]).is_file()
    assert _csv(out)[0]["source"] == name
    assert _csv(out)[0]["status"] == "PASS"
    assert measurement.read_bytes() == before


def test_missing_optional_backend_does_not_stop_csv_analysis(tmp_path, monkeypatch):
    from batterylog.loaders import mf4 as mf4_module

    source = tmp_path / "logs"
    source.mkdir()
    (source / "a.mf4").write_bytes(b"missing optional backend")
    _source(source, "b.csv")

    def unavailable():
        raise ImportError("Install the mf4 extra")

    monkeypatch.setattr(mf4_module, "_load_asammdf", unavailable)
    summary = analyze_directory(source, tmp_path / "results", service=_service(cell_max_v=4.2))
    assert [item["status"] for item in summary["files"]] == ["ERROR", "PASS"]
    assert "mf4 extra" in summary["files"][0]["error"]


@pytest.mark.parametrize("scenario", ["missing", "file", "empty", "unsupported"])
def test_bad_input_is_rejected_before_output_creation(tmp_path, scenario):
    source = tmp_path / "logs"
    if scenario == "file":
        source.write_text("not a directory")
    elif scenario != "missing":
        source.mkdir()
        if scenario == "unsupported":
            (source / "notes.txt").write_text("not a measurement")
    out = tmp_path / "results"
    with pytest.raises(ValueError):
        analyze_directory(source, out, service=_service())
    assert not out.exists()


@pytest.mark.parametrize("kind", ["same", "child", "existing", "ancestor"])
def test_output_guards_preserve_inputs_and_previous_results(tmp_path, kind):
    source = tmp_path / "logs"
    log = _source(source, "input.csv")
    before = log.read_bytes()
    out = {
        "same": source,
        "child": source / "results",
        "existing": tmp_path / "old-results",
        "ancestor": tmp_path,
    }[kind]
    if kind == "existing":
        out.mkdir()
        (out / "keep.txt").write_text("previous output")
    with pytest.raises(ValueError):
        analyze_directory(source, out, service=_service())
    assert log.read_bytes() == before
    if kind == "existing":
        assert (out / "keep.txt").read_text() == "previous output"


@pytest.mark.parametrize("writer_name", ["write_json_result", "write_html_report"])
@pytest.mark.parametrize("error_type", [OSError, ValueError])
def test_failed_report_pair_is_not_published_and_later_files_continue(
    tmp_path, monkeypatch, writer_name, error_type
):
    source = tmp_path / "logs"
    _source(source, "a.csv")
    _source(source, "b.csv")
    out = tmp_path / "results"
    original = getattr(batch_module, writer_name)
    calls = 0

    def fail_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error_type("simulated report failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(batch_module, writer_name, fail_first)
    summary = analyze_directory(source, out, service=_service(cell_max_v=4.2))
    assert [item["status"] for item in summary["files"]] == ["ERROR", "PASS"]
    assert not (out / "files/a.csv").exists()
    assert (out / "files/b.csv/result.json").is_file()
    assert (out / "files/b.csv/report.html").is_file()
    assert not list(out.rglob(".batterylog-*"))


def test_source_change_prevents_publishing_report_pair(tmp_path, monkeypatch):
    source = tmp_path / "logs"
    changed = _source(source, "a.csv")
    _source(source, "b.csv")
    original = batch_module.write_html_report
    calls = 0

    def change_source(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 1:
            changed.write_text(HEADER + "0,4.5,25\n")
        return result

    monkeypatch.setattr(batch_module, "write_html_report", change_source)
    out = tmp_path / "results"
    summary = analyze_directory(source, out, service=_service(cell_max_v=4.2))
    assert [item["status"] for item in summary["files"]] == ["ERROR", "PASS"]
    assert "changed during analysis" in summary["files"][0]["error"]
    assert not (out / "files/a.csv").exists()


def test_interrupt_keeps_completed_reports_and_explicit_pending_rows(tmp_path, monkeypatch):
    source = tmp_path / "logs"
    for name in ("a.csv", "b.csv", "c.csv"):
        _source(source, name)
    original = batch_module.write_html_report
    calls = 0

    def interrupt_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return original(*args, **kwargs)

    monkeypatch.setattr(batch_module, "write_html_report", interrupt_second)
    out = tmp_path / "results"
    with pytest.raises(KeyboardInterrupt):
        analyze_directory(source, out, service=_service(cell_max_v=4.2))
    assert [row["status"] for row in _csv(out)] == ["PASS", "NOT_PROCESSED", "NOT_PROCESSED"]
    assert (out / "files/a.csv/result.json").is_file()
    assert (out / "files/a.csv/report.html").is_file()
    assert not (out / "files/b.csv").exists()
    assert not (out / "files/c.csv").exists()
    assert not list(out.rglob(".batterylog-*"))


def test_excluded_data_and_no_rules_keep_authoritative_status(tmp_path):
    source = tmp_path / "logs"
    _source(source, "a.csv", "0,bad,25\n1,3.5,25\n")
    _source(source, "b.csv")
    service = AnalysisService(
        ValidationConfig(data_quality=DataQualityConfig("exclude_invalid_rows"))
    )
    summary = analyze_directory(source, tmp_path / "results", service=service)
    assert [item["status"] for item in summary["files"]] == ["FAIL", "NOT_EVALUATED"]
    assert summary["files"][0]["rows_excluded"] == 1
    assert summary["files"][0]["data_quality_events"] == 1
    assert summary["files"][0]["violation_events"] == 0


@pytest.mark.parametrize(
    "rows,limits,expected",
    [
        ("0,3.5,25\n", [], 3),
        ("0,3.5,25\n", ["--cell-max-v", "4.2"], 0),
        ("0,4.5,25\n", ["--cell-max-v", "4.2"], 1),
        ("0,bad,25\n", ["--cell-max-v", "4.2"], 4),
    ],
)
def test_batch_cli_exit_codes_and_json_envelope(tmp_path, capsys, rows, limits, expected):
    source = tmp_path / "logs"
    _source(source, "a.csv", rows)
    out = tmp_path / "results"
    code = run([str(source), "--batch", "--output-dir", str(out), *limits])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == expected
    assert captured.err == ""
    assert payload["batch_schema_version"] == 1
    assert len(payload["files"]) == 1
    assert (
        payload["files"][0]["status"]
        == {0: "PASS", 1: "FAIL", 3: "NOT_EVALUATED", 4: "ERROR"}[code]
    )
    assert (out / payload["summary_csv"]).is_file()


def test_batch_cli_error_precedence_and_one_captured_config(tmp_path, capsys, monkeypatch):
    import batterylog.__main__ as cli

    source = tmp_path / "logs"
    _source(source, "a.csv", "0,bad,25\n")
    _source(source, "b.csv", "0,4.5,25\n")
    _source(source, "c.csv")
    config = tmp_path / "config.yaml"
    config.write_text("schema_version: 6\nlimits:\n  cell_voltage:\n    max_v: 4.2\n")
    original = cli.capture_file_snapshot
    original_bytes = config.read_bytes()
    captures = []

    def capture_then_change(path):
        captures.append(path)
        snapshot = original(path)
        config.write_text("schema_version: 6\nlimits:\n  cell_voltage:\n    max_v: 9.0\n")
        return snapshot

    monkeypatch.setattr(cli, "capture_file_snapshot", capture_then_change)
    out = tmp_path / "results"
    code = run([str(source), "--batch", "--output-dir", str(out), "--config", str(config)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 4
    assert len(captures) == 1
    assert [item["status"] for item in payload["files"]] == ["ERROR", "FAIL", "PASS"]
    expected_hash = hashlib.sha256(original_bytes).hexdigest()
    assert payload["config_sha256"] == expected_hash
    for item in payload["files"][1:]:
        assert expected_hash in (out / item["report_html"]).read_text()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--batch"],
        ["--recursive"],
        ["--output-dir", "results"],
        ["--batch", "--output-dir", "results", "--report", "report.html"],
        ["--batch", "--output-dir", "results", "--json-out", "result.json"],
    ],
)
def test_batch_cli_rejects_ambiguous_options_without_writes(tmp_path, capsys, arguments):
    source = tmp_path / "logs"
    _source(source, "input.csv")
    assert run([str(source), *arguments]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


def test_unicode_and_csv_quotes_round_trip(tmp_path):
    source = tmp_path / "logs"
    name = "ölçüm,🚙.csv"
    _source(source, name)
    out = tmp_path / "results"
    summary = analyze_directory(source, out, service=_service(cell_max_v=4.2))
    assert summary["files"][0]["source"] == name
    assert _csv(out)[0]["source"] == name
    assert (out / summary["files"][0]["report_html"]).is_file()


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_csv_keeps_text_cells_inert_and_json_keeps_exact_paths(tmp_path, prefix):
    source = tmp_path / "logs"
    name = prefix + "measurement.csv"
    _source(source, name)
    out = tmp_path / "results"
    summary = analyze_directory(source, out, service=_service(cell_max_v=4.2))
    assert summary["files"][0]["source"] == name
    assert _csv(out)[0]["source"] == "'" + name
    assert (out / summary["files"][0]["report_html"]).is_file()


def test_summary_write_failure_preserves_reports_and_removes_partial_csv(tmp_path, monkeypatch):
    from contextlib import contextmanager

    source = tmp_path / "logs"
    _source(source, "a.csv")
    original = batch_module.NamedTemporaryFile

    @contextmanager
    def failing_temporary_file(**kwargs):
        with original(**kwargs) as handle:

            def fail_write(content):
                raise OSError("simulated summary failure")

            monkeypatch.setattr(handle, "write", fail_write)
            yield handle

    monkeypatch.setattr(batch_module, "NamedTemporaryFile", failing_temporary_file)
    out = tmp_path / "results"
    with pytest.raises(OSError, match="summary failure"):
        analyze_directory(source, out, service=_service(cell_max_v=4.2))
    assert (out / "files/a.csv/result.json").is_file()
    assert (out / "files/a.csv/report.html").is_file()
    assert not (out / "summary.csv").exists()
    assert not list(out.glob(".summary.*"))
