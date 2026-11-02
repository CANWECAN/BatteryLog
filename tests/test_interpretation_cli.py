import json
import subprocess
import sys

import pytest

from batterylog.__main__ import run

DATA = b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.8,3.6,25\n1,3.8,3.6,25\n"


def invoke(*args):
    return subprocess.run(
        [sys.executable, "-m", "batterylog", *(str(arg) for arg in args)],
        capture_output=True,
        text=True,
        check=False,
        timeout=40,
    )


@pytest.mark.parametrize(
    "limit,status,exit_code", [(None, "NOT_EVALUATED", 3), ("0.5", "PASS", 0), ("0.05", "FAIL", 1)]
)
@pytest.mark.parametrize("with_context", [False, True])
def test_real_cli_preserves_stdout_and_engineering_exit_codes(
    tmp_path, limit, status, exit_code, with_context
):
    source = tmp_path / "sample.csv"
    source.write_bytes(DATA)
    args = [source] + (["--imbalance-limit-v", limit] if limit is not None else [])
    legacy = invoke(*args)
    target = tmp_path / "review"
    options = ["--interpret", "--output-dir", target]
    if with_context:
        context = tmp_path / "context.json"
        context.write_text('{"measurement_context_schema_version":1,"chemistry":"LFP"}')
        options += ["--measurement-context", context]
    completed = invoke(*args, *options)
    assert legacy.returncode == completed.returncode == exit_code
    assert legacy.stdout == completed.stdout
    assert json.loads(completed.stdout)["validation_status"] == status
    assert "Physical interpretation: NOT_EVALUATED" in completed.stderr
    assert (target / "result.json").read_text() == completed.stdout
    payload = json.loads((target / "interpretation.json").read_text())
    assert payload["engineering_status"] == status
    assert payload["physical_interpretation_status"] == "NOT_EVALUATED"
    assert payload["diagnostic_claim"] is False
    if with_context:
        assert (target / "context.json").read_bytes() == context.read_bytes()


@pytest.mark.parametrize(
    "error",
    [
        "missing_context",
        "invalid_context",
        "existing_target",
        "parent_is_file",
        "bad_source",
        "bad_config",
    ],
)
def test_real_cli_error_has_no_result_stdout_or_partial_bundle(tmp_path, error):
    source = tmp_path / "sample.csv"
    source.write_bytes(DATA)
    target = tmp_path / "review"
    options = []
    if error in {"missing_context", "invalid_context"}:
        context = tmp_path / "context.json"
        if error == "invalid_context":
            context.write_text('{"measurement_context_schema_version":999}')
        options += ["--measurement-context", context]
    elif error == "existing_target":
        target.mkdir()
        (target / "keep").write_text("original")
    elif error == "parent_is_file":
        parent = tmp_path / "file"
        parent.write_text("original")
        target = parent / "review"
    elif error == "bad_source":
        source.write_text("timestamp_s,temp_c\n0,25\n")
    else:
        config = tmp_path / "config.yaml"
        config.write_text("not: supported\n")
        options += ["--config", config]
    completed = invoke(source, "--interpret", "--output-dir", target, *options)
    assert completed.returncode == 4
    assert completed.stdout == ""
    assert "error:" in completed.stderr
    if error == "existing_target":
        assert (target / "keep").read_text() == "original"
        assert list(target.iterdir()) == [target / "keep"]
    else:
        assert not target.exists()
    assert not list(tmp_path.glob(".batterylog-interpret-*"))


@pytest.mark.parametrize(
    "options",
    [
        ["--interpret"],
        ["--measurement-context", "context.json"],
        ["--interpret", "--output-dir", "unused", "--report", "unused.html"],
        ["--interpret", "--output-dir", "unused", "--json-out", "unused.json"],
        ["--interpret", "--output-dir", "unused", "--recursive"],
        ["--interpret", "--batch", "--output-dir", "unused"],
        ["--interpret", "--inspect", "--output-dir", "unused"],
    ],
)
def test_cli_rejects_ambiguous_or_incomplete_opt_in_before_reading_source(capsys, options):
    assert run(["missing.csv", *options]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


def test_real_cli_keeps_yaml_overrides_and_records_actual_effective_settings(tmp_path):
    source = tmp_path / "sample.csv"
    source.write_bytes(DATA)
    config = tmp_path / "config.yaml"
    config.write_text("limits:\n  cell_voltage:\n    max_delta_v: 0.05\n")
    target = tmp_path / "review"
    completed = invoke(
        source,
        "--interpret",
        "--output-dir",
        target,
        "--config",
        config,
        "--imbalance-limit-v",
        "0.5",
    )
    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result["limits_applied"]["imbalance_max_v"] == 0.5
    settings = json.loads((target / "effective-config.json").read_text())
    assert settings["limits"]["imbalance_max_v"] == 0.5
