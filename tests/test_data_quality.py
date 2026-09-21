from io import BytesIO

import numpy as np
import pandas as pd
import pytest

from batterylog import ValidationLimits
from batterylog.analysis.core import _analyze_battery_frame, analyze_battery_bytes
from batterylog.analysis.data_quality import DataQualityCollector
from batterylog.analysis.streaming import _analyze_battery_chunks, analyze_measurement_loader
from batterylog.config import DataQualityConfig
from batterylog.loaders import CsvFileLoader


def _numeric(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.apply(pd.to_numeric, errors="coerce")


def test_data_quality_collector_classifies_required_numeric_defects() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0, 3.0],
            "cell_1_v": [3.8, np.nan, "bad", np.inf],
            "temp_1_c": [25.0, 26.0, 27.0, 28.0],
        }
    )
    collector = DataQualityCollector()

    invalid = collector.consume_chunk(frame, _numeric(frame), row_offset=10)
    events = collector.finish()

    assert invalid.tolist() == [False, True, True, True]
    assert events == [
        {
            "code": "MISSING_REQUIRED_VALUE",
            "start_row": 12,
            "end_row": 12,
            "signals": ["cell_1_v"],
            "affected_values": 1,
        },
        {
            "code": "NON_NUMERIC_REQUIRED_VALUE",
            "start_row": 13,
            "end_row": 13,
            "signals": ["cell_1_v"],
            "affected_values": 1,
        },
        {
            "code": "NON_FINITE_REQUIRED_VALUE",
            "start_row": 14,
            "end_row": 14,
            "signals": ["cell_1_v"],
            "affected_values": 1,
        },
    ]


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("timestamp_s", True),
        ("cell_1_v", np.bool_(False)),
        ("temp_1_c", True),
    ],
)
def test_data_quality_collector_classifies_booleans_as_non_numeric(
    column: str,
    value: object,
) -> None:
    values: dict[str, list[object]] = {
        "timestamp_s": [0.0],
        "cell_1_v": [3.8],
        "temp_1_c": [25.0],
    }
    values[column] = [value]
    frame = pd.DataFrame(values)
    collector = DataQualityCollector()

    invalid = collector.consume_chunk(frame, _numeric(frame), row_offset=0)

    assert invalid.tolist() == [True]
    assert collector.finish() == [
        {
            "code": "NON_NUMERIC_REQUIRED_VALUE",
            "start_row": 1,
            "end_row": 1,
            "signals": [column],
            "affected_values": 1,
        }
    ]


def test_nullable_boolean_distinguishes_boolean_from_missing() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0],
            "cell_1_v": pd.Series([True, pd.NA], dtype="boolean"),
            "temp_1_c": [25.0, 25.0],
        }
    )
    collector = DataQualityCollector()

    invalid = collector.consume_chunk(frame, _numeric(frame), row_offset=0)

    assert invalid.tolist() == [True, True]
    assert [event["code"] for event in collector.finish()] == [
        "NON_NUMERIC_REQUIRED_VALUE",
        "MISSING_REQUIRED_VALUE",
    ]


def test_data_quality_collector_groups_exact_defect_runs_across_chunks() -> None:
    collector = DataQualityCollector()
    first = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0],
            "cell_1_v": [np.nan, np.nan],
            "cell_2_v": [np.nan, np.nan],
            "temp_1_c": [25.0, 25.0],
        }
    )
    second = pd.DataFrame(
        {
            "timestamp_s": [2.0, 3.0, 4.0],
            "cell_1_v": [np.nan, 3.8, np.nan],
            "cell_2_v": [np.nan, 3.79, 3.79],
            "temp_1_c": [25.0, 25.0, 25.0],
        }
    )

    first_invalid = collector.consume_chunk(first, _numeric(first), row_offset=0)
    second_invalid = collector.consume_chunk(second, _numeric(second), row_offset=2)
    events = collector.finish()

    assert first_invalid.tolist() == [True, True]
    assert second_invalid.tolist() == [True, False, True]
    assert events == [
        {
            "code": "MISSING_REQUIRED_VALUE",
            "start_row": 1,
            "end_row": 3,
            "signals": ["cell_1_v", "cell_2_v"],
            "affected_values": 6,
        },
        {
            "code": "MISSING_REQUIRED_VALUE",
            "start_row": 5,
            "end_row": 5,
            "signals": ["cell_1_v"],
            "affected_values": 1,
        },
    ]


def test_strict_mode_rejects_typed_boolean_required_value() -> None:
    frame = pd.DataFrame({"timestamp_s": [0.0], "cell_1_v": [3.8], "temp_c": [True]})

    with pytest.raises(ValueError, match="Required numeric value is missing or non-numeric"):
        _analyze_battery_frame(frame)


def test_csv_boolean_inference_is_chunk_boundary_independent() -> None:
    data = b"timestamp_s,cell_1_v,temp_c\n0,3.8,True\n1,3.8,bad\n"
    config = DataQualityConfig(mode="exclude_invalid_rows")

    whole = analyze_battery_bytes(data, data_quality=config)
    streaming = analyze_measurement_loader(
        CsvFileLoader(BytesIO(data), chunk_rows=1),
        data_quality=config,
    )

    assert streaming == whole
    assert whole["rows_analyzed"] == 0
    assert whole["rows_excluded"] == 2
    assert whole["max_temperature_c"] is None
    assert whole["data_quality"]["events"] == [
        {
            "code": "NON_NUMERIC_REQUIRED_VALUE",
            "start_row": 1,
            "end_row": 2,
            "signals": ["temp_c"],
            "affected_values": 2,
        }
    ]


def test_strict_mode_preserves_fail_fast_invalid_numeric_behavior() -> None:
    data = b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.8,3.79,25\n1,bad,3.79,25\n"

    with pytest.raises(ValueError, match="Required numeric value is missing or non-numeric"):
        analyze_battery_bytes(data)


def test_pack_signals_participate_in_required_numeric_data_quality() -> None:
    data = (
        b"timestamp_s,pack_current_a,pack_voltage_v,cell_1_v,temp_c\n"
        b"0,-10,400,3.8,25\n"
        b"1,bad,401,3.9,26\n"
    )

    with pytest.raises(ValueError, match="column 'pack_current_a': 'bad'"):
        analyze_battery_bytes(data)

    result = analyze_battery_bytes(
        data,
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )

    assert result["rows_analyzed"] == 1
    assert result["rows_excluded"] == 1
    assert result["max_pack_current_a"] == -10.0
    assert result["min_pack_voltage_v"] == 400.0
    assert result["data_quality"]["events"] == [
        {
            "code": "NON_NUMERIC_REQUIRED_VALUE",
            "start_row": 2,
            "end_row": 2,
            "signals": ["pack_current_a"],
            "affected_values": 1,
        }
    ]


def test_exclude_invalid_rows_records_evidence_and_breaks_rule_continuity() -> None:
    data = b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,4.30,3.80,25\n1,bad,3.80,25\n2,4.40,3.80,25\n"

    result = analyze_battery_bytes(
        data,
        limits=ValidationLimits(cell_max_v=4.2),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )

    assert result["validation_status"] == "FAIL"
    assert result["rows_input"] == 3
    assert result["rows_analyzed"] == 2
    assert result["rows_excluded"] == 1
    assert result["data_quality"] == {
        "mode": "exclude_invalid_rows",
        "events": [
            {
                "code": "NON_NUMERIC_REQUIRED_VALUE",
                "start_row": 2,
                "end_row": 2,
                "signals": ["cell_1_v"],
                "affected_values": 1,
            }
        ],
    }
    assert [event["start_time_s"] for event in result["violations"]] == [0.0, 2.0]
    assert [event["end_time_s"] for event in result["violations"]] == [0.0, 2.0]
    assert result["max_cell_voltage_v"] == 4.4
    assert result["max_delta_v"] == 0.6


def test_data_quality_evidence_prevents_false_pass_without_battery_rules() -> None:
    data = b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.8,3.79,25\n1,,3.79,25\n"

    result = analyze_battery_bytes(
        data,
        limits=ValidationLimits(),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )

    assert result["rules_evaluated"] == []
    assert result["violations"] == []
    assert result["validation_status"] == "FAIL"
    assert result["rows_input"] == 2
    assert result["rows_analyzed"] == 1
    assert result["rows_excluded"] == 1
    assert result["data_quality"]["events"][0]["code"] == "MISSING_REQUIRED_VALUE"


def test_all_invalid_rows_return_structured_fail_with_null_extrema() -> None:
    data = b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,bad,3.79,25\n1,inf,3.79,25\n"

    result = analyze_battery_bytes(
        data,
        limits=ValidationLimits(cell_max_v=4.2),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )

    assert result["validation_status"] == "FAIL"
    assert result["rows_input"] == 2
    assert result["rows_analyzed"] == 0
    assert result["rows_excluded"] == 2
    assert result["violations"] == []
    assert result["max_cell_voltage_v"] is None
    assert result["min_cell_voltage_v"] is None
    assert result["max_delta_v"] is None
    assert result["max_temperature_c"] is None
    assert result["min_temperature_c"] is None
    assert [event["code"] for event in result["data_quality"]["events"]] == [
        "NON_NUMERIC_REQUIRED_VALUE",
        "NON_FINITE_REQUIRED_VALUE",
    ]


def test_streaming_and_whole_frame_data_quality_results_match_across_chunk_boundary() -> None:
    first = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0],
            "cell_1_v": [3.80, np.nan],
            "cell_2_v": [3.79, 3.79],
            "temp_c": [25.0, 25.0],
        }
    )
    second = pd.DataFrame(
        {
            "timestamp_s": [2.0, 3.0],
            "cell_1_v": [np.nan, 3.81],
            "cell_2_v": [3.79, 3.80],
            "temp_c": [25.0, 25.0],
        }
    )
    config = DataQualityConfig(mode="exclude_invalid_rows")
    limits = ValidationLimits(imbalance_max_v=0.08)

    streaming = _analyze_battery_chunks(
        [first, second],
        limits=limits,
        data_quality=config,
    )
    whole = _analyze_battery_frame(
        pd.concat([first, second], ignore_index=True),
        limits=limits,
        data_quality=config,
    )

    assert streaming == whole
    assert streaming["data_quality"]["events"] == [
        {
            "code": "MISSING_REQUIRED_VALUE",
            "start_row": 2,
            "end_row": 3,
            "signals": ["cell_1_v"],
            "affected_values": 2,
        }
    ]


def test_invalid_timestamp_is_excluded_and_breaks_violation_continuity() -> None:
    data = (
        b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,4.30,3.80,25\nbad,4.35,3.80,25\n2,4.40,3.80,25\n"
    )

    result = analyze_battery_bytes(
        data,
        limits=ValidationLimits(cell_max_v=4.2),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )

    assert result["rows_input"] == result["rows_analyzed"] + result["rows_excluded"]
    assert result["rows_excluded"] == 1
    assert result["data_quality"]["events"] == [
        {
            "code": "NON_NUMERIC_REQUIRED_VALUE",
            "start_row": 2,
            "end_row": 2,
            "signals": ["timestamp_s"],
            "affected_values": 1,
        }
    ]
    assert [(event["start_time_s"], event["end_time_s"]) for event in result["violations"]] == [
        (0.0, 0.0),
        (2.0, 2.0),
    ]
