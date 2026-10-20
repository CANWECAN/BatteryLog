"""Unified source distributions retain experimental code and its tests."""

from __future__ import annotations

import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def package_fixture(tmp_path: Path) -> Path:
    """Minimal package with precisely the repository's controlled manifest."""
    root = Path(__file__).parents[1]
    manifest = root / "MANIFEST.in"
    if not manifest.exists():
        pytest.fail("Unified packaging must declare an explicit MANIFEST.in")
    project = tmp_path / "package"
    (project / "batterylog").mkdir(parents=True)
    (project / "batterylog_research").mkdir()
    (project / "tests").mkdir()
    (project / "docs").mkdir()
    (project / "batterylog" / "__init__.py").write_text("# Apache Core\n")
    (project / "batterylog_research" / "__init__.py").write_text("# Apache experimental package\n")
    (project / "batterylog_research" / "unpublished.py").write_text(
        "# Authored experimental source\n"
    )
    (project / "tests" / "test_research_secret.py").write_text("# Research-specific test\n")
    (project / "tests" / "test_temperature_triage.py").write_text("# Research-only triage\n")
    (project / "tests" / "test_core.py").write_text("# Core regression\n")
    (project / "docs" / "RESEARCH_PRIVATE.md").write_text("Private review\n")
    (project / "docs" / "BUG_HUNT_INTERNAL.md").write_text("Private audit\n")
    (project / "docs" / "REFERENCE.md").write_text("Core reference\n")
    (project / "README.md").write_text("# Synthetic packaging test\n")
    (project / "LICENSE").write_text("Apache-2.0 placeholder\n")
    (project / "NOTICE").write_text("Notice placeholder\n")
    (project / "MANIFEST.in").write_bytes(manifest.read_bytes())
    (project / "pyproject.toml").write_text("""[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"
[project]
name = "batterylog"
version = "0.11.0.dev0"
readme = "README.md"
license = "Apache-2.0"
license-files = ["LICENSE", "NOTICE"]
requires-python = ">=3.11"
[tool.setuptools.packages.find]
include = ["batterylog", "batterylog.*", "batterylog_research"]
""")
    (project / "dist").mkdir()
    return project


def test_unified_sdist_includes_experimental_code_and_tests(package_fixture: Path):
    pytest.importorskip("setuptools")
    script = "import setuptools.build_meta as backend; backend.build_sdist('dist')"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=package_fixture,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    archives = list((package_fixture / "dist").glob("*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0], "r:gz") as archive:
        members = [member.name.split("/", 1)[-1] for member in archive if member.isfile()]
    assert "batterylog/__init__.py" in members
    assert "tests/test_core.py" in members
    assert "MANIFEST.in" in members
    assert "docs/REFERENCE.md" in members
    assert "docs/RESEARCH_PRIVATE.md" in members
    assert "docs/BUG_HUNT_INTERNAL.md" not in members
    assert "batterylog_research/unpublished.py" in members
    assert "tests/test_research_secret.py" in members
    assert "tests/test_temperature_triage.py" in members


def test_manifest_excludes_internal_notes_and_raw_external_files():
    manifest = (Path(__file__).parents[1] / "MANIFEST.in").read_text()
    assert "exclude docs/BUG_HUNT_*.md" in manifest
    assert "global-exclude *.dbc *.log" in manifest
    assert "exclude docs/RESEARCH_ACCESS_TERMS_DRAFT.md" in manifest


def test_source_manifest_retains_experimental_regression_material(package_fixture: Path):
    """Pin the original reproduction: the old manifest included private tests/docs."""
    pytest.importorskip("setuptools")
    (package_fixture / "MANIFEST.in").write_text(
        "recursive-include docs *.md *.png *.json\nrecursive-include tests *.py *.json *.md\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", "import setuptools.build_meta as b; b.build_sdist('dist')"],
        cwd=package_fixture,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    archive = next((package_fixture / "dist").glob("*.tar.gz"))
    with tarfile.open(archive, "r:gz") as tar:
        names = [member.name.split("/", 1)[-1] for member in tar if member.isfile()]
    assert "tests/test_research_secret.py" in names
    assert "tests/test_temperature_triage.py" in names
    assert "docs/RESEARCH_PRIVATE.md" in names
    assert "docs/BUG_HUNT_INTERNAL.md" in names
