"""Contract and analysis parity for pack-voltage measurement plausibility."""

import copy
import json
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from batterylog import DataQualityConfig, EventDetectionConfig, ValidationLimits
from batterylog.__main__ import run
from batterylog.analysis.core import _analyze_battery_frame, analyze_battery_bytes
from batterylog.analysis.streaming import (
    _analyze_battery_chunks,
    analyze_battery_file_with_report_series,
)
from batterylog.config import load_validation_config_bytes
from batterylog.reporting.html import render_html_report

DATA = (
    b"timestamp_s,cell_1_v,cell_2_v,temp_c,pack_voltage_v\n"
    b"0,3.5,3.5,25,7.0\n"
    b"1,3.5,3.5,25,7.125\n"
    b"1,3.5,3.5,25,7.25\n"
    b"2,3.5,3.5,25,7.25\n"
    b"3,3.5,3.5,25,7.0\n"
)
LIMIT = ValidationLimits(pack_voltage_cell_sum_max_delta_v=0.125)
SCHEMA = json.loads((Path(__file__).parents[1] / "batterylog/schema/result-v8.json").read_text())


def test_exact_boundary_event_peak_and_chunk_merge() -> None:
    frame = pd.read_csv(StringIO(DATA.decode()))
    expected = _analyze_battery_frame(frame, limits=LIMIT)
    for size in (1, 2, 3, 10):
        chunks = (frame.iloc[i : i + size].copy() for i in range(0, len(frame), size))
        assert _analyze_battery_chunks(chunks, limits=LIMIT) == expected
    assert expected == analyze_battery_bytes(DATA, limits=LIMIT)
    assert expected["rules_evaluated"] == ["PACK_VOLTAGE_CELL_SUM_MISMATCH"]
    assert expected["validation_status"] == "FAIL"
    assert expected["pack_voltage_cell_sum_peak"] == {
        "timestamp_s": 1.0,
        "pack_voltage_v": 7.25,
        "cell_voltage_sum_v": 7.0,
        "signed_error_v": 0.25,
        "absolute_delta_v": 0.25,
    }
    assert expected["violations"] == [
        {
            "code": "PACK_VOLTAGE_CELL_SUM_MISMATCH",
            "start_time_s": 1.0,
            "end_time_s": 2.0,
            "peak_time_s": 1.0,
            "measured_value": 0.25,
            "limit_value": 0.125,
            "sample_count": 2,
            "duration_s": 1.0,
            "peak_excursion": 0.125,
            "unit": "V",
            "signals": ["pack_voltage_v", "cell_1_v", "cell_2_v"],
            "pack_voltage_v": 7.25,
            "cell_voltage_sum_v": 7.0,
            "signed_error_v": 0.25,
        }
    ]
    Draft202012Validator(SCHEMA).validate(expected)


def test_negative_signed_error_and_missing_pack_fail_closed() -> None:
    data = DATA.replace(b"7.25", b"6.75")
    result = analyze_battery_bytes(data, limits=LIMIT)
    assert result["violations"][0]["signed_error_v"] == -0.25
    assert result["pack_voltage_cell_sum_peak"]["signed_error_v"] == -0.25
    missing = (
        DATA.replace(b",pack_voltage_v", b"")
        .replace(b",7.0", b"")
        .replace(b",7.125", b"")
        .replace(b",7.25", b"")
    )
    with pytest.raises(ValueError, match="requires column 'pack_voltage_v'"):
        analyze_battery_bytes(missing, limits=LIMIT)
    with pytest.raises(ValueError, match="requires column 'pack_voltage_v'"):
        _analyze_battery_chunks((pd.read_csv(StringIO(missing.decode())),), limits=LIMIT)


def test_excluded_row_breaks_contiguous_event_and_all_invalid_has_null_peak() -> None:
    data = DATA.replace(b"1,3.5,3.5,25,7.25\n", b"1,bad,3.5,25,7.25\n", 1)
    dq = DataQualityConfig(mode="exclude_invalid_rows")
    result = analyze_battery_bytes(data, limits=LIMIT, data_quality=dq)
    frame = pd.read_csv(StringIO(data.decode()))
    assert result == _analyze_battery_chunks(
        (frame.iloc[:2], frame.iloc[2:4], frame.iloc[4:]), limits=LIMIT, data_quality=dq
    )
    assert result["rows_excluded"] == 1
    assert result["violations"][0]["sample_count"] == 1
    assert result["violations"][0]["start_time_s"] == 2.0
    Draft202012Validator(SCHEMA).validate(result)
    invalid = data.replace(b"3.5", b"bad")
    all_invalid = analyze_battery_bytes(invalid, limits=LIMIT, data_quality=dq)
    assert all_invalid["pack_voltage_cell_sum_peak"] is None
    assert all_invalid["validation_status"] == "FAIL"
    Draft202012Validator(SCHEMA).validate(all_invalid)


@pytest.mark.parametrize("bad", (0, -0.1, float("nan"), True))
def test_invalid_tolerance_rejected(bad: float) -> None:
    with pytest.raises((ValueError, TypeError)):
        ValidationLimits(pack_voltage_cell_sum_max_delta_v=bad)


def test_config_version_gate_and_schema_evidence() -> None:
    config = b"schema_version: 6\nlimits:\n  pack_voltage:\n    cell_sum_max_delta_v: 0.125\n"
    assert load_validation_config_bytes(config).limits == LIMIT
    with pytest.raises(ValueError, match="Unknown limits key"):
        load_validation_config_bytes(config.replace(b"schema_version: 6", b"schema_version: 5"))
    result = analyze_battery_bytes(DATA, limits=LIMIT)
    validator = Draft202012Validator(SCHEMA)
    validator.validate(result)
    for field in ("pack_voltage_v", "cell_voltage_sum_v", "signed_error_v"):
        altered = copy.deepcopy(result)
        altered["violations"][0].pop(field)
        with pytest.raises(ValidationError):
            validator.validate(altered)
    altered = copy.deepcopy(result)
    altered["pack_voltage_cell_sum_peak"] = None
    with pytest.raises(ValidationError):
        validator.validate(altered)
    unrelated = analyze_battery_bytes(DATA, limits=ValidationLimits(cell_max_v=3.4))
    unrelated["violations"][0]["signed_error_v"] = 0.0
    with pytest.raises(ValidationError):
        validator.validate(unrelated)
    old = json.loads((Path(__file__).parents[1] / "batterylog/schema/result-v7.json").read_text())
    assert "PACK_VOLTAGE_CELL_SUM_MISMATCH" not in old["$defs"]["ruleCode"]["enum"]


def test_cli_override_and_report_evidence(tmp_path: Path, capsys) -> None:
    path = tmp_path / "measurement.csv"
    path.write_bytes(DATA)
    report = tmp_path / "report.html"
    assert run([str(path), "--pack-cell-sum-max-delta-v", "0.125", "--report", str(report)]) == 1
    result = json.loads(capsys.readouterr().out)
    Draft202012Validator(SCHEMA).validate(result)
    html = report.read_text()
    assert "Pack voltage and cell sum" in html
    assert "Absolute pack/cell-sum mismatch" in html
    assert "signed error 0.25 V" in html
    with BytesIO(DATA) as handle:
        expected, series = analyze_battery_file_with_report_series(handle, limits=LIMIT)
    assert render_html_report(expected, series=series) == render_html_report(
        expected, series=series
    )
    assert series.points[2].pack_cell_delta_v == 0.25
    assert run([str(path), "--pack-cell-sum-max-delta-v", "0"]) == 4
    capsys.readouterr()
    config = tmp_path / "limits.yaml"
    config.write_text(
        "schema_version: 6\nlimits:\n  pack_voltage:\n    cell_sum_max_delta_v: 0.125\n"
    )
    assert run([str(path), "--config", str(config), "--no-pack-cell-sum-max-delta-v"]) == 3
    disabled = json.loads(capsys.readouterr().out)
    assert disabled["limits_applied"]["pack_voltage_cell_sum_max_delta_v"] is None
    assert disabled["violations"] == []


def test_downsampled_plot_retains_unique_mismatch_peak() -> None:
    rows = [f"{i},3.5,3.5,25,{8.0 if i == 51 else 7.0}" for i in range(110)]
    data = (
        "timestamp_s,cell_1_v,cell_2_v,temp_c,pack_voltage_v\n" + "\n".join(rows) + "\n"
    ).encode()
    with BytesIO(data) as handle:
        result, series = analyze_battery_file_with_report_series(
            handle, limits=LIMIT, max_points=14
        )
    assert series.is_downsampled
    assert len(series.points) <= 14
    assert max(p.pack_cell_delta_v for p in series.points) == 1.0
    assert result["pack_voltage_cell_sum_peak"]["timestamp_s"] == 51.0
    assert "Absolute pack/cell-sum mismatch" in render_html_report(result, series=series)


def test_synthetic_complete_96s_pack_preserves_mismatch_through_streaming_and_plot() -> None:
    rows = 129
    values = {
        "timestamp_s": range(rows),
        "temp_c": [25.0] * rows,
        "pack_current_a": [12.0] * rows,
    }
    cell_columns = [f"cell_{index}_v" for index in range(1, 97)]
    for index, column in enumerate(cell_columns):
        values[column] = [
            3.45 + (index % 13) * 0.001 + ((row % 9) - 4) * 0.002 for row in range(rows)
        ]
    frame = pd.DataFrame(values)
    frame["pack_voltage_v"] = [
        sum(float(frame[column].iat[row]) for column in cell_columns)
        + (0.01 if row % 2 else -0.01)
        + (0.35 if 60 <= row <= 62 else 0.0)
        for row in range(rows)
    ]
    limits = ValidationLimits(pack_voltage_cell_sum_max_delta_v=0.15)
    expected = _analyze_battery_frame(frame, limits=limits)

    for size in (1, 17, 64):
        chunks = (frame.iloc[start : start + size] for start in range(0, rows, size))
        assert _analyze_battery_chunks(chunks, limits=limits) == expected

    assert expected["rules_evaluated"] == ["PACK_VOLTAGE_CELL_SUM_MISMATCH"]
    assert expected["validation_status"] == "FAIL"
    assert [
        (event["start_time_s"], event["end_time_s"], event["sample_count"])
        for event in expected["violations"]
    ] == [(60.0, 62.0, 3)]

    with BytesIO(frame.to_csv(index=False).encode()) as handle:
        result, series = analyze_battery_file_with_report_series(
            handle, limits=limits, max_points=24
        )
    assert result["validation_status"] == "FAIL"
    assert len(series.points) <= 24
    assert any(point.row_index == 61 for point in series.points)
    assert "Absolute pack/cell-sum mismatch" in render_html_report(result, series=series)

    incomplete = _analyze_battery_frame(frame.drop(columns=["cell_96_v"]), limits=limits)
    assert incomplete["validation_status"] == "FAIL"
    assert incomplete["violations"][0]["sample_count"] == rows


def test_event_gap_split_matches_chunked_analysis() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 10.0, 11.0],
            "cell_1_v": [3.5] * 4,
            "cell_2_v": [3.5] * 4,
            "temp_c": [25.0] * 4,
            "pack_voltage_v": [7.0, 7.25, 7.25, 7.25],
        }
    )
    gap = EventDetectionConfig(max_gap_s=2.0)
    expected = _analyze_battery_frame(frame, limits=LIMIT, event_detection=gap)
    assert (
        _analyze_battery_chunks(
            (frame.iloc[:2], frame.iloc[2:3], frame.iloc[3:]),
            limits=LIMIT,
            event_detection=gap,
        )
        == expected
    )
    assert [(e["start_time_s"], e["sample_count"]) for e in expected["violations"]] == [
        (1.0, 1),
        (10.0, 2),
    ]
