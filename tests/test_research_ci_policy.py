"""BatteryLog CI must select conservatively and never mask a selected test failure."""

import json
import subprocess
import sys

import pytest

from batterylog_research.ci_policy import JOB_FLAGS, check_gate, event_plan, selection


@pytest.mark.parametrize(
    ("paths", "profile", "risks"),
    [
        (["CURRENT_STATE.md", "docs/RESEARCH_CAN.md"], "docs", set()),
        (["docs/design.rst"], "docs", set()),
        (["batterylog_research/can_prepare.py"], "fast", {"windows", "package"}),
        (["tests/test_research_can_prepare.py"], "fast", set()),
        (["tests/test_desktop_ui.py"], "fast", {"windows"}),
        (["tests/test_mf4_loader.py"], "fast", {"mf4"}),
        (["tests/test_research_distribution_boundary.py"], "fast", {"package"}),
        (["batterylog_research/packaging/README.md"], "fast", {"package"}),
        (["scripts/check_installed_package.py"], "fast", {"package"}),
        (["README.md"], "fast", {"package"}),
        (["batterylog/analysis/core.py"], "fast", {"windows", "mf4", "package"}),
        (["batterylog/schema/result.schema.json"], "fast", {"windows", "mf4", "package"}),
        ([".github/workflows/ci.yml"], "full", {"windows", "mf4", "package"}),
        (["ci-templates/ci.yml"], "full", {"windows", "mf4", "package"}),
        (["batterylog_research/ci_policy.py"], "full", {"windows", "mf4", "package"}),
        (["tests/test_research_ci_policy.py"], "full", {"windows", "mf4", "package"}),
        (["pyproject.toml"], "full", {"windows", "mf4", "package"}),
        (["batterylog_research/requirements-can.txt"], "full", {"windows", "mf4", "package"}),
        (["tests/fixtures/new.csv"], "full", {"windows", "mf4", "package"}),
        (["unknown-file"], "full", {"windows", "mf4", "package"}),
        (["docs/evidence/new.json"], "full", {"windows", "mf4", "package"}),
        (["docs/../batterylog/analysis/core.py"], "full", {"windows", "mf4", "package"}),
        (["docs\\hidden.md"], "full", {"windows", "mf4", "package"}),
        ([], "full", {"windows", "mf4", "package"}),
    ],
)
def test_selection_examples(paths, profile, risks):
    plan = selection(paths)
    assert plan["profile"] == profile
    assert {key for key in ("windows", "mf4", "package") if plan[key] == "true"} == risks
    assert plan["tests"] == ("false" if profile == "docs" else "true")
    versions = json.loads(plan["python_matrix"])["python-version"]
    assert versions == (["3.11", "3.12", "3.13", "3.14"] if profile == "full" else ["3.13"])
    assert len(json.loads(plan["mf4_matrix"])["include"]) == (5 if profile == "full" else 2)


def statuses(plan):
    return {
        "plan": {"result": "success", "outputs": plan},
        **{
            job: {"result": "success" if plan[flag] == "true" else "skipped"}
            for job, flag in JOB_FLAGS.items()
        },
    }


@pytest.mark.parametrize(
    "paths",
    [
        ["docs/a.md"],
        ["batterylog_research/can_prepare.py"],
        ["batterylog/analysis/core.py"],
        ["pyproject.toml"],
    ],
)
def test_gate_accepts_only_the_complete_selected_result_set(paths):
    plan = selection(paths)
    assert check_gate(statuses(plan)) == plan["profile"]


@pytest.mark.parametrize("job", ["plan", *JOB_FLAGS])
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", ""])
def test_gate_rejects_every_missing_or_failed_required_job(job, result):
    data = statuses(selection([], force_full=True))
    data[job]["result"] = result
    with pytest.raises(ValueError):
        check_gate(data)


@pytest.mark.parametrize(
    "change",
    [
        "missing_job",
        "missing_output",
        "true_bool",
        "fake_docs",
        "fake_full",
        "fake_fast",
        "unexpected_job",
        "extra_run",
    ],
)
def test_invalid_plans_and_unexpected_execution_do_not_pass(change):
    data = statuses(selection(["docs/a.md"]))
    output = data["plan"]["outputs"]
    if change == "missing_job":
        data.pop("test")
    elif change == "missing_output":
        output.pop("tests")
    elif change == "true_bool":
        output["tests"] = False
    elif change == "fake_docs":
        output["tests"] = "true"
    elif change == "fake_full":
        output["profile"] = "full"
    elif change == "fake_fast":
        output["profile"] = "fast"
    elif change == "unexpected_job":
        data["unknown"] = {"result": "success"}
    elif change == "extra_run":
        data["test"]["result"] = "success"
    with pytest.raises(ValueError):
        check_gate(data)


def test_docs_cannot_downgrade_a_mixed_or_forced_change():
    assert selection(["docs/readme.md", "batterylog/analysis/core.py"])["mf4"] == "true"
    assert selection(["docs/readme.md"], force_full=True)["full"] == "true"


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_full_events_do_not_need_a_pull_request_or_changed_file_listing(event):
    assert event_plan(event, {})["full"] == "true"


def test_unknown_event_is_an_error():
    with pytest.raises(ValueError, match="Unsupported"):
        event_plan("release", {})


def test_git_diff_sees_renamed_deleted_code_and_handles_newline_paths(tmp_path):
    def git(*args):
        return subprocess.check_output(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.name=CI Test",
                "-c",
                "user.email=ci@example.invalid",
                *args,
            ],
            text=True,
        ).strip()

    git("init", "--initial-branch=main")
    (tmp_path / "batterylog_research").mkdir()
    (tmp_path / "batterylog_research/signal.py").write_text("original code\n")
    git("add", ".")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "docs").mkdir()
    git("mv", "batterylog_research/signal.py", "docs/prose.md")
    # Windows prohibits newline names; the binary NUL parser is checked separately below.
    git("commit", "-m", "rename")
    event = {
        "pull_request": {
            "base": {"sha": base},
            "head": {"sha": git("rev-parse", "HEAD")},
            "labels": [],
        }
    }
    assert event_plan("pull_request", event, root=tmp_path)["tests"] == "true"
    event["pull_request"]["labels"] = [{"name": "ci:full"}]
    assert event_plan("pull_request", event, root=tmp_path)["full"] == "true"
    event["pull_request"]["head"]["sha"] = "HEAD; anything"
    with pytest.raises(ValueError, match="commit identities"):
        event_plan("pull_request", event, root=tmp_path)


def test_null_delimited_diff_is_not_a_line_based_or_shell_interpolation(monkeypatch):
    from batterylog_research import ci_policy

    seen = []

    def diff(command):
        seen.extend(command)
        return b"docs/newline\nname.md\x00batterylog/analysis/core.py\x00"

    monkeypatch.setattr(ci_policy.subprocess, "check_output", diff)
    event = {"pull_request": {"base": {"sha": "a" * 40}, "head": {"sha": "b" * 40}}}
    assert event_plan("pull_request", event)["mf4"] == "true"
    assert "--no-renames" in seen and "-z" in seen
    event["pull_request"]["labels"] = False
    with pytest.raises(TypeError, match="labels"):
        event_plan("pull_request", event)


def test_real_gate_cli_exits_nonzero_on_skipped_selected_job(tmp_path):
    import os

    from batterylog_research import ci_policy

    data = statuses(selection([], force_full=True))
    data["mf4"]["result"] = "skipped"
    env = {**os.environ, "CI_NEEDS_JSON": json.dumps(data)}
    result = subprocess.run(
        [sys.executable, ci_policy.__file__, "gate"],
        env=env,
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "mf4 result" in result.stderr


def test_real_plan_cli_writes_action_outputs(tmp_path):
    import os

    from batterylog_research import ci_policy

    event = tmp_path / "event.json"
    event.write_text("{}", encoding="utf-8")
    output = tmp_path / "outputs.txt"
    result = subprocess.run(
        [sys.executable, ci_policy.__file__, "plan"],
        env={
            **os.environ,
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_OUTPUT": str(output),
        },
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    actual = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert actual["profile"] == "full"
    assert actual["tests"] == "true" and actual["full"] == "true"
    assert len(json.loads(actual["mf4_matrix"])["include"]) == 5


def test_forced_full_preserves_public_required_checks_for_documentation(monkeypatch):
    from batterylog_research import ci_policy

    monkeypatch.setattr(ci_policy.subprocess, "check_output", lambda _: b"docs/guide.md\x00")
    event = {"pull_request": {"base": {"sha": "a" * 40}, "head": {"sha": "b" * 40}}}
    assert event_plan("pull_request", event)["profile"] == "docs"
    plan = event_plan("pull_request", event, force_full=True)
    assert plan["profile"] == "full"
    assert json.loads(plan["python_matrix"])["python-version"] == ["3.11", "3.12", "3.13", "3.14"]
    assert plan["windows"] == "true"
