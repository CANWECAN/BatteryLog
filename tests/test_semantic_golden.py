from io import BytesIO
from pathlib import Path

import pytest

from batterylog import (
    DataQualityConfig,
    EventDetectionConfig,
    SignalMapping,
    SignalPattern,
    ValidationLimits,
)
from batterylog.analysis.core import analyze_battery_bytes
from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.loaders import CsvFileLoader
from batterylog.models import CurrentDirection
from batterylog.reporting import render_json_result

GOLDEN_DIR = Path(__file__).with_name("golden")


def _golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_text(encoding="utf-8")


def _assert_serialized_golden(
    data: bytes,
    golden_name: str,
    *,
    limits: ValidationLimits | None = None,
    data_quality: DataQualityConfig | None = None,
    event_detection: EventDetectionConfig | None = None,
    signal_mapping: SignalMapping | None = None,
    chunk_rows: int = 1,
) -> None:
    expected = _golden(golden_name)

    whole = analyze_battery_bytes(
        data,
        limits=limits,
        data_quality=data_quality,
        event_detection=event_detection,
        signal_mapping=signal_mapping,
    )
    streaming = analyze_measurement_loader(
        CsvFileLoader(BytesIO(data), chunk_rows=chunk_rows),
        limits=limits,
        data_quality=data_quality,
        event_detection=event_detection,
        signal_mapping=signal_mapping,
    )

    assert render_json_result(whole) == expected
    assert render_json_result(streaming) == expected


def test_not_evaluated_serialized_semantics_match_v092_golden() -> None:
    _assert_serialized_golden(
        b"timestamp_s,temp_c,cell_1_v\n0,25,3.8\n",
        "semantic_not_evaluated.json",
    )


def test_multi_rule_serialized_semantics_match_v092_golden() -> None:
    _assert_serialized_golden(
        (b"timestamp_s,temp_1_c,temp_2_c,cell_1_v,cell_2_v\n0,25,24,3.8,3.7\n1,56,50,4.3,3.9\n"),
        "semantic_multi_rule_fail.json",
        limits=ValidationLimits(
            imbalance_max_v=0.08,
            cell_max_v=4.2,
            temperature_max_c=55.0,
        ),
    )


def test_data_quality_serialized_semantics_match_v092_golden() -> None:
    _assert_serialized_golden(
        (b"timestamp_s,temp_c,cell_1_v,cell_2_v\n0,25,3.8,3.7\n1,bad,4.5,3.0\n2,26,4.0,3.9\n"),
        "semantic_data_quality_fail.json",
        limits=ValidationLimits(imbalance_max_v=0.08),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )


def _all_limits(positive_direction: CurrentDirection = "charge") -> ValidationLimits:
    return ValidationLimits(
        cell_min_v=3.0,
        cell_max_v=4.25,
        imbalance_max_v=1.0,
        temperature_min_c=-20.0,
        temperature_max_c=50.0,
        temperature_spread_max_c=10.0,
        pack_charge_max_a=10.0,
        pack_discharge_max_a=15.0,
        pack_current_positive_direction=positive_direction,
        pack_voltage_cell_sum_max_delta_v=0.25,
    )


PASS_DATA = (
    b"timestamp_s,pack_current_a,pack_voltage_v,cell_1_v,cell_2_v,temp_1_c,temp_2_c\n"
    b"0,10,7,3,4,-20,-10\n"
    b"1,-15,8.75,4.25,4.25,50,50\n"
)


@pytest.mark.parametrize("chunk_rows", [1, 2, 3, 64])
def test_all_rules_pass_at_exact_boundaries_matches_golden(chunk_rows: int) -> None:
    _assert_serialized_golden(
        PASS_DATA,
        "semantic_all_rules_pass.json",
        limits=_all_limits(),
        chunk_rows=chunk_rows,
    )


@pytest.mark.parametrize("chunk_rows", [1, 2, 3, 64])
@pytest.mark.parametrize("positive_direction", ["charge", "discharge"])
def test_pack_and_lower_rule_evidence_matches_golden(
    chunk_rows: int,
    positive_direction: CurrentDirection,
) -> None:
    # Binary-exact inputs make the independently calculated signed errors and
    # boundary expectations unambiguous. Duplicate timestamps and equal peaks
    # must retain the first source sample even when it lies in another chunk.
    sign = 1 if positive_direction == "charge" else -1
    data = (
        "timestamp_s,pack_current_a,pack_voltage_v,cell_1_v,cell_2_v,temp_1_c,temp_2_c\n"
        "0,0,7,3.5,3.5,25,25\n"
        f"1,{sign * 12},7.5,3.5,3.5,25,25\n"
        f"1,{sign * 12},6.5,3.5,3.5,25,25\n"
        f"10,{sign * -20},5.5,2.5,3.5,-25,0\n"
        f"11,{sign * -20},6.5,3.5,3.5,-25,0\n"
        "12,0,7,3.5,3.5,25,25\n"
    ).encode()
    _assert_serialized_golden(
        data,
        f"semantic_pack_lower_fail_{positive_direction}.json",
        limits=_all_limits(positive_direction),
        event_detection=EventDetectionConfig(max_gap_s=2.0),
        chunk_rows=chunk_rows,
    )


@pytest.mark.parametrize("chunk_rows", [1, 2, 3, 64])
def test_all_excluded_with_active_rules_matches_golden(chunk_rows: int) -> None:
    _assert_serialized_golden(
        (
            b"timestamp_s,pack_current_a,pack_voltage_v,cell_1_v,cell_2_v,temp_1_c,temp_2_c\n"
            b"0,10,7,3.5,3.5,bad,25\n"
            b"1,-15,7.25,3.5,3.5,bad,25\n"
        ),
        "semantic_all_excluded_fail.json",
        limits=_all_limits(),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
        chunk_rows=chunk_rows,
    )


@pytest.mark.parametrize("chunk_rows", [1, 2, 3, 64])
def test_explicit_mapping_provenance_matches_golden(chunk_rows: int) -> None:
    vendor = PASS_DATA.replace(
        b"timestamp_s,pack_current_a,pack_voltage_v,cell_1_v,cell_2_v,temp_1_c,temp_2_c",
        b"Time,Current,Pack,U1,U2,T1,T2",
    )
    _assert_serialized_golden(
        vendor,
        "semantic_explicit_mapping_pass.json",
        limits=_all_limits(),
        signal_mapping=SignalMapping(
            timestamp="Time",
            cell_voltage=SignalPattern(r"U(?P<index>[0-9]+)"),
            temperature=SignalPattern(r"T(?P<index>[0-9]+)"),
            pack_current="Current",
            pack_voltage="Pack",
        ),
        chunk_rows=chunk_rows,
    )
