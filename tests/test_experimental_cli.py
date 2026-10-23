"""The installed-product interface preserves observation and source-clock contracts."""

import json
from pathlib import Path

import pytest

from batterylog.__main__ import run

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("workflow", [[], ["can"], ["precharge"], ["replay"]])
def test_experimental_help_is_available_from_root_command(workflow, capsys):
    assert run(["experimental", *workflow, "--help"]) == 0
    assert "batterylog experimental" in capsys.readouterr().out


@pytest.mark.parametrize("args", [[], ["unknown"], ["precharge"], ["replay"]])
def test_experimental_usage_errors_keep_exit_two(args):
    assert run(["experimental", *args]) == 2


def test_root_precharge_writes_observations_and_html(tmp_path):
    fixtures = ROOT / "batterylog_research/fixtures"
    output = tmp_path / "review"
    capture = fixtures / "precharge_aligned_example.csv"
    before = capture.read_bytes()
    assert (
        run(
            [
                "experimental",
                "precharge",
                "--csv",
                str(capture),
                "--context",
                str(fixtures / "precharge_aligned_example.context.json"),
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "OBSERVATIONS_RECORDED"
    assert manifest["workflow"] == "precharge"
    assert (output / "report.html").is_file() and (output / "index.html").is_file()
    assert capture.read_bytes() == before


def test_root_replay_preserves_exact_recorded_clock(tmp_path):
    capture = tmp_path / "capture.log"
    capture.write_text("(1700000000.000000001) can0 100#01\n(1700000000.000000002) can0 100#02\n")
    output = tmp_path / "replay"
    assert run(["experimental", "replay", str(capture), str(output), "--capacity", "1"]) == 0
    frames = [json.loads(line) for line in (output / "frames.jsonl").read_text().splitlines()]
    assert [row["timestamp_as_recorded"] for row in frames] == [
        "1700000000.000000001",
        "1700000000.000000002",
    ]
    assert json.loads((output / "session.json").read_text())["complete"] is True
