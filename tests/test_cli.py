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


def test_cli_max_event_gap_overrides_yaml_and_splits_events(
    tmp_path,
    capsys,
) -> None:
    source = tmp_path / "sparse.csv"
    source.write_text(
        "timestamp_s,temp_c,cell_1_v,cell_2_v\n0.0,25,4.0,3.8\n0.4,25,4.0,3.8\n5.0,25,4.0,3.8\n",
        encoding="utf-8",
    )
    config = tmp_path / "validation.yaml"
    config.write_text(
        "limits:\n  cell_voltage:\n    max_delta_v: 0.08\nevent_detection:\n  max_gap_s: 10.0\n",
        encoding="utf-8",
    )

    exit_code = run(
        [
            str(source),
            "--config",
            str(config),
            "--max-event-gap-s",
            "0.5",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    imbalance_events = [
        event for event in payload["violations"] if event["code"] == "CELL_IMBALANCE_HIGH"
    ]

    assert exit_code == 1
    assert payload["analysis_options"] == {"max_event_gap_s": 0.5}
    assert len(imbalance_events) == 2


def test_cli_rejects_invalid_max_event_gap(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        run([str(SAMPLE), "--max-event-gap-s", "-0.1"])

    assert exc.value.code == 2
    assert "max_gap_s must be non-negative" in capsys.readouterr().err


def test_cli_applies_explicit_signal_mapping_from_yaml(tmp_path, capsys) -> None:
    source = tmp_path / "vendor.csv"
    source.write_text(
        "Time_s,BMS_CellVoltage_002,BMS_CellVoltage_001,"
        "BMS_CellVoltage_Max,T_Module_02,T_Module_01\n"
        "0.0,3.90,3.70,4.20,30,28\n",
        encoding="utf-8",
    )
    config = tmp_path / "validation.yaml"
    config.write_text(
        "limits:\n"
        "  cell_voltage:\n"
        "    max_delta_v: 0.08\n"
        "signals:\n"
        "  timestamp: Time_s\n"
        "  cell_voltage:\n"
        "    pattern: 'BMS_CellVoltage_(?P<index>\\d+)'\n"
        "  temperature:\n"
        "    pattern: 'T_Module_(?P<index>\\d+)'\n",
        encoding="utf-8",
    )

    exit_code = run([str(source), "--config", str(config)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["cells_detected"] == 2
    assert payload["temperature_sensors_detected"] == 2
    assert payload["signal_mapping"] == {
        "mode": "explicit",
        "timestamp_source": "Time_s",
        "cell_voltage_pattern": r"BMS_CellVoltage_(?P<index>\d+)",
        "temperature_pattern": r"T_Module_(?P<index>\d+)",
    }
    assert payload["max_cell_voltage_v"] == 3.9
    assert payload["violations"][0]["signals"] == ["cell_2_v", "cell_1_v"]


def test_cli_reports_mapping_errors_as_exit_2(tmp_path, capsys) -> None:
    source = tmp_path / "vendor.csv"
    source.write_text(
        "Time_s,OtherCell,T_Module_01\n0.0,3.8,25\n",
        encoding="utf-8",
    )
    config = tmp_path / "validation.yaml"
    config.write_text(
        "signals:\n"
        "  timestamp: Time_s\n"
        "  cell_voltage:\n"
        "    pattern: 'BMS_CellVoltage_(?P<index>\\d+)'\n"
        "  temperature:\n"
        "    pattern: 'T_Module_(?P<index>\\d+)'\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        run([str(source), "--config", str(config)])

    assert exc.value.code == 2
    assert "matched no cell-voltage columns" in capsys.readouterr().err


ALL_LIMITS_YAML = (
    "limits:\n"
    "  cell_voltage:\n"
    "    min_v: 3.6\n"
    "    max_v: 3.9\n"
    "    max_delta_v: 0.08\n"
    "  temperature:\n"
    "    min_c: 29\n"
    "    max_c: 45\n"
)


@pytest.mark.parametrize(
    ("disable_flag", "limit_field", "rule_code"),
    [
        ("--no-cell-min-v", "cell_min_v", "CELL_UNDERVOLTAGE"),
        ("--no-cell-max-v", "cell_max_v", "CELL_OVERVOLTAGE"),
        ("--no-imbalance-limit-v", "imbalance_max_v", "CELL_IMBALANCE_HIGH"),
        ("--no-temp-min-c", "temperature_min_c", "TEMPERATURE_LOW"),
        ("--no-temp-max-c", "temperature_max_c", "TEMPERATURE_HIGH"),
    ],
)
def test_cli_can_disable_each_yaml_rule(
    tmp_path,
    capsys,
    disable_flag: str,
    limit_field: str,
    rule_code: str,
) -> None:
    config = tmp_path / "validation.yaml"
    config.write_text(ALL_LIMITS_YAML, encoding="utf-8")

    exit_code = run(
        [
            str(SAMPLE),
            "--config",
            str(config),
            disable_flag,
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["limits_applied"][limit_field] is None
    assert rule_code not in payload["rules_evaluated"]
    assert len(payload["rules_evaluated"]) == 4


@pytest.mark.parametrize(
    ("numeric_args", "disable_flag"),
    [
        (["--cell-min-v", "3.5"], "--no-cell-min-v"),
        (["--cell-max-v", "4.2"], "--no-cell-max-v"),
        (["--imbalance-limit-v", "0.1"], "--no-imbalance-limit-v"),
        (["--temp-min-c", "-20"], "--no-temp-min-c"),
        (["--temp-max-c", "50"], "--no-temp-max-c"),
    ],
)
def test_cli_rejects_numeric_and_disable_override_for_same_rule(
    capsys,
    numeric_args: list[str],
    disable_flag: str,
) -> None:
    with pytest.raises(SystemExit) as exc:
        run([str(SAMPLE), *numeric_args, disable_flag])

    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_cli_no_temp_warning_alias_disables_yaml_temperature_max(
    tmp_path,
    capsys,
) -> None:
    config = tmp_path / "validation.yaml"
    config.write_text(
        "limits:\n  temperature:\n    max_c: 45\n",
        encoding="utf-8",
    )

    exit_code = run(
        [
            str(SAMPLE),
            "--config",
            str(config),
            "--no-temp-warning-c",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert payload["validation_status"] == "NOT_EVALUATED"
    assert payload["limits_applied"]["temperature_max_c"] is None
    assert payload["rules_evaluated"] == []


def test_cli_unspecified_limit_options_preserve_yaml_values(
    tmp_path,
    capsys,
) -> None:
    config = tmp_path / "validation.yaml"
    config.write_text(ALL_LIMITS_YAML, encoding="utf-8")

    exit_code = run([str(SAMPLE), "--config", str(config)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["limits_applied"] == {
        "cell_min_v": 3.6,
        "cell_max_v": 3.9,
        "imbalance_max_v": 0.08,
        "temperature_min_c": 29.0,
        "temperature_max_c": 45.0,
    }
    assert len(payload["rules_evaluated"]) == 5
