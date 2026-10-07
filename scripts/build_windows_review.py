"""Build and verify an isolated Windows review folder without publishing a release."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path


def build_review(output_parent: Path) -> Path:
    if sys.platform != "win32":
        raise ValueError("Run this review builder with Windows Python.")
    output_parent = output_parent.expanduser().resolve(strict=True)
    if not output_parent.is_dir():
        raise ValueError("Choose an existing output folder.")
    source = Path(__file__).resolve().parents[1]
    version = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip():
        raise ValueError("Commit or restore tracked changes before building a review candidate.")
    review = Path(tempfile.mkdtemp(prefix=f"BatteryLog-{version}-review-", dir=output_parent))
    print(f"Review folder: {review}", flush=True)
    log_path = review / "build.log"
    with log_path.open("w", encoding="utf-8") as log:

        def run(command: list[str], *, expected: int = 0) -> None:
            log.write(f"\n{command!r}\n")
            log.flush()
            completed = subprocess.run(
                command, cwd=review, stdout=log, stderr=subprocess.STDOUT, check=False
            )
            if completed.returncode != expected:
                raise RuntimeError(
                    f"Command exited with {completed.returncode}, expected {expected}; see {log_path}"
                )

        artifacts = review / "artifacts"
        run([sys.executable, "-m", "build", "--outdir", str(artifacts), str(source)])
        wheel = next(artifacts.glob("*.whl"))
        sdist = next(artifacts.glob("*.tar.gz"))
        run([sys.executable, str(source / "scripts/check_sdist_test_fixtures.py"), str(sdist)])
        run([sys.executable, "-m", "twine", "check", "--strict", str(wheel), str(sdist)])
        venv.EnvBuilder(with_pip=True).create(review / "venv")
        python = review / "venv/Scripts/python.exe"
        run([str(python), "-m", "pip", "install", str(wheel), "jsonschema"])
        run([str(python), "-m", "pip", "check"])
        examples = review / "examples"
        examples.mkdir()
        for item in (source / "examples").iterdir():
            if item.is_file() and item.suffix in {".csv", ".yaml"}:
                shutil.copy2(item, examples / item.name)
        run(
            [
                str(python),
                str(source / "scripts/check_installed_package.py"),
                version,
                str(examples / "sample_battery_log.csv"),
            ]
        )
        run([str(python), "-m", "pip", "install", f"{wheel}[mf4]"])
        run([str(python), "-m", "pip", "check"])
        run([str(python), str(source / "scripts/check_installed_mf4_package.py"), version])
        run(
            [
                str(python),
                "-c",
                (
                    "import tkinter as tk; from batterylog.desktop_ui import DesktopWindow; "
                    "root=tk.Tk(); root.withdraw(); DesktopWindow(root); root.update(); root.destroy(); "
                    "print('Installed Tk window verified')"
                ),
            ]
        )
        results = review / "results/failure-models"
        results.mkdir(parents=True)
        run(
            [
                str(python),
                "-m",
                "batterylog",
                str(examples / "failure_models_demo.csv"),
                "--config",
                str(examples / "failure_models.example.yaml"),
                "--report",
                str(results / "report.html"),
                "--json-out",
                str(results / "result.json"),
            ],
            expected=1,
        )
        result = json.loads((results / "result.json").read_text(encoding="utf-8"))
        if (
            result["schema_version"] != 9
            or result["validation_status"] != "FAIL"
            or len(result["violations"]) != 1
            or len(result["failure_models"]["evaluations"]) != 5
            or sum(len(item["events"]) for item in result["failure_models"]["evaluations"]) != 5
        ):
            raise RuntimeError(f"Unexpected model demo result; see {results}")
        # Verify the sdist in a second fresh environment, leaving the wheel environment ready to use.
        venv.EnvBuilder(with_pip=True).create(review / "sdist-verify")
        sdist_python = review / "sdist-verify/Scripts/python.exe"
        run([str(sdist_python), "-m", "pip", "install", str(sdist), "jsonschema"])
        run([str(sdist_python), "-m", "pip", "check"])
        run(
            [
                str(sdist_python),
                str(source / "scripts/check_installed_package.py"),
                version,
                str(examples / "sample_battery_log.csv"),
            ]
        )
        run([str(sdist_python), "-m", "pip", "install", f"{sdist}[mf4]"])
        run([str(sdist_python), "-m", "pip", "check"])
        run([str(sdist_python), str(source / "scripts/check_installed_mf4_package.py"), version])
    (artifacts / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(item.read_bytes()).hexdigest()}  {item.name}\n"
            for item in sorted([wheel, sdist])
        ),
        encoding="ascii",
    )
    (review / "Start-BatteryLog.cmd").write_text(
        '@echo off\ncd /d "%~dp0"\n"%~dp0venv\\Scripts\\batterylog-gui.exe"\n'
        "if errorlevel 1 pause\n",
        encoding="ascii",
    )
    (review / "README.md").write_text(
        f"# BatteryLog {version} review build\n\nSource commit: `{commit}`.\n\n"
        "Double-click **Start-BatteryLog.cmd** to open the installed desktop launcher. "
        "Keep the folder at its current location because the Python environments contain absolute paths.\n\n"
        "Use **Try demo...** for the five-sample basic example. To exercise the new models, "
        "select `examples/failure_models_demo.csv` and `examples/failure_models.example.yaml`, "
        "then select an existing output folder and Run analysis. The synthetic model example "
        "produces FAIL with six events; its completed report is already at "
        "`results/failure-models/report.html`, with JSON beside it.\n\n"
        "Both wheel and sdist passed strict metadata, fixture-corpus, fresh base and MF4 "
        "installation checks outside the source checkout. The installed desktop worker "
        "passed model-only PASS/FAIL/NOT_EVALUATED checks. Build diagnostics are in "
        "`build.log`; distributions and checksums are in `artifacts/`.\n\n"
        "This folder uses Windows Python and a local virtual environment. It is a development "
        "review build, not a standalone installer or a published release. The demo parameters "
        "are illustrative; the new models have no vehicle-data calibration in this build.\n",
        encoding="utf-8",
    )
    print(f"Verified review build: {review}", flush=True)
    return review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-parent", type=Path, required=True)
    args = parser.parse_args()
    build_review(args.output_parent)


if __name__ == "__main__":
    main()
