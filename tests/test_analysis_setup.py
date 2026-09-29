import pandas as pd
import pytest

from batterylog.analysis.configuration import (
    resolve_data_quality,
    resolve_event_detection,
    resolve_limits,
    validate_signal_mapping,
)
from batterylog.analysis.input_validation import (
    canonicalize_analysis_frame,
    raise_invalid_numeric_value,
    valid_timestamp_values,
)
from batterylog.config import DataQualityConfig, EventDetectionConfig, ValidationLimits


def test_configuration_resolution_preserves_legacy_limit_overrides() -> None:
    resolved = resolve_limits(
        ValidationLimits(cell_max_v=4.2, imbalance_max_v=0.1),
        0.2,
        55.0,
    )
    assert resolved.cell_max_v == 4.2
    assert resolved.imbalance_max_v == 0.2
    assert resolved.temperature_max_c == 55.0


def test_configuration_resolution_validates_option_types() -> None:
    assert resolve_event_detection(None) == EventDetectionConfig()
    assert resolve_data_quality(None) == DataQualityConfig()

    with pytest.raises(TypeError, match="signal_mapping"):
        validate_signal_mapping(object())  # type: ignore[arg-type]


def test_canonical_frame_returns_one_signal_layout_authority() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0],
            "pack_current_a": [1.0],
            "pack_voltage_v": [7.4],
            "cell_2_v": [3.7],
            "cell_1_v": [3.7],
            "temp_1_c": [25.0],
        }
    )
    canonical, layout = canonicalize_analysis_frame(
        frame,
        None,
        ValidationLimits(),
    )

    assert canonical is frame
    assert layout.cell_cols == ["cell_1_v", "cell_2_v"]
    assert layout.temp_cols == ["temp_1_c"]
    assert layout.pack_current_col == "pack_current_a"
    assert layout.pack_voltage_col == "pack_voltage_v"
    assert layout.numeric_cols == [
        "timestamp_s",
        "pack_current_a",
        "pack_voltage_v",
        "cell_1_v",
        "cell_2_v",
        "temp_1_c",
    ]


def test_canonical_frame_enforces_required_pack_signal_for_active_rule() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0],
            "cell_1_v": [3.7],
            "temp_1_c": [25.0],
        }
    )
    with pytest.raises(ValueError, match="Pack-current validation requires"):
        canonicalize_analysis_frame(
            frame,
            None,
            ValidationLimits(
                pack_charge_max_a=100.0,
                pack_current_positive_direction="charge",
            ),
        )


def test_numeric_and_timestamp_validation_helpers_preserve_diagnostics() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [1.0, 0.0],
            "cell_1_v": [3.7, "bad"],
        }
    )
    numeric = frame[["timestamp_s", "cell_1_v"]].apply(pd.to_numeric, errors="coerce")

    with pytest.raises(ValueError, match=r"data row 2 .*column 'cell_1_v'"):
        raise_invalid_numeric_value(frame, numeric)

    timestamps = valid_timestamp_values(frame, numeric)
    assert timestamps.tolist() == [1.0, 0.0]
