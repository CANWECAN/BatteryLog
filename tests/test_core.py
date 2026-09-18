from pathlib import Path

import pytest

from batterylog import analyze_battery_log

SAMPLE = Path(__file__).parents[1] / "examples" / "sample_battery_log.csv"


def test_sample_log_detects_expected_violations() -> None:
    result = analyze_battery_log(SAMPLE)

    assert result["rows_analyzed"] == 5
    assert result["cells_detected"] == 4
    assert result["max_cell_voltage_v"] == pytest.approx(3.95)
    assert result["min_cell_voltage_v"] == pytest.approx(3.58)
    assert result["max_delta_v"] == pytest.approx(0.10)
    assert result["max_temperature_c"] == pytest.approx(48.0)
    assert result["violations"] == [
        "CELL_IMBALANCE_HIGH",
        "TEMPERATURE_WARNING",
    ]


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
        ("temp_c,current_a\n25,0\n", "No cell voltage columns"),
        ("cell_1_v,current_a\n3.8,0\n", "Required column 'temp_c' is missing"),
        ("temp_c,cell_1_v\n", "contains no data rows"),
        (
            "temp_c,cell_1_v,cell_2_v\n25,3.8,bad\n",
            "missing or non-numeric",
        ),
        (
            "temp_c,cell_1_v,cell_2_v\n25,3.8,inf\n",
            "non-finite",
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
