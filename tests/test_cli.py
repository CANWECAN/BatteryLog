import json
import os
import sys
from pathlib import Path

import pytest

from batterylog.__main__ import main, run

SAMPLE = Path(__file__).parents[1] / "examples" / "sample_battery_log.csv"


def test_cli_fail_emits_json_and_returns_exit_1(capsys) -> None:
    exit_code = run(
        [
            str(SAMPLE),
            "--imbalance-limit-v",
            "0.08",
            "--temp-max-c",
            "45",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["schema_version"] == 1
    assert payload["validation_status"] == "FAIL"
    assert payload["rules_evaluated"] == [
        "CELL_IMBALANCE_HIGH",
        "TEMPERATURE_HIGH",
    ]
    assert payload["max_delta_v"] == 0.1
    assert payload["violations"][0]["code"] == "CELL_IMBALANCE_HIGH"


def test_cli_pass_returns_exit_0(capsys) -> None:
    exit_code = run(
        [
            str(SAMPLE),
            "--imbalance-limit-v",
            "0.11",
            "--temp-warning-c",
            "50",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["validation_status"] == "PASS"
    assert payload["violations"] == []


def test_cli_without_limits_returns_not_evaluated_exit_3(capsys) -> None:
    exit_code = run([str(SAMPLE)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert payload["validation_status"] == "NOT_EVALUATED"
    assert payload["rules_evaluated"] == []
    assert payload["violations"] == []


def test_cli_reports_validation_errors_as_exit_2(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "timestamp_s,temp_c,current_a\n0,25,0\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        run([str(bad)])

    assert exc.value.code == 2
    assert "No cell voltage columns" in capsys.readouterr().err


def test_cli_loads_yaml_config_and_cli_overrides_it(tmp_path, capsys) -> None:
    config = tmp_path / "validation.yaml"
    config.write_text(
        "limits:\n  cell_voltage:\n    max_delta_v: null\n  temperature:\n    max_c: 40\n",
        encoding="utf-8",
    )

    exit_code = run(
        [
            str(SAMPLE),
            "--config",
            str(config),
            "--temp-max-c",
            "50",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["validation_status"] == "PASS"
    assert payload["rules_evaluated"] == ["TEMPERATURE_HIGH"]
    assert payload["limits_applied"]["temperature_max_c"] == 50.0


def test_cli_reports_config_errors_as_exit_2(tmp_path, capsys) -> None:
    config = tmp_path / "bad.yaml"
    config.write_text(
        "limits:\n  cell_voltage:\n    max_v: wrong\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        run([str(SAMPLE), "--config", str(config)])

    assert exc.value.code == 2
    assert "must be a number" in capsys.readouterr().err


def test_cli_writes_html_report_and_preserves_fail_exit_code(
    tmp_path,
    capsys,
) -> None:
    report = tmp_path / "report.html"

    exit_code = run(
        [
            str(SAMPLE),
            "--imbalance-limit-v",
            "0.08",
            "--temp-max-c",
            "45",
            "--report",
            str(report),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["validation_status"] == "FAIL"
    assert report.exists()

    html = report.read_text(encoding="utf-8")
    assert "Battery Validation Report" in html
    assert "<strong>FAIL</strong>" in html
    assert SAMPLE.name in html
    assert "Source SHA-256" in html
    assert "Not provided" in html


def test_cli_report_contains_config_provenance(tmp_path, capsys) -> None:
    config = tmp_path / "validation.yaml"
    config.write_text(
        "limits:\n  cell_voltage:\n    max_delta_v: 0.11\n  temperature:\n    max_c: 50\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.html"

    exit_code = run(
        [
            str(SAMPLE),
            "--config",
            str(config),
            "--report",
            str(report),
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    html = report.read_text(encoding="utf-8")
    assert config.name in html
    assert "Config SHA-256" in html
    assert "Result schema" in html


def test_cli_refuses_to_overwrite_input_with_report(tmp_path, capsys) -> None:
    source = tmp_path / "input.csv"
    original = SAMPLE.read_text(encoding="utf-8")
    source.write_text(original, encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        run([str(source), "--report", str(source)])

    assert exc.value.code == 2
    assert "must not overwrite the input log" in capsys.readouterr().err
    assert source.read_text(encoding="utf-8") == original


def test_cli_refuses_to_overwrite_config_with_report(tmp_path, capsys) -> None:
    config = tmp_path / "validation.yaml"
    original = "limits:\n  temperature:\n    max_c: 50\n"
    config.write_text(original, encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        run(
            [
                str(SAMPLE),
                "--config",
                str(config),
                "--report",
                str(config),
            ]
        )

    assert exc.value.code == 2
    assert "must not overwrite the validation config" in capsys.readouterr().err
    assert config.read_text(encoding="utf-8") == original


def test_main_propagates_run_exit_code(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "batterylog",
            str(SAMPLE),
            "--imbalance-limit-v",
            "0.11",
            "--temp-max-c",
            "50",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0


def test_cli_refuses_hardlink_alias_of_input_as_report(tmp_path, capsys) -> None:
    source = tmp_path / "input.csv"
    source.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    alias = tmp_path / "report.html"
    os.link(source, alias)

    with pytest.raises(SystemExit) as exc:
        run([str(source), "--report", str(alias)])

    assert exc.value.code == 2
    assert "must not overwrite the input log" in capsys.readouterr().err
    assert source.read_text(encoding="utf-8").startswith("timestamp_s,")
