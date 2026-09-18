import json
import sys
from pathlib import Path

import pytest

from batterylog.__main__ import main

SAMPLE = Path(__file__).parents[1] / "examples" / "sample_battery_log.csv"


def test_cli_emits_clean_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["batterylog", str(SAMPLE)])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["max_delta_v"] == 0.1
    assert payload["max_temperature_c"] == 48.0
    assert "CELL_IMBALANCE_HIGH" in payload["violations"]


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
    assert payload["violations"] == []


def test_cli_reports_validation_errors(monkeypatch, tmp_path, capsys) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("temp_c,current_a\n25,0\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["batterylog", str(bad)])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    assert "No cell voltage columns" in capsys.readouterr().err
