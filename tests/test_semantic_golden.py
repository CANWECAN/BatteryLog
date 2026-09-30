from io import BytesIO
from pathlib import Path

from batterylog import DataQualityConfig, ValidationLimits
from batterylog.analysis.core import analyze_battery_bytes
from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.loaders import CsvFileLoader
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
) -> None:
    expected = _golden(golden_name)

    whole = analyze_battery_bytes(
        data,
        limits=limits,
        data_quality=data_quality,
    )
    streaming = analyze_measurement_loader(
        CsvFileLoader(BytesIO(data), chunk_rows=1),
        limits=limits,
        data_quality=data_quality,
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
        (
            b"timestamp_s,temp_1_c,temp_2_c,cell_1_v,cell_2_v\n"
            b"0,25,24,3.8,3.7\n"
            b"1,56,50,4.3,3.9\n"
        ),
        "semantic_multi_rule_fail.json",
        limits=ValidationLimits(
            imbalance_max_v=0.08,
            cell_max_v=4.2,
            temperature_max_c=55.0,
        ),
    )


def test_data_quality_serialized_semantics_match_v092_golden() -> None:
    _assert_serialized_golden(
        (
            b"timestamp_s,temp_c,cell_1_v,cell_2_v\n"
            b"0,25,3.8,3.7\n"
            b"1,bad,4.5,3.0\n"
            b"2,26,4.0,3.9\n"
        ),
        "semantic_data_quality_fail.json",
        limits=ValidationLimits(imbalance_max_v=0.08),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )
