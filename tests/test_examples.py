from pathlib import Path

import pytest

from batterylog import analyze_battery_log, load_validation_config

ROOT = Path(__file__).parents[1]
VENDOR_SAMPLE = ROOT / "examples" / "vendor_battery_log.csv"
VENDOR_CONFIG = ROOT / "examples" / "vendor_mapping.example.yaml"


def test_vendor_mapping_example_runs_end_to_end() -> None:
    config = load_validation_config(VENDOR_CONFIG)

    result = analyze_battery_log(
        VENDOR_SAMPLE,
        limits=config.limits,
        event_detection=config.event_detection,
        data_quality=config.data_quality,
        signal_mapping=config.signals,
    )

    assert result["validation_status"] == "FAIL"
    assert result["cells_detected"] == 4
    assert result["temperature_sensors_detected"] == 2
    assert result["max_cell_voltage_v"] == pytest.approx(3.95)
    assert result["max_delta_v"] == pytest.approx(0.10)
    assert result["max_temperature_c"] == pytest.approx(48.0)
    assert result["min_pack_current_a"] == pytest.approx(-25.0)
    assert result["max_pack_current_a"] == pytest.approx(35.0)
    assert result["min_pack_voltage_v"] == pytest.approx(398.0)
    assert result["max_pack_voltage_v"] == pytest.approx(405.0)
    assert result["analysis_options"] == {"max_event_gap_s": 2.0}
    assert result["signal_mapping"] == {
        "mode": "explicit",
        "timestamp_source": "Time_s",
        "cell_voltage_pattern": r"BMS_CellVoltage_(?P<index>\d+)",
        "temperature_pattern": r"T_Module_(?P<index>\d+)",
        "pack_current_source": "PackCurrent",
        "pack_voltage_source": "PackVoltage",
    }
    assert [event["code"] for event in result["violations"]] == [
        "CELL_IMBALANCE_HIGH",
        "TEMPERATURE_HIGH",
    ]
