"""Unified archives must bind Core, experimental resources and license notices."""

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import check_experimental_package as checker


@pytest.fixture
def package(tmp_path, monkeypatch):
    root = tmp_path / "source"
    source = {
        "batterylog/__init__.py": b"# core\n",
        "batterylog_research/__init__.py": b"# experimental\n",
        "batterylog_research/operator.py": b"# operator\n",
        "LICENSE": b"Apache-2.0 test license\n",
        "NOTICE": b"BatteryLog copyright\n",
        "examples/recording_plan.json": b"{}\n",
        checker.THIRD_PARTY_NOTICE: b"MIT notice\n",
        **{f"batterylog_research/fixtures/{name}": b"authored" for name in checker.FIXTURES},
        **{f"batterylog_research/{name}": b"{}" for name in checker.PROFILES},
    }
    for name, content in source.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "pyproject.toml").write_text(
        '[project]\nversion="0.11.0.dev0"\n[project.scripts]\nbatterylog="batterylog.__main__:main"\n'
    )
    monkeypatch.setattr(checker, "ROOT", root)
    metadata = (
        "Name: batterylog\nVersion: 0.11.0.dev0\nLicense-Expression: Apache-2.0\n"
        "License-File: LICENSE\nLicense-File: NOTICE\n"
        f"License-File: {checker.THIRD_PARTY_NOTICE}\nProvides-Extra: can\n\n"
    ).encode()
    return source, metadata


def _archive(tmp_path, source, metadata, wheel):
    if wheel:
        info = "batterylog-0.11.0.dev0.dist-info"
        files = {name: data for name, data in source.items() if name.startswith("batterylog")}
        for name in ("LICENSE", "NOTICE", checker.THIRD_PARTY_NOTICE):
            files[f"{info}/licenses/{name}"] = source[name]
        files[f"{info}/METADATA"] = metadata
        files[f"{info}/entry_points.txt"] = (
            b"[console_scripts]\nbatterylog = batterylog.__main__:main\n"
        )
        path = tmp_path / "batterylog-0.11.0.dev0-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
    else:
        path = tmp_path / "batterylog-0.11.0.dev0.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, content in {**source, "PKG-INFO": metadata}.items():
                member = tarfile.TarInfo("batterylog-0.11.0.dev0/" + name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
    return path


@pytest.mark.parametrize("wheel", [True, False])
def test_one_distribution_contains_both_packages_and_notices(package, tmp_path, wheel):
    source, metadata = package
    result = checker.audit(_archive(tmp_path, source, metadata, wheel))
    assert len(result["sha256"]) == 64


@pytest.mark.parametrize("wheel", [True, False])
@pytest.mark.parametrize(
    "defect", ["license", "companion", "missing_operator", "mutated_fixture", "notice"]
)
def test_unified_artifact_rejects_wrong_rights_or_payload(package, tmp_path, wheel, defect):
    source, metadata = package
    source = source.copy()
    if defect == "license":
        metadata = metadata.replace(b"Apache-2.0", b"LicenseRef-BatteryLog-Research")
    elif defect == "companion":
        metadata = metadata.replace(b"\n\n", b"\nRequires-Dist: batterylog==0.11.0.dev0\n\n")
    elif defect == "missing_operator":
        source.pop("batterylog_research/operator.py")
    elif defect == "mutated_fixture":
        source[f"batterylog_research/fixtures/{checker.FIXTURES[0]}"] = b"changed"
    else:
        metadata = metadata.replace(b"License-File: NOTICE\n", b"")
    with pytest.raises(ValueError):
        checker.audit(_archive(tmp_path, source, metadata, wheel))


def test_all_first_party_experimental_modules_declare_apache():
    root = Path(__file__).parents[1]
    for source in (root / "batterylog_research").glob("*.py"):
        text = source.read_text()
        assert "SPDX-License-Identifier: Apache-2.0" in text[:200], source
        assert "All rights reserved" not in text[:200], source


def test_sdist_rejects_missing_recording_plan_example(package, tmp_path):
    source, metadata = package
    source = source.copy()
    source.pop("examples/recording_plan.json")
    with pytest.raises(ValueError, match="examples/recording_plan.json"):
        checker.audit(_archive(tmp_path, source, metadata, False))
