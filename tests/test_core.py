from pathlib import Path

import pytest

from batterylog import ValidationLimits, analyze_battery_log

SAMPLE = Path(__file__).parents[1] / "examples" / "sample_battery_log.csv"


def test_sample_log_returns_structured_violation_events() -> None:
    result = analyze_battery_log(
        SAMPLE,
        imbalance_limit_v=0.08,
        temp_warning_c=45.0,
    )

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

    result = analyze_battery_log(
        path,
        imbalance_limit_v=0.08,
        temp_warning_c=45.0,
    )

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


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (-0.01, "non-negative"),
        (float("inf"), "finite"),
        (float("nan"), "finite"),
    ],
)
def test_invalid_limits_are_rejected(value: float, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        analyze_battery_log(SAMPLE, imbalance_limit_v=value)


def test_configurable_rules_detect_voltage_and_temperature_extremes(tmp_path: Path) -> None:
    path = tmp_path / "limits.csv"
    path.write_text(
        "timestamp_s,temp_1_c,temp_2_c,cell_1_v,cell_2_v\n"
        "0,25,24,3.80,3.79\n"
        "1,56,54,4.25,4.10\n"
        "2,-21,-19,2.75,2.90\n"
        "3,25,25,3.80,3.80\n",
        encoding="utf-8",
    )
    limits = ValidationLimits(
        cell_min_v=2.8,
        cell_max_v=4.2,
        imbalance_max_v=None,
        temperature_min_c=-20.0,
        temperature_max_c=55.0,
    )

    result = analyze_battery_log(path, limits=limits)
    by_code = {event["code"]: event for event in result["violations"]}

    assert set(by_code) == {
        "CELL_OVERVOLTAGE",
        "CELL_UNDERVOLTAGE",
        "TEMPERATURE_HIGH",
        "TEMPERATURE_LOW",
    }
    assert by_code["CELL_OVERVOLTAGE"]["peak_time_s"] == 1.0
    assert by_code["CELL_OVERVOLTAGE"]["measured_value"] == pytest.approx(4.25)
    assert by_code["CELL_OVERVOLTAGE"]["signals"] == ["cell_1_v"]
    assert by_code["CELL_UNDERVOLTAGE"]["peak_time_s"] == 2.0
    assert by_code["CELL_UNDERVOLTAGE"]["measured_value"] == pytest.approx(2.75)
    assert by_code["TEMPERATURE_HIGH"]["signals"] == ["temp_1_c"]
    assert by_code["TEMPERATURE_LOW"]["signals"] == ["temp_1_c"]
    assert result["min_temperature_c"] == pytest.approx(-21.0)


def test_all_rules_can_be_disabled() -> None:
    limits = ValidationLimits(
        cell_min_v=None,
        cell_max_v=None,
        imbalance_max_v=None,
        temperature_min_c=None,
        temperature_max_c=None,
    )

    result = analyze_battery_log(SAMPLE, limits=limits)

    assert result["violations"] == []


def test_legacy_threshold_arguments_override_limits() -> None:
    limits = ValidationLimits(
        imbalance_max_v=0.05,
        temperature_max_c=40.0,
    )

    result = analyze_battery_log(
        SAMPLE,
        imbalance_limit_v=0.11,
        temp_warning_c=50.0,
        limits=limits,
    )

    assert result["violations"] == []


def test_imbalance_event_reports_all_tied_extreme_cells(tmp_path: Path) -> None:
    path = tmp_path / "tied.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v,cell_2_v,cell_3_v,cell_4_v\n0,25,4.00,4.00,3.80,3.80\n",
        encoding="utf-8",
    )

    result = analyze_battery_log(path, imbalance_limit_v=0.08)
    event = result["violations"][0]

    assert event["code"] == "CELL_IMBALANCE_HIGH"
    assert event["signals"] == [
        "cell_1_v",
        "cell_2_v",
        "cell_3_v",
        "cell_4_v",
    ]


def test_default_analysis_computes_metrics_without_assuming_limits() -> None:
    result = analyze_battery_log(SAMPLE)

    assert result["max_delta_v"] == pytest.approx(0.10)
    assert result["max_temperature_c"] == pytest.approx(48.0)
    assert result["violations"] == []


def test_aggregate_columns_are_not_misclassified_as_cell_signals(tmp_path: Path) -> None:
    path = tmp_path / "aggregate.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_min_v,cell_max_v\n0,25,3.7,4.1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="No cell voltage columns found"):
        analyze_battery_log(path)


def test_signal_columns_are_sorted_by_numeric_index(tmp_path: Path) -> None:
    path = tmp_path / "natural_order.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_10_v,cell_2_v,cell_1_v\n0,25,4.0,3.8,4.0\n",
        encoding="utf-8",
    )

    result = analyze_battery_log(path, imbalance_limit_v=0.1)
    event = result["violations"][0]

    assert event["signals"] == ["cell_1_v", "cell_10_v", "cell_2_v"]


def test_duplicate_logical_signal_indexes_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate_index.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v,cell_01_v\n0,25,3.8,3.9\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate cell signal index 1"):
        analyze_battery_log(path)


def test_legacy_temperature_name_cannot_mix_with_indexed_sensors(tmp_path: Path) -> None:
    path = tmp_path / "mixed_temp.csv"
    path.write_text(
        "timestamp_s,temp_c,temp_1_c,cell_1_v\n0,25,26,3.8\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Legacy temp_c cannot be combined"):
        analyze_battery_log(path)


def test_duplicate_csv_headers_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate_header.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v,cell_1_v\n0,25,3.8,3.9\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate CSV column name"):
        analyze_battery_log(path)


def test_values_exactly_on_limits_do_not_violate(tmp_path: Path) -> None:
    path = tmp_path / "boundaries.csv"
    path.write_text(
        "timestamp_s,temp_1_c,temp_2_c,cell_1_v,cell_2_v\n0,-20,55,4.20,4.12\n1,25,25,2.80,2.80\n",
        encoding="utf-8",
    )
    limits = ValidationLimits(
        cell_min_v=2.8,
        cell_max_v=4.2,
        imbalance_max_v=0.08,
        temperature_min_c=-20.0,
        temperature_max_c=55.0,
    )

    result = analyze_battery_log(path, limits=limits)

    assert result["violations"] == []
