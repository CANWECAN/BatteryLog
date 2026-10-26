"""Verify unified package contents and exercise installed experimental workflows."""

from __future__ import annotations

import argparse
import configparser
import csv
import hashlib
import io
import json
import stat
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from importlib import metadata, resources, util
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ("precharge_aligned_example.csv", "precharge_aligned_example.context.json")
PROFILES = ("can_model3_profile.json", "can_model3_multiplex_profile.json")
THIRD_PARTY_NOTICE = "batterylog_research/third_party_model3dbc_NOTICE.txt"


def _members(artifact: Path) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            entries = [item for item in archive.infolist() if not item.is_dir()]
            for item in entries:
                if stat.S_IFMT(item.external_attr >> 16) == stat.S_IFLNK:
                    raise ValueError("Symlink in wheel")
                if item.filename in members:
                    raise ValueError("Duplicate wheel member")
                members[item.filename] = archive.read(item)
    else:
        with tarfile.open(artifact) as archive:
            roots = {item.name.split("/", 1)[0] for item in archive}
            if len(roots) != 1:
                raise ValueError("Source distribution must have one root")
            for item in archive:
                if item.isdir():
                    continue
                if not item.isfile():
                    raise ValueError("Special source-distribution member")
                name = item.name.split("/", 1)[-1]
                if name in members:
                    raise ValueError("Duplicate source-distribution member")
                stream = archive.extractfile(item)
                if stream is None:
                    raise ValueError("Unreadable source-distribution member")
                members[name] = stream.read()
    for name in members:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("Unsafe archive member")
    return members


def audit(artifact: Path) -> dict:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    version = project["version"]
    files = _members(artifact)
    wheel = artifact.suffix == ".whl"
    info = f"batterylog-{version}.dist-info"
    metadata_name = f"{info}/METADATA" if wheel else "PKG-INFO"
    msg = BytesParser().parsebytes(files[metadata_name])
    if (msg["Name"], msg["Version"], msg["License-Expression"]) != (
        "batterylog",
        version,
        "Apache-2.0",
    ):
        raise ValueError("Wrong unified distribution identity or license")
    if set(msg.get_all("License-File", [])) != {"LICENSE", "NOTICE", THIRD_PARTY_NOTICE}:
        raise ValueError("Missing unified license/third-party notice metadata")
    requirements = msg.get_all("Requires-Dist", [])
    if any(req.startswith(("batterylog==", "batterylog-research")) for req in requirements):
        raise ValueError("Separate companion dependency remains")
    if "can" not in msg.get_all("Provides-Extra", []):
        raise ValueError("Missing CAN extra")
    for name in ("LICENSE", "NOTICE", THIRD_PARTY_NOTICE):
        archive_name = f"{info}/licenses/{name}" if wheel else name
        if files.get(archive_name) != (ROOT / name).read_bytes():
            raise ValueError(f"License/notice bytes differ: {name}")
    required = []
    for package in ("batterylog", "batterylog_research"):
        sources = (
            (ROOT / package).rglob("*.py")
            if package == "batterylog"
            else (ROOT / package).glob("*.py")
        )
        required.extend(p for p in sources if "__pycache__" not in p.parts)
    required.extend((ROOT / "batterylog/schema").glob("*.json"))
    required.extend(ROOT / "batterylog_research/fixtures" / name for name in FIXTURES)
    required.extend(ROOT / "batterylog_research" / name for name in PROFILES)
    required.append(ROOT / THIRD_PARTY_NOTICE)
    if not wheel:
        required.append(ROOT / "examples/recording_plan.json")
    for source in required:
        name = source.relative_to(ROOT).as_posix()
        if files.get(name) != source.read_bytes():
            raise ValueError(f"Unified package omitted or changed source/resource: {name}")
    if wheel:
        entry_points = configparser.ConfigParser()
        entry_points.read_string(files[f"{info}/entry_points.txt"].decode())
        if dict(entry_points["console_scripts"]) != project["scripts"]:
            raise ValueError("Unexpected console-script contract")
        research = {name for name in files if name.startswith("batterylog_research/")}
        expected = {
            p.relative_to(ROOT).as_posix()
            for p in required
            if p.relative_to(ROOT).parts[0] == "batterylog_research"
        }
        if research != expected:
            raise ValueError("Unexpected experimental wheel payload")
    return {
        "artifact": artifact.name,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "verified_source_resources": len(required),
    }


def installed() -> dict:
    distribution = metadata.distribution("batterylog")
    if distribution.metadata["License-Expression"] != "Apache-2.0":
        raise ValueError("Installed package license differs")
    try:
        metadata.distribution("batterylog-research")
    except metadata.PackageNotFoundError:
        pass
    else:
        raise ValueError("Separate Research add-on is still installed")
    package = resources.files("batterylog_research")
    for name in PROFILES:
        json.loads(package.joinpath(name).read_text(encoding="utf-8"))
    if "Josh Wardell" not in package.joinpath("third_party_model3dbc_NOTICE.txt").read_text():
        raise ValueError("Installed third-party notice missing")
    scripts = Path(sysconfig.get_path("scripts"))
    command = scripts / ("batterylog.exe" if sys.platform == "win32" else "batterylog")

    def run(*args):
        return subprocess.run(
            [str(command), "experimental", *map(str, args)],
            check=True,
            capture_output=True,
            text=True,
        )

    with tempfile.TemporaryDirectory(prefix="batterylog-installed-") as tmp:
        work = Path(tmp)
        capture, context = work / "example.csv", work / "context.json"
        capture.write_bytes(package.joinpath("fixtures", FIXTURES[0]).read_bytes())
        context.write_bytes(package.joinpath("fixtures", FIXTURES[1]).read_bytes())
        run("precharge", "--csv", capture, "--context", context, "--output-dir", work / "precharge")
        review = json.loads((work / "precharge/review.json").read_text())
        if review["scope"] != "aligned_file_observations_only":
            raise ValueError("Unexpected precharge scope")
        if not all(
            (work / "precharge" / name).is_file()
            for name in ("index.html", "report.html", "manifest.json")
        ):
            raise ValueError("Installed precharge HTML/operator output missing")
        source = work / "example.log"
        source.write_text(
            "(1674587734.000000001) can0 100#AC0D3C\n(1674587734.000000002) can0 100#DE0D3D\n",
            encoding="utf-8",
        )
        run("replay", source, work / "replay", "--capacity", "1")
        session = json.loads((work / "replay/session.json").read_text())
        records = [
            json.loads(line) for line in (work / "replay/frames.jsonl").read_text().splitlines()
        ]
        if not session["complete"] or session["written_frames"] != 2:
            raise ValueError("Installed replay did not complete")
        if [row["timestamp_as_recorded"] for row in records] != [
            "1674587734.000000001",
            "1674587734.000000002",
        ]:
            raise ValueError("Installed replay lost source time")
        can_available = util.find_spec("cantools") is not None
        if can_available:
            dbc = work / "example.dbc"
            dbc.write_text(
                'VERSION ""\nNS_ :\nBS_:\nBU_: Test\nBO_ 256 Brick: 3 Test\n'
                ' SG_ V : 0|16@1+ (0.001,0) [0|65.535] "V" Test\n'
                ' SG_ T : 16|8@1+ (1,-40) [-40|215] "C" Test\n',
                encoding="utf-8",
            )
            profile = {
                "bus": "can0",
                "dbc_sha256": hashlib.sha256(dbc.read_bytes()).hexdigest(),
                "anchor": {
                    "frame_id": 256,
                    "extended": False,
                    "multiplexer_signal": None,
                    "multiplexer_value": None,
                },
                "signals": [
                    {
                        "column": column,
                        "frame_id": 256,
                        "extended": False,
                        "signal": signal,
                        "max_age_s": 0,
                    }
                    for column, signal in (("cell_1_v", "V"), ("temp_1_c", "T"))
                ],
            }
            spec, config = work / "profile.json", work / "limits.yaml"
            spec.write_text(json.dumps(profile), encoding="utf-8")
            config.write_text("limits:\n  cell_voltage:\n    max_v: 4.2\n", encoding="utf-8")
            run(
                "can",
                "--log",
                source,
                "--dbc",
                dbc,
                "--profile",
                spec,
                "--config",
                config,
                "--output-dir",
                work / "can",
            )
            result = json.loads((work / "can/result.json").read_text())
            rows = list(csv.reader(io.StringIO((work / "can/prepared/canonical.csv").read_text())))
            if result["validation_status"] != "PASS" or len(rows) != 3:
                raise ValueError("Installed CAN workflow failed")
            if [float(value) for value in rows[1]] != [0.0, 3.5, 20.0]:
                raise ValueError("Installed CAN bytes disagree with authored reference")
            if not (work / "can/report.html").is_file():
                raise ValueError("Installed CAN report missing")
    return {
        "installed": str(distribution.locate_file("")),
        "version": distribution.version,
        "workflows": 3 if can_available else 2,
        "can_verified": can_available,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--artifacts", type=Path)
    group.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    if args.installed:
        result = installed()
    else:
        artifacts = sorted(args.artifacts.glob("*.whl")) + sorted(args.artifacts.glob("*.tar.gz"))
        if len(artifacts) != 2:
            raise ValueError("Require exactly one unified wheel and one source distribution")
        result = [audit(path) for path in artifacts]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
