from pathlib import Path

import pytest

from batterylog import analyze_battery_log

SAMPLE = Path(__file__).parents[1] / "examples" / "sample_battery_log.csv"


def test_sample_log_returns_structured_violation_events() -> None:
    result = analyze_battery_log(SAMPLE)

    assert result["rows_analyzed"] == 5
    assert result["cells_detected"] == 4
    assert result["temperature_sensors_detected"] == 1
    assert result["max_delta_v"] == pytest.approx(0.10)
    assert result["max_temperature_c"] == pytest.approx(48.0)
    assert result["violations"] == [
        {
            "code": "CELL_IMBALANCE_HIGH",
            "start_time_s": 4.0,
            "end_time_s": 4.0,
            "peak_time_s": 4.0,
            "measured_value": 0.1,
            "limit_value": 0.08,
            "unit": "V",
            "signals": ["cell_1_v", "cell_4_v"],
        },
        {
            "code": "TEMPERATURE_HIGH",
            "start_time_s": 4.0,
            "end_time_s": 4.0,
            "peak_time_s": 4.0,
            "measured_value": 48.0,
            "limit_value": 45.0,
            "unit": "degC",
            "signals": ["temp_c"],
        },
    ]


def test_contiguous_violations_are_grouped_into_events(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    path.write_text(
        "timestamp_s,temp_1_c,temp_2_c,cell_1_v,cell_2_v\n"
        "0,25,26,3.80,3.79\n"
        "1,46,44,3.90,3.80\n"
        "2,48,47,3.92,3.78\n"
        "3,44,43,3.85,3.84\n"
        "4,47,49,3.91,3.80\n",
        encoding="utf-8",
    )

    result = analyze_battery_log(path)

    imbalance_events = [
        event for event in result["violations"] if event["code"] == "CELL_IMBALANCE_HIGH"
    ]
    temperature_events = [
        event for event in result["violations"] if event["code"] == "TEMPERATURE_HIGH"
    ]

    assert len(imbalance_events) == 2
    assert imbalance_events[0]["start_time_s"] == 1.0
    assert imbalance_events[0]["end_time_s"] == 2.0
    assert imbalance_events[0]["peak_time_s"] == 2.0
    assert imbalance_events[0]["measured_value"] == pytest.approx(0.14)
    assert imbalance_events[0]["signals"] == ["cell_1_v", "cell_2_v"]
    assert imbalance_events[1]["start_time_s"] == 4.0

    assert len(temperature_events) == 2
    assert temperature_events[0]["start_time_s"] == 1.0
    assert temperature_events[0]["end_time_s"] == 2.0
    assert temperature_events[0]["peak_time_s"] == 2.0
    assert temperature_events[0]["signals"] == ["temp_1_c"]
    assert temperature_events[1]["signals"] == ["temp_2_c"]
    assert result["temperature_sensors_detected"] == 2


def test_custom_limits_can_clear_violations() -> None:
    result = analyze_battery_log(
        SAMPLE,
        imbalance_limit_v=0.11,
        temp_warning_c=50.0,
    )
    assert result["violations"] == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            "temp_c,cell_1_v\n25,3.8\n",
            "Required column 'timestamp_s' is missing",
        ),
        (
            "timestamp_s,temp_c,current_a\n0,25,0\n",
            "No cell voltage columns found",
        ),
        (
            "timestamp_s,cell_1_v\n0,3.8\n",
            "No temperature columns found",
        ),
        (
            "timestamp_s,temp_c,cell_1_v\n",
            "contains no data rows",
        ),
        (
            "timestamp_s,temp_c,cell_1_v,cell_2_v\n0,25,3.8,bad\n",
            "missing or non-numeric",
        ),
        (
            "timestamp_s,temp_c,cell_1_v,cell_2_v\n0,25,3.8,inf\n",
            "non-finite",
        ),
        (
            "timestamp_s,temp_c,cell_1_v\n1,25,3.8\n0,26,3.7\n",
            "non-decreasing",
        ),
    ],
)
def test_invalid_logs_are_rejected(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        analyze_battery_log(path)


@pytest.mark.parametrize("value", [-0.01, float("inf"), float("nan")])
def test_invalid_limits_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="finite, non-negative"):
        analyze_battery_log(SAMPLE, imbalance_limit_v=value)
