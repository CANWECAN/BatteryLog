import json
from urllib.parse import unquote

import pytest

from batterylog import AnalysisService, ValidationConfig, ValidationLimits
from batterylog.__main__ import run
from batterylog.recording_review import render_recording_review, review_recordings


def _inputs(tmp_path, voltage="3.7", name="run.csv", missing=False):
    source = tmp_path / "input"
    source.mkdir()
    if not missing:
        (source / name).write_text(
            f"timestamp_s,cell_1_v,temp_c\n0,{voltage},25\n1,{voltage},25\n2,{voltage},25\n",
            encoding="utf-8",
        )
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "recording_plan_schema_version": 1,
                "recordings": [
                    {
                        "id": "test-1",
                        "path": name,
                        "expected_channels": ["cell_1_v", "temp_c"],
                        "time": {
                            "column": "timestamp_s",
                            "unit": "s",
                            "start_s": "0",
                            "end_s": "2",
                            "max_gap_s": "1",
                            "boundary_tolerance_s": "0",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return source, plan, tmp_path / "output"


def _service():
    return AnalysisService(ValidationConfig(limits=ValidationLimits(cell_max_v=4.2)))


@pytest.mark.parametrize("voltage,engineering", [("3.7", "PASS"), ("4.3", "FAIL")])
def test_html_and_json_keep_coverage_and_engineering_independent(tmp_path, voltage, engineering):
    source, plan, target = _inputs(tmp_path, voltage=voltage)
    before = (source / "run.csv").read_bytes()
    result = review_recordings(source, target, plan=plan, service=_service())
    assert result["audit"]["coverage_status"] == "COMPLETE"
    assert result["engineering_status"] == engineering
    assert json.loads((target / "review.json").read_text()) == result
    html = (target / "review.html").read_text()
    assert "Recording coverage: <strong>COMPLETE" in html
    assert f"Engineering: <strong>{engineering}" in html
    assert result["audit"]["plan_sha256"] in html
    file_result = result["recordings"][0]
    assert file_result["recording"]["source_sha256"] == file_result["engineering"]["source_sha256"]
    analysis = json.loads((target / "files/run.csv/result.json").read_text())
    assert analysis["validation_status"] == engineering
    assert "recording_audit_schema_version" not in analysis
    assert (target / "files/run.csv/report.html").is_file()
    assert (source / "run.csv").read_bytes() == before


def test_empty_input_can_report_missing_expected_recording(tmp_path):
    source, plan, target = _inputs(tmp_path, missing=True)
    result = review_recordings(source, target, plan=plan, service=_service())
    assert result["audit"]["coverage_status"] == "INCOMPLETE"
    assert result["engineering_status"] == "NOT_EVALUATED"
    assert result["recordings"][0]["engineering"] is None
    assert (target / "review.html").is_file()


def test_coverage_only_and_undeclared_plan_remain_explicit(tmp_path):
    source, plan, target = _inputs(tmp_path)
    result = review_recordings(source, target, plan=plan)
    assert result["audit"]["coverage_status"] == "COMPLETE"
    assert result["engineering_requested"] is False
    assert result["engineering_status"] == "NOT_EVALUATED"
    absent = review_recordings(source, tmp_path / "without-plan")
    assert absent["audit"]["coverage_status"] == "NOT_EVALUATED"


def test_html_escapes_plan_labels_and_encodes_real_file_links(tmp_path):
    from html.parser import HTMLParser

    source, plan, target = _inputs(tmp_path, name="capture #1.csv")
    data = json.loads(plan.read_text())
    data["recordings"][0]["id"] = '<script>alert("x")</script>'
    plan.write_text(json.dumps(data))
    result = review_recordings(source, target, plan=plan, service=_service())
    html = render_recording_review(result)
    assert '<script>alert("x")</script>' not in html
    assert "&lt;script&gt;" in html
    links = []

    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                links.extend(value for key, value in attrs if key == "href")

    Links().feed(html)
    assert "files/capture%20%231.csv/report.html" in links
    assert all((target / unquote(link)).is_file() for link in links)


@pytest.mark.parametrize("failure", ["interrupt", "render", "source", "plan", "mismatch"])
def test_failed_or_cancelled_review_publishes_no_partial_success(tmp_path, monkeypatch, failure):
    import batterylog.recording_review as module

    source, plan, target = _inputs(tmp_path)
    original_render = module.render_recording_review
    analyze = module._analyze_file

    def replaced_analyze(*args, **kwargs):
        if failure == "interrupt":
            raise KeyboardInterrupt
        result = analyze(*args, **kwargs)
        if failure == "mismatch":
            result["source_sha256"] = "0" * 64
        return result

    def replaced_render(result):
        if failure == "render":
            raise OSError("render write failed")
        if failure == "source":
            with (source / "run.csv").open("a") as handle:
                handle.write("3,3.7,25\n")
        if failure == "plan":
            plan.write_text(plan.read_text() + " ")
        return original_render(result)

    monkeypatch.setattr(module, "_analyze_file", replaced_analyze)
    monkeypatch.setattr(module, "render_recording_review", replaced_render)
    with pytest.raises((KeyboardInterrupt, OSError, ValueError)):
        review_recordings(source, target, plan=plan, service=_service())
    assert not target.exists()
    assert not list(tmp_path.glob(".batterylog-review-*"))


def test_engineering_error_is_retained_without_a_pass_report(tmp_path):
    source, plan, target = _inputs(tmp_path, voltage="broken")
    review = review_recordings(source, target, plan=plan, service=_service())
    assert review["audit"]["coverage_status"] == "INCOMPLETE"
    assert review["engineering_status"] == "ERROR"
    assert review["recordings"][0]["engineering"]["result_json"] is None
    assert not (target / "files/run.csv/result.json").exists()


def test_existing_output_and_input_subdirectory_are_not_overwritten(tmp_path):
    source, plan, target = _inputs(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        review_recordings(source, source / "output", plan=plan)
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep")
    with pytest.raises(ValueError, match="exists"):
        review_recordings(source, target, plan=plan)
    assert marker.read_text() == "keep"


@pytest.mark.parametrize(
    "voltage,missing,expected",
    [("3.7", False, 0), ("4.3", False, 1), ("3.7", True, 1), ("bad", False, 4)],
)
def test_cli_reports_exit_scope_and_evidence(tmp_path, capsys, voltage, missing, expected):
    source, plan, target = _inputs(tmp_path, voltage=voltage, missing=missing)
    code = run(
        [
            str(source),
            "--audit-recordings",
            str(plan),
            "--output-dir",
            str(target),
            "--cell-max-v",
            "4.2",
        ]
    )
    captured = capsys.readouterr()
    assert code == expected, captured.err
    assert captured.err == ""
    assert json.loads(captured.out)["recording_review_schema_version"] == 1


def test_cli_without_active_engineering_rules_returns_not_evaluated(tmp_path, capsys):
    source, plan, target = _inputs(tmp_path)
    assert run([str(source), "--audit-recordings", str(plan), "--output-dir", str(target)]) == 3
    assert json.loads(capsys.readouterr().out)["audit"]["coverage_status"] == "COMPLETE"


@pytest.mark.parametrize(
    "options",
    [[], ["--recursive"], ["--report", "r.html"], ["--batch"], ["--inspect"], ["--normalize"]],
)
def test_cli_invalid_combinations_do_not_create_outputs(tmp_path, capsys, options):
    source, plan, target = _inputs(tmp_path)
    args = [str(source), "--audit-recordings", str(plan)]
    if options:
        args += ["--output-dir", str(target), *options]
    assert run(args) == 2
    assert capsys.readouterr().out == ""
    assert not target.exists()
