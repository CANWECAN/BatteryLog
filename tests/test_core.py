from pathlib import Path

import pytest

from batterylog import (
    EventDetectionConfig,
    SignalMapping,
    SignalPattern,
    ValidationLimits,
    analyze_battery_log,
)

SAMPLE = Path(__file__).parents[1] / "examples" / "sample_battery_log.csv"


def test_sample_log_returns_structured_violation_events() -> None:
    result = analyze_battery_log(
        SAMPLE,
        limits=ValidationLimits(
            imbalance_max_v=0.08,
            temperature_max_c=45.0,
        ),
    )

    assert result["schema_version"] == 2
    assert result["validation_status"] == "FAIL"
    assert result["rules_evaluated"] == [
        "CELL_IMBALANCE_HIGH",
        "TEMPERATURE_HIGH",
    ]
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
        limits=ValidationLimits(
            imbalance_max_v=0.08,
            temperature_max_c=45.0,
        ),
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
        limits=ValidationLimits(
            imbalance_max_v=0.11,
            temperature_max_c=50.0,
        ),
    )
    assert result["validation_status"] == "PASS"
    assert result["rules_evaluated"] == [
        "CELL_IMBALANCE_HIGH",
        "TEMPERATURE_HIGH",
    ]
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
        ValidationLimits(imbalance_max_v=value)


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

    assert result["validation_status"] == "NOT_EVALUATED"
    assert result["rules_evaluated"] == []
    assert result["violations"] == []


def test_legacy_threshold_arguments_override_limits() -> None:
    limits = ValidationLimits(
        imbalance_max_v=0.05,
        temperature_max_c=40.0,
    )

    with pytest.warns(DeprecationWarning, match="deprecated"):
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

    result = analyze_battery_log(
        path,
        limits=ValidationLimits(imbalance_max_v=0.08),
    )
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

    assert result["validation_status"] == "NOT_EVALUATED"
    assert result["rules_evaluated"] == []
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

    result = analyze_battery_log(
        path,
        limits=ValidationLimits(imbalance_max_v=0.1),
    )
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

    assert result["validation_status"] == "PASS"
    assert result["rules_evaluated"] == [
        "CELL_IMBALANCE_HIGH",
        "CELL_OVERVOLTAGE",
        "CELL_UNDERVOLTAGE",
        "TEMPERATURE_HIGH",
        "TEMPERATURE_LOW",
    ]
    assert result["violations"] == []


def test_result_contains_applied_limit_snapshot() -> None:
    limits = ValidationLimits(
        cell_min_v=2.8,
        cell_max_v=4.2,
        imbalance_max_v=0.08,
        temperature_min_c=-20.0,
        temperature_max_c=55.0,
    )

    result = analyze_battery_log(SAMPLE, limits=limits)

    assert result["limits_applied"] == {
        "cell_min_v": 2.8,
        "cell_max_v": 4.2,
        "imbalance_max_v": 0.08,
        "temperature_min_c": -20.0,
        "temperature_max_c": 55.0,
    }


def test_default_event_grouping_preserves_row_contiguity_for_sparse_failures(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sparse.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v,cell_2_v\n"
        "1.0,25,4.00,3.80\n"
        "1.5,25,4.00,3.80\n"
        "800.0,25,4.00,3.80\n",
        encoding="utf-8",
    )

    result = analyze_battery_log(
        path,
        limits=ValidationLimits(imbalance_max_v=0.08),
    )
    events = [event for event in result["violations"] if event["code"] == "CELL_IMBALANCE_HIGH"]

    assert result["analysis_options"] == {"max_event_gap_s": None}
    assert len(events) == 1
    assert events[0]["start_time_s"] == 1.0
    assert events[0]["end_time_s"] == 800.0


def test_max_event_gap_splits_sparse_failures_and_keeps_boundary_samples(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gap.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v,cell_2_v\n"
        "1.0,25,4.00,3.80\n"
        "1.5,25,4.00,3.80\n"
        "1.5,25,4.00,3.80\n"
        "2.1,25,4.00,3.80\n",
        encoding="utf-8",
    )

    result = analyze_battery_log(
        path,
        limits=ValidationLimits(imbalance_max_v=0.08),
        event_detection=EventDetectionConfig(max_gap_s=0.5),
    )
    events = [event for event in result["violations"] if event["code"] == "CELL_IMBALANCE_HIGH"]

    assert result["analysis_options"] == {"max_event_gap_s": 0.5}
    assert len(events) == 2
    assert events[0]["start_time_s"] == 1.0
    assert events[0]["end_time_s"] == 1.5
    assert events[1]["start_time_s"] == 2.1
    assert events[1]["end_time_s"] == 2.1


def test_max_event_gap_applies_to_generic_high_event_rules(tmp_path: Path) -> None:
    path = tmp_path / "temperature_gap.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v\n0.0,50,3.80\n0.4,51,3.80\n5.0,52,3.80\n",
        encoding="utf-8",
    )

    result = analyze_battery_log(
        path,
        limits=ValidationLimits(temperature_max_c=45.0),
        event_detection=EventDetectionConfig(max_gap_s=0.5),
    )
    events = [event for event in result["violations"] if event["code"] == "TEMPERATURE_HIGH"]

    assert len(events) == 2
    assert events[0]["start_time_s"] == 0.0
    assert events[0]["end_time_s"] == 0.4
    assert events[0]["peak_time_s"] == 0.4
    assert events[1]["start_time_s"] == 5.0


@pytest.mark.parametrize("value", [-0.01, float("inf"), float("nan")])
def test_invalid_event_gap_values_are_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        EventDetectionConfig(max_gap_s=value)


def test_event_gap_exact_decimal_boundary_is_not_split_by_float_noise(
    tmp_path: Path,
) -> None:
    path = tmp_path / "float_gap.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v,cell_2_v\n0.1,25,4.0,3.8\n0.4,25,4.0,3.8\n",
        encoding="utf-8",
    )

    result = analyze_battery_log(
        path,
        limits=ValidationLimits(imbalance_max_v=0.08),
        event_detection=EventDetectionConfig(max_gap_s=0.3),
    )
    events = [event for event in result["violations"] if event["code"] == "CELL_IMBALANCE_HIGH"]

    assert len(events) == 1
    assert events[0]["start_time_s"] == 0.1
    assert events[0]["end_time_s"] == 0.4


def test_explicit_signal_mapping_flows_through_full_analysis(tmp_path: Path) -> None:
    path = tmp_path / "vendor.csv"
    path.write_text(
        "Time_s,BMS_CellVoltage_010,BMS_CellVoltage_002,"
        "BMS_CellVoltage_001,BMS_CellVoltage_Max,T_Module_02,T_Module_01\n"
        "0.0,3.90,3.80,3.70,4.20,30,28\n"
        "1.0,3.95,3.82,3.68,4.25,50,47\n",
        encoding="utf-8",
    )
    mapping = SignalMapping(
        timestamp="Time_s",
        cell_voltage=SignalPattern(r"BMS_CellVoltage_(?P<index>\d+)"),
        temperature=SignalPattern(r"T_Module_(?P<index>\d+)"),
    )

    result = analyze_battery_log(
        path,
        limits=ValidationLimits(
            imbalance_max_v=0.08,
            temperature_max_c=45.0,
        ),
        signal_mapping=mapping,
    )

    assert result["cells_detected"] == 3
    assert result["temperature_sensors_detected"] == 2
    assert result["max_cell_voltage_v"] == pytest.approx(3.95)
    assert result["max_delta_v"] == pytest.approx(0.27)
    assert result["max_temperature_c"] == pytest.approx(50.0)
    assert result["signal_mapping"] == {
        "mode": "explicit",
        "timestamp_source": "Time_s",
        "cell_voltage_pattern": r"BMS_CellVoltage_(?P<index>\d+)",
        "temperature_pattern": r"T_Module_(?P<index>\d+)",
    }
    assert [event["code"] for event in result["violations"]] == [
        "CELL_IMBALANCE_HIGH",
        "TEMPERATURE_HIGH",
    ]
    assert result["violations"][0]["signals"] == ["cell_10_v", "cell_1_v"]


def test_canonical_analysis_records_canonical_mapping_mode() -> None:
    result = analyze_battery_log(SAMPLE)

    assert result["signal_mapping"] == {
        "mode": "canonical",
        "timestamp_source": "timestamp_s",
        "cell_voltage_pattern": None,
        "temperature_pattern": None,
    }


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"limits": {}},
            "limits must be a ValidationLimits instance or null",
        ),
        (
            {"event_detection": {}},
            "event_detection must be an EventDetectionConfig instance or null",
        ),
        (
            {"signal_mapping": {}},
            "signal_mapping must be a SignalMapping instance or null",
        ),
    ],
)
def test_analyzer_rejects_invalid_config_object_types(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        analyze_battery_log(SAMPLE, **kwargs)  # type: ignore[arg-type]


def test_invalid_numeric_error_identifies_first_row_column_and_value(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid_numeric.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v,cell_2_v\n0,25,3.8,3.7\n1,26,3.9,bad\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc:
        analyze_battery_log(path)

    message = str(exc.value)
    assert "data row 2" in message
    assert "index 1" in message
    assert "column 'cell_2_v'" in message
    assert "'bad'" in message


def test_non_finite_error_identifies_first_row_column_and_value(
    tmp_path: Path,
) -> None:
    path = tmp_path / "non_finite.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v\n0,25,3.8\n1,inf,3.9\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc:
        analyze_battery_log(path)

    message = str(exc.value)
    assert "data row 2" in message
    assert "index 1" in message
    assert "column 'temp_c'" in message
    assert "inf" in message


def test_result_records_explicit_comparison_policy() -> None:
    from batterylog.analysis.comparison import BINARY64_ABS_TOL, BINARY64_REL_TOL

    result = analyze_battery_log(SAMPLE)

    assert result["comparison_policy"] == {
        "mode": "strict_with_binary64_guard",
        "relative_tolerance": BINARY64_REL_TOL,
        "absolute_tolerance": BINARY64_ABS_TOL,
    }


def test_meaningful_values_beyond_boundaries_still_violate(tmp_path: Path) -> None:
    path = tmp_path / "comparison_boundaries.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v,cell_2_v\n"
        "0,55.000000001,4.200000001,4.12\n"
        "1,-20.000000001,2.799999999,2.80\n",
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

    assert result["validation_status"] == "FAIL"
    assert set(result["rules_evaluated"]) == {
        "CELL_IMBALANCE_HIGH",
        "CELL_OVERVOLTAGE",
        "CELL_UNDERVOLTAGE",
        "TEMPERATURE_HIGH",
        "TEMPERATURE_LOW",
    }
    assert {event["code"] for event in result["violations"]} == {
        "CELL_IMBALANCE_HIGH",
        "CELL_OVERVOLTAGE",
        "CELL_UNDERVOLTAGE",
        "TEMPERATURE_HIGH",
        "TEMPERATURE_LOW",
    }
