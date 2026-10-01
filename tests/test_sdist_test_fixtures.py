import io
import tarfile
from pathlib import Path

import pytest

from scripts import check_sdist_test_fixtures as checker


def _archive(path: Path, entries: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def _reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    checkout = tmp_path / "checkout"
    tests = checkout / "tests"
    tests.mkdir(parents=True)
    monkeypatch.setattr(checker, "__file__", str(checkout / "scripts/check.py"))
    return tests


def test_verifier_rejects_missing_reference_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checker, "__file__", str(tmp_path / "missing/scripts/check.py"))
    archive = _archive(tmp_path / "sdist.tar.gz", {"batterylog/README.md": b"package"})
    with pytest.raises(ValueError, match="Reference test directory is missing"):
        checker.check_sdist_test_fixtures(archive)


def test_verifier_rejects_empty_reference_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tests = _reference(tmp_path, monkeypatch)
    (tests / "cache.pyc").write_bytes(b"ignored")
    archive = _archive(tmp_path / "sdist.tar.gz", {"batterylog/README.md": b"package"})
    with pytest.raises(ValueError, match="Reference test corpus is empty"):
        checker.check_sdist_test_fixtures(archive)


def test_verifier_accepts_nested_corpus_with_identical_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tests = _reference(tmp_path, monkeypatch)
    (tests / "golden").mkdir()
    entries = {
        "test_example.py": b"def test_example(): pass\n",
        "golden/example.json": b'{"value": 1}\n',
        "golden/README.md": b"Fixed expectations\n",
    }
    for name, data in entries.items():
        (tests / name).write_bytes(data)
    archive = _archive(
        tmp_path / "sdist.tar.gz",
        {f"batterylog/tests/{name}": data for name, data in entries.items()},
    )
    checker.check_sdist_test_fixtures(archive)


@pytest.mark.parametrize("packaged", [None, b'{"value": 2}\n'])
def test_verifier_rejects_omitted_or_changed_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, packaged: bytes | None
) -> None:
    tests = _reference(tmp_path, monkeypatch)
    (tests / "golden").mkdir()
    (tests / "golden/example.json").write_bytes(b'{"value": 1}\n')
    entries = {"batterylog/README.md": b"package"}
    if packaged is not None:
        entries["batterylog/tests/golden/example.json"] = packaged
    archive = _archive(tmp_path / "sdist.tar.gz", entries)
    message = "omits test corpus file" if packaged is None else "changed test corpus file"
    with pytest.raises(ValueError, match=message):
        checker.check_sdist_test_fixtures(archive)


def test_verifier_rejects_directory_in_place_of_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tests = _reference(tmp_path, monkeypatch)
    (tests / "test_example.py").write_bytes(b"expected")
    archive_path = tmp_path / "sdist.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("batterylog/tests/test_example.py")
        info.type = tarfile.DIRTYPE
        archive.addfile(info)
    with pytest.raises(ValueError, match="changed test corpus file"):
        checker.check_sdist_test_fixtures(archive_path)


@pytest.mark.parametrize("empty", [False, True])
def test_verifier_rejects_invalid_archive_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, empty: bool
) -> None:
    tests = _reference(tmp_path, monkeypatch)
    (tests / "test_example.py").write_bytes(b"expected")
    archive = _archive(
        tmp_path / "sdist.tar.gz",
        {}
        if empty
        else {
            "batterylog/tests/test_example.py": b"expected",
            "other/README.md": b"extra",
        },
    )
    with pytest.raises(ValueError, match="one top-level directory"):
        checker.check_sdist_test_fixtures(archive)
