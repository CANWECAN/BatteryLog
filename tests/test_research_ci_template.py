"""BatteryLog CI must run its contract tests and publish only verified release tags."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


@pytest.fixture(params=["ci-templates/ci.yml", ".github/workflows/ci.yml"])
def workflow(request):
    template = ROOT / request.param
    return yaml.load(template.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_batterylog_template_preserves_verified_tag_release_controls(workflow):
    assert workflow["on"]["push"]["tags"] == ["v*"]
    release = workflow["jobs"]["release"]
    assert release["if"] == "startsWith(github.ref, 'refs/tags/v') && github.event_name == 'push'"
    assert set(release["needs"]) == {"gate", "package"}
    assert release["permissions"]["contents"] == "write"
    assert release["concurrency"]["cancel-in-progress"] == "false"
    script = release["steps"][-1]["run"]
    assert "sha256sum --check SHA256SUMS" in script
    assert "--verify-tag" in script
    assert "--prerelease --latest=false" in script
    package = workflow["jobs"]["package"]
    version = next(step for step in package["steps"] if step.get("id") == "version")
    assert version["if"] == "startsWith(github.ref, 'refs/tags/v')"
    assert version["run"] == "python scripts/check_release_version.py"
    assert package["outputs"]["prerelease"] == "${{ steps.version.outputs.prerelease }}"
    assert workflow["permissions"]["contents"] == "read"


def test_batterylog_template_tests_working_and_review_branches(workflow):
    watched = workflow["on"]["push"]["branches"]
    assert set(watched) == {"main"}
    assert "pull_request" in workflow["on"]
    assert {
        "plan",
        "test",
        "minimum-runtime",
        "windows",
        "mf4",
        "package",
        "gate",
        "release",
    } == set(workflow["jobs"])
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["jobs"]["plan"]["steps"][-1]["run"].endswith("plan --full")
    assert "paths-ignore" not in workflow["on"]["pull_request"]


def test_batterylog_template_checks_built_artifacts_before_upload(workflow):
    steps = workflow["jobs"]["package"]["steps"]
    runs = [step.get("run", "") for step in steps]
    build = next(i for i, run in enumerate(runs) if run == "python -m build")
    scan = next(
        i for i, run in enumerate(runs) if "scripts/validation/check_distribution.py" in run
    )
    upload = next(
        i
        for i, step in enumerate(steps)
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert build < scan < upload
    assert "dist/*.tar.gz" in runs[scan]
    assert "dist/*.whl" in runs[scan]


def test_full_suites_install_research_can_and_verification_backends(workflow):
    for name in ["test", "minimum-runtime", "windows"]:
        installs = " ".join(step.get("run", "") for step in workflow["jobs"][name]["steps"])
        assert "-r batterylog_research/requirements-can.txt" in installs
        assert "types-PyYAML" in installs
        assert "setuptools" in installs
    assert workflow["concurrency"]["cancel-in-progress"] == "true"


def test_active_workflow_matches_reviewed_template():
    load = lambda p: yaml.load((ROOT / p).read_text(), Loader=yaml.BaseLoader)
    assert load("ci-templates/ci.yml") == load(".github/workflows/ci.yml")


def test_unified_artifact_audit_precedes_installation_and_addon_is_retired(workflow):
    steps = workflow["jobs"]["package"]["steps"]
    runs = [step.get("run", "") for step in steps]
    audit = next(
        i for i, run in enumerate(runs) if "check_experimental_package.py --artifacts" in run
    )
    install = next(i for i, run in enumerate(runs) if "check_installed_package.py" in run)
    assert audit < install
    assert any("${artifact}[mf4,can]" in run for run in runs)
    assert any('check_experimental_package.py" --installed' in run for run in runs)
    assert not any("build_candidate.py" in run or "dist/research" in run for run in runs)


def test_gate_runs_after_all_selected_jobs_and_reads_results_without_shell_expansion(workflow):
    gate = workflow["jobs"]["gate"]
    assert gate["if"] == "${{ !cancelled() }}"
    assert set(gate["needs"]) == set(workflow["jobs"]) - {"gate", "release"}
    assert gate["steps"][-1]["env"]["CI_NEEDS_JSON"] == "${{ toJSON(needs) }}"
    assert gate["steps"][-1]["run"].endswith("ci_policy.py gate")
    plan = workflow["jobs"]["plan"]
    assert plan["steps"][0]["with"]["fetch-depth"] == "0"
    for job, flag in (
        ("test", "tests"),
        ("minimum-runtime", "full"),
        ("windows", "windows"),
        ("mf4", "mf4"),
        ("package", "package"),
    ):
        selected = workflow["jobs"][job]
        assert selected["needs"] == "plan"
        assert selected["if"] == f"needs.plan.outputs.{flag} == 'true'"
