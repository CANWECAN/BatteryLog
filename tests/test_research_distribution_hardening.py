"""Bounded archive-path regressions for the Research release preflight."""

import io
import stat
import tarfile
import zipfile

import pytest

from scripts.validation.check_distribution import scan_archive


def make_tar(path, names, *, symlink=None):
    with tarfile.open(path, "w:gz") as archive:
        for name in names:
            payload = b"source"
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        if symlink:
            member = tarfile.TarInfo(symlink)
            member.type = tarfile.SYMTYPE
            member.linkname = "batterylog_research/secret.py"
            archive.addfile(member)
    return path


def make_wheel(path, names, *, symlink=None):
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "source")
        if symlink:
            item = zipfile.ZipInfo(symlink)
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, "batterylog_research/secret.py")
    return path


@pytest.mark.parametrize(
    "name",
    [
        "batterylog-0.11/raw_data/capture.csv",
        "batterylog-0.11/x/y/downloads/capture.log",
        "batterylog-0.11/docs/BUG_HUNT_2026_10_08.md",
        "batterylog-0.11/foo/docs/RESEARCH_ACCESS_TERMS_DRAFT.md",
        "batterylog-0.11/../secret.py",
        "/batterylog-0.11/batterylog/core.py",
        "batterylog-0.11\\batterylog_research\\secret.py",
        "C:/batterylog/core.py",
    ],
)
def test_sdist_excluded_or_unsafe_path_flagged(tmp_path, name):
    file = make_tar(tmp_path / "test.tar.gz", [name])
    assert scan_archive(file)


def test_sdist_benign_core_module_allowed(tmp_path):
    file = make_tar(tmp_path / "test.tar.gz", ["batterylog-0.11/batterylog/core.py"])
    assert scan_archive(file) == []


@pytest.mark.parametrize(
    "name",
    [
        "batterylog_research/raw.DBC",
        "batterylog-0.11.data/purelib/raw_data/trace.csv",
        "foo/docs/BUG_HUNT_INTERNAL.md",
        "foo/docs/RESEARCH_ACCESS_TERMS_DRAFT.md",
        "../batterylog_research/secret.py",
    ],
)
def test_wheel_excluded_or_unsafe_path_flagged(tmp_path, name):
    file = make_wheel(tmp_path / "test.whl", [name])
    assert scan_archive(file)


def test_sdist_symlink_is_rejected(tmp_path):
    file = make_tar(
        tmp_path / "test.tar.gz",
        ["batterylog-0.11/batterylog/__init__.py"],
        symlink="batterylog-0.11/batterylog/shadow.py",
    )
    assert any("Unsupported" in p for p in scan_archive(file))


def test_wheel_symlink_is_rejected(tmp_path):
    file = make_wheel(
        tmp_path / "test.whl", ["batterylog/__init__.py"], symlink="batterylog/shadow.py"
    )
    assert scan_archive(file) == ["batterylog/shadow.py"]


def test_benign_wheel_allowed(tmp_path):
    file = make_wheel(tmp_path / "test.whl", ["batterylog/__init__.py"])
    assert scan_archive(file) == []
