"""Artifact-level checks retain source while excluding raw data and unsafe paths."""

import io
import tarfile
import zipfile

import pytest

from scripts.validation.check_distribution import main, scan_archive


def make_tar(path, names):
    with tarfile.open(path, "w:gz") as tar:
        for name in names:
            content = b"reproducible test content\n"
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return path


def make_wheel(path, names):
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "test content")
    return path


def test_core_sdist_passes_when_no_research_paths(tmp_path):
    file = make_tar(
        tmp_path / "batterylog-0.11.tar.gz",
        [
            "batterylog-0.11/batterylog/__init__.py",
            "batterylog-0.11/tests/test_core.py",
        ],
    )
    assert scan_archive(file) == []
    assert main([str(file)]) == 0


@pytest.mark.parametrize(
    "name",
    [
        "downloads/capture.log",
        "raw_data/cells.csv",
        "third_party_data/capture.csv",
        "batterylog_research/source.dbc",
        "docs/BUG_HUNT_INTERNAL.md",
        "docs/RESEARCH_ACCESS_TERMS_DRAFT.md",
    ],
)
def test_raw_external_or_internal_material_blocks_sdist(tmp_path, name):
    archive = make_tar(tmp_path / "batterylog-0.11.tar.gz", ["batterylog-0.11/" + name])
    assert scan_archive(archive) == ["batterylog-0.11/" + name]
    assert main([str(archive)]) == 1


def test_wheel_can_include_apache_experimental_package(tmp_path):
    file = make_wheel(
        tmp_path / "batterylog-0.11-py3-none-any.whl",
        ["batterylog/__init__.py", "batterylog_research/voltage_step_audit.py"],
    )
    assert scan_archive(file) == []
    assert main([str(file)]) == 0


def test_wheel_with_only_core_passes(tmp_path):
    file = make_wheel(
        tmp_path / "batterylog-0.11-py3-none-any.whl",
        ["batterylog/__init__.py", "batterylog-0.11.dist-info/WHEEL"],
    )
    assert scan_archive(file) == []


@pytest.mark.parametrize("filename", ["missing.tar.gz", "not-an-archive.txt"])
def test_missing_or_unsupported_artifact_fails_closed(tmp_path, filename):
    path = tmp_path / filename
    if filename.endswith(".txt"):
        path.write_text("not a built distribution")
    with pytest.raises(ValueError):
        scan_archive(path)
    assert main([str(path)]) == 1


def test_corrupt_tar_fails_closed(tmp_path):
    path = tmp_path / "bad.tar.gz"
    path.write_bytes(b"not gzip")
    with pytest.raises(ValueError):
        scan_archive(path)
    assert main([str(path)]) == 1
