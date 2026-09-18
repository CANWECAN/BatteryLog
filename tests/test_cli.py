import json
import sys
from pathlib import Path

import pytest

from batterylog.__main__ import main

SAMPLE = Path(__file__).parents[1] / "examples" / "sample_battery_log.csv"


def test_cli_emits_structured_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "batterylog",
            str(SAMPLE),
            "--imbalance-limit-v",
            "0.08",
            "--temp-max-c",
            "45",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["validation_status"] == "FAIL"
    assert payload["rules_evaluated"] == [
        "CELL_IMBALANCE_HIGH",
        "TEMPERATURE_HIGH",
    ]
    assert payload["max_delta_v"] == 0.1
    assert payload["temperature_sensors_detected"] == 1
    assert payload["violations"][0] == {
        "code": "CELL_IMBALANCE_HIGH",
        "end_time_s": 4.0,
        "limit_value": 0.08,
        "measured_value": 0.1,
        "peak_time_s": 4.0,
        "signals": ["cell_1_v", "cell_4_v"],
        "start_time_s": 4.0,
        "unit": "V",
    }


def test_cli_accepts_custom_thresholds(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "batterylog",
            str(SAMPLE),
            "--imbalance-limit-v",
            "0.11",
            "--temp-warning-c",
            "50",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["validation_status"] == "PASS"
    assert payload["violations"] == []


def test_cli_reports_validation_errors(monkeypatch, tmp_path, capsys) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "timestamp_s,temp_c,current_a\n0,25,0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["batterylog", str(bad)])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    assert "No cell voltage columns" in capsys.readouterr().err


def test_cli_loads_yaml_config_and_cli_overrides_it(monkeypatch, tmp_path, capsys) -> None:
    config = tmp_path / "validation.yaml"
    config.write_text(
        "limits:\n  cell_voltage:\n    max_delta_v: null\n  temperature:\n    max_c: 40\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "batterylog",
            str(SAMPLE),
            "--config",
            str(config),
            "--temp-max-c",
            "50",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["validation_status"] == "PASS"
    assert payload["rules_evaluated"] == ["TEMPERATURE_HIGH"]
    assert payload["violations"] == []


def test_cli_reports_config_errors(monkeypatch, tmp_path, capsys) -> None:
    config = tmp_path / "bad.yaml"
    config.write_text(
        "limits:\n  cell_voltage:\n    max_v: wrong\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["batterylog", str(SAMPLE), "--config", str(config)],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    assert "must be a number" in capsys.readouterr().err


def test_cli_without_limits_reports_metrics_only(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["batterylog", str(SAMPLE)])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["validation_status"] == "NOT_EVALUATED"
    assert payload["rules_evaluated"] == []
    assert payload["max_delta_v"] == 0.1
    assert payload["violations"] == []
