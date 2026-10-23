# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""BatteryLog CI selection and fail-closed result gate (stdlib only)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

JOB_FLAGS = {
    "test": "tests",
    "minimum-runtime": "full",
    "windows": "windows",
    "mf4": "mf4",
    "package": "package",
}
PYTHONS = ["3.11", "3.12", "3.13", "3.14"]
MF4_FULL = [{"os": "ubuntu-24.04", "python-version": v} for v in PYTHONS] + [
    {"os": "windows-latest", "python-version": "3.13"}
]
MF4_RISK = [
    {"os": os_name, "python-version": "3.13"} for os_name in ("ubuntu-24.04", "windows-latest")
]


def selection(paths, *, force_full=False):
    """Unknown paths select Full; only explicitly harmless prose can skip tests."""
    flags = dict.fromkeys(("tests", "full", "windows", "mf4", "package"), False)
    full = force_full or not paths
    for name in paths:
        path = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != name
        ):
            full = True
            continue
        if (
            name.startswith((".github/", "ci-templates/"))
            or name
            in {
                "batterylog_research/ci_policy.py",
                "tests/test_research_ci_policy.py",
                "tests/test_research_ci_template.py",
                "pyproject.toml",
                "MANIFEST.in",
                "setup.py",
                "setup.cfg",
                "uv.lock",
                "poetry.lock",
                ".python-version",
            }
            or path.name.startswith("requirements")
            and path.suffix == ".txt"
        ):
            full = True
        elif name == "CURRENT_STATE.md" or (
            name.startswith("docs/") and path.suffix in {".md", ".rst"}
        ):
            continue
        elif name.startswith("batterylog/"):
            flags.update(tests=True, windows=True, mf4=True, package=True)
        elif name.startswith("batterylog_research/"):
            flags["tests"] = True
            flags["package"] = True
            flags["windows"] |= path.suffix == ".py"
        elif name.startswith("tests/"):
            flags["tests"] = True
            flags["windows"] |= path.name.startswith("test_desktop")
            flags["mf4"] |= "mf4" in path.name
            flags["package"] |= any(
                word in path.name for word in ("distribution", "sdist", "installed", "package")
            )
            full |= name.startswith("tests/fixtures/")
        elif name.startswith(("scripts/", "examples/")) or name in {
            "README.md",
            "LICENSE",
            "NOTICE",
            "RESEARCH_LICENSE.md",
            "RESEARCH_BOUNDARY.md",
        }:
            flags.update(tests=True, package=True)
        else:
            full = True
    if full:
        flags = dict.fromkeys(flags, True)
    profile = "full" if full else "fast" if flags["tests"] else "docs"
    return {
        **{key: str(value).lower() for key, value in flags.items()},
        "profile": profile,
        "python_matrix": json.dumps({"python-version": PYTHONS if full else ["3.13"]}),
        "mf4_matrix": json.dumps({"include": MF4_FULL if full else MF4_RISK}),
    }


def event_plan(event_name, event, *, root=".", force_full=False):
    if event_name in {"push", "workflow_dispatch"}:
        return selection([], force_full=True)
    if event_name != "pull_request":
        raise ValueError("Unsupported CI event")
    request = event["pull_request"]
    base, head = request["base"]["sha"], request["head"]["sha"]
    if not all(isinstance(sha, str) and re.fullmatch("[0-9a-f]{40}", sha) for sha in (base, head)):
        raise ValueError("Invalid PR commit identities")
    raw = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            f"{base}...{head}",
            "--",
        ]
    )
    paths = raw.decode("utf-8", errors="surrogateescape").split("\0")
    paths = [name for name in paths if name]
    labels = request.get("labels", [])
    if not isinstance(labels, list):
        raise TypeError("Invalid PR labels")
    force = force_full or any(label["name"] == "ci:full" for label in labels)
    return selection(paths, force_full=force)


def check_gate(needs):
    """A failed planner, skipped required job or missing result can never pass."""
    if set(needs) != {"plan", *JOB_FLAGS} or needs["plan"]["result"] != "success":
        raise ValueError("CI planning or dependency results are incomplete")
    outputs = needs["plan"]["outputs"]
    expected = {flag for flag in JOB_FLAGS.values()}
    if any(outputs.get(flag) not in {"true", "false"} for flag in expected):
        raise ValueError("Invalid CI selection outputs")
    if outputs.get("profile") not in {"docs", "fast", "full"}:
        raise ValueError("Missing CI profile")
    profile = outputs["profile"]
    if (
        profile == "full"
        and any(outputs[flag] != "true" for flag in expected)
        or profile == "docs"
        and any(outputs[flag] != "false" for flag in expected)
        or profile == "fast"
        and (outputs["tests"] != "true" or outputs["full"] != "false")
    ):
        raise ValueError("Inconsistent CI profile selection")
    for job, flag in JOB_FLAGS.items():
        wanted = "success" if outputs[flag] == "true" else "skipped"
        if needs[job]["result"] != wanted:
            raise ValueError(f"{job} result {needs[job]['result']!r}; required {wanted!r}")
    return outputs["profile"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "gate"])
    parser.add_argument("--full", action="store_true", help="Run every supported verification job")
    args = parser.parse_args()
    if args.command == "gate":
        profile = check_gate(json.loads(os.environ["CI_NEEDS_JSON"]))
        print(f"BatteryLog CI gate passed: {profile}")
        return
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    result = event_plan(os.environ["GITHUB_EVENT_NAME"], event, force_full=args.full)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8", newline="\n") as output:
        output.writelines(f"{key}={value}\n" for key, value in result.items())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
