"""The unified sdist must retain both established and experimental tests."""

import io
import tarfile
from pathlib import Path

import pytest

from scripts import check_sdist_test_fixtures as checker


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sources: dict[str, bytes]) -> Path:
    root = tmp_path / "checkout"
    tests = root / "tests"
    tests.mkdir(parents=True)
    for path, data in sources.items():
        target = tests / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    monkeypatch.setattr(checker, "__file__", str(root / "scripts/check_sdist_test_fixtures.py"))
    return tests


def _archive(tmp_path: Path, members: dict[str, bytes]) -> Path:
    result = tmp_path / "batterylog.tar.gz"
    with tarfile.open(result, "w:gz") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo("batterylog-0.11/" + name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return result


def test_missing_experimental_test_blocks_distribution(tmp_path, monkeypatch):
    _setup(
        tmp_path,
        monkeypatch,
        {
            "test_core.py": b"core",
            "golden/out.json": b"evidence",
            "test_research_voltage_steps.py": b"private",
            "test_temperature_triage.py": b"private",
        },
    )
    archive = _archive(
        tmp_path,
        {
            "tests/test_core.py": b"core",
            "tests/golden/out.json": b"evidence",
        },
    )
    with pytest.raises(ValueError, match="omits test corpus file"):
        checker.check_sdist_test_fixtures(archive)


def test_missing_regular_core_test_still_blocks_distribution(tmp_path, monkeypatch):
    _setup(
        tmp_path,
        monkeypatch,
        {
            "test_core.py": b"core",
            "test_research_demo.py": b"private",
        },
    )
    with pytest.raises(ValueError, match="omits test corpus file"):
        checker.check_sdist_test_fixtures(_archive(tmp_path, {"README.md": b"x"}))


def test_experimental_tests_are_part_of_the_required_corpus(tmp_path, monkeypatch):
    _setup(
        tmp_path,
        monkeypatch,
        {
            "test_research_demo.py": b"private",
            "test_temperature_triage.py": b"private",
        },
    )
    archive = _archive(
        tmp_path,
        {
            "tests/test_research_demo.py": b"private",
            "tests/test_temperature_triage.py": b"private",
        },
    )
    checker.check_sdist_test_fixtures(archive)


def test_nested_test_named_research_is_not_silently_exempted(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"golden/test_research_example.py": b"nested fixture"})
    with pytest.raises(ValueError, match="omits test corpus file"):
        checker.check_sdist_test_fixtures(_archive(tmp_path, {"README.md": b"x"}))
