"""Validate explicit tag or release-branch requests against distribution metadata."""

import os
import tomllib
from pathlib import Path

import yaml
from packaging.version import Version


def release_tag_from_ref(ref: str) -> str:
    for prefix in ("refs/tags/v", "refs/heads/release/v"):
        if ref.startswith(prefix):
            return "v" + ref.removeprefix(prefix)
    raise ValueError("Release requires a v* tag or release/v* branch")


def check_release_version(tag: str, package_version: str, citation_version: str) -> None:
    if tag != f"v{package_version}" or citation_version != package_version:
        raise ValueError("Tag, pyproject.toml and CITATION.cff versions must agree exactly")
    if Version(package_version).is_devrelease:
        raise ValueError("Development versions cannot be released")


if __name__ == "__main__":
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    citation = yaml.safe_load(Path("CITATION.cff").read_text(encoding="utf-8"))
    tag = release_tag_from_ref(os.environ["GITHUB_REF"])
    check_release_version(tag, project["project"]["version"], citation["version"])
    if output_path := os.environ.get("GITHUB_OUTPUT"):
        prerelease = Version(project["project"]["version"]).is_prerelease
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(f"release_tag={tag}\n")
            output.write(f"prerelease={str(prerelease).lower()}\n")
