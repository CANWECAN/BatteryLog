import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_release_version import check_release_version, release_tag_from_ref


@pytest.mark.parametrize(
    ("tag", "package", "citation"),
    [
        ("v0.7.1", "0.7.0", "0.7.0"),
        ("0.7.0", "0.7.0", "0.7.0"),
        ("v0.7.0", "0.7.0", "0.6.1"),
        ("v0.7.0.dev0", "0.7.0.dev0", "0.7.0.dev0"),
    ],
)
def test_release_rejects_inconsistent_or_development_versions(tag, package, citation):
    with pytest.raises(ValueError):
        check_release_version(tag, package, citation)


def test_release_accepts_matching_stable_version():
    check_release_version("v0.7.0", "0.7.0", "0.7.0")


@pytest.mark.parametrize("ref", ["refs/tags/v0.11.0", "refs/heads/release/v0.11.0"])
def test_explicit_release_ref_selects_the_same_tag(ref):
    assert release_tag_from_ref(ref) == "v0.11.0"


@pytest.mark.parametrize(
    "ref",
    ["refs/heads/main", "refs/heads/prepare/v0.11.0", "refs/pull/119/merge", "v0.11.0"],
)
def test_other_refs_cannot_request_publication(ref):
    with pytest.raises(ValueError, match="Release requires"):
        release_tag_from_ref(ref)


@pytest.mark.parametrize("prefix", ["refs/tags/", "refs/heads/release/"])
@pytest.mark.parametrize(("version", "prerelease"), [("0.11.0", "false"), ("0.11.0rc1", "true")])
def test_release_cli_exports_validated_tag_and_prerelease(tmp_path, prefix, version, prerelease):
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    (tmp_path / "CITATION.cff").write_text(f'version: "{version}"\n')
    output = tmp_path / "output.txt"
    script = Path(__file__).parents[1] / "scripts/check_release_version.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_REF": f"{prefix}v{version}", "GITHUB_OUTPUT": str(output)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert output.read_text() == f"release_tag=v{version}\nprerelease={prerelease}\n"


def test_release_cli_does_not_export_mismatched_branch_version(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.11.0"\n')
    (tmp_path / "CITATION.cff").write_text('version: "0.11.0"\n')
    output = tmp_path / "output.txt"
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "scripts/check_release_version.py")],
        cwd=tmp_path,
        env={
            **os.environ,
            "GITHUB_REF": "refs/heads/release/v0.12.0",
            "GITHUB_OUTPUT": str(output),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "versions must agree exactly" in completed.stderr
    assert not output.exists()
