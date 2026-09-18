import pandas as pd
import pytest

from batterylog import SignalMapping, SignalPattern
from batterylog.signals import canonicalize_battery_signals


def _mapping(
    *,
    timestamp: str = "Time_s",
    cell_pattern: str = r"BMS_CellVoltage_(?P<index>\d+)",
    temp_pattern: str = r"T_Module_(?P<index>\d+)",
) -> SignalMapping:
    return SignalMapping(
        timestamp=timestamp,
        cell_voltage=SignalPattern(cell_pattern),
        temperature=SignalPattern(temp_pattern),
    )


def test_no_mapping_preserves_canonical_frame() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0],
            "cell_1_v": [3.8],
            "temp_c": [25.0],
        }
    )

    result = canonicalize_battery_signals(frame, None)

    assert result is frame


def test_explicit_mapping_canonicalizes_and_sorts_numeric_indexes() -> None:
    frame = pd.DataFrame(
        {
            "Time_s": [0.0],
            "BMS_CellVoltage_10": [3.90],
            "BMS_CellVoltage_2": [3.80],
            "BMS_CellVoltage_1": [3.70],
            "BMS_CellVoltage_Max": [4.20],
            "T_Module_3": [30.0],
            "T_Module_1": [28.0],
        }
    )

    result = canonicalize_battery_signals(frame, _mapping())

    assert list(result.columns) == [
        "timestamp_s",
        "cell_1_v",
        "cell_2_v",
        "cell_10_v",
        "temp_1_c",
        "temp_3_c",
    ]
    assert result.iloc[0].to_dict() == {
        "timestamp_s": 0.0,
        "cell_1_v": 3.70,
        "cell_2_v": 3.80,
        "cell_10_v": 3.90,
        "temp_1_c": 28.0,
        "temp_3_c": 30.0,
    }


def test_duplicate_logical_indexes_are_rejected() -> None:
    frame = pd.DataFrame(
        {
            "Time_s": [0.0],
            "BMS_CellVoltage_1": [3.8],
            "BMS_CellVoltage_01": [3.9],
            "T_Module_1": [25.0],
        }
    )

    with pytest.raises(ValueError, match="Duplicate logical cell-voltage index 1"):
        canonicalize_battery_signals(frame, _mapping())


def test_ambiguous_sensor_patterns_are_rejected() -> None:
    frame = pd.DataFrame(
        {
            "Time_s": [0.0],
            "Sensor_1": [3.8],
        }
    )
    mapping = _mapping(
        cell_pattern=r"Sensor_(?P<index>\d+)",
        temp_pattern=r"Sensor_(?P<index>\d+)",
    )

    with pytest.raises(ValueError, match="mapping is ambiguous"):
        canonicalize_battery_signals(frame, mapping)


def test_timestamp_cannot_also_match_a_sensor_pattern() -> None:
    frame = pd.DataFrame(
        {
            "Sensor_0": [0.0],
            "Sensor_1": [3.8],
            "T_Module_1": [25.0],
        }
    )
    mapping = _mapping(
        timestamp="Sensor_0",
        cell_pattern=r"Sensor_(?P<index>\d+)",
    )

    with pytest.raises(ValueError, match="also matches a sensor pattern"):
        canonicalize_battery_signals(frame, mapping)


def test_missing_mapped_timestamp_is_rejected() -> None:
    frame = pd.DataFrame(
        {
            "OtherTime": [0.0],
            "BMS_CellVoltage_1": [3.8],
            "T_Module_1": [25.0],
        }
    )

    with pytest.raises(ValueError, match="Mapped timestamp column 'Time_s' is missing"):
        canonicalize_battery_signals(frame, _mapping())


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (
            pd.DataFrame(
                {
                    "Time_s": [0.0],
                    "OtherCell": [3.8],
                    "T_Module_1": [25.0],
                }
            ),
            "matched no cell-voltage columns",
        ),
        (
            pd.DataFrame(
                {
                    "Time_s": [0.0],
                    "BMS_CellVoltage_1": [3.8],
                    "OtherTemp": [25.0],
                }
            ),
            "matched no temperature columns",
        ),
    ],
)
def test_empty_signal_matches_are_rejected(
    frame: pd.DataFrame,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        canonicalize_battery_signals(frame, _mapping())


def test_non_numeric_index_capture_is_rejected() -> None:
    frame = pd.DataFrame(
        {
            "Time_s": [0.0],
            "Cell_A": [3.8],
            "T_Module_1": [25.0],
        }
    )
    mapping = _mapping(cell_pattern=r"Cell_(?P<index>.+)")

    with pytest.raises(ValueError, match="non-numeric index 'A'"):
        canonicalize_battery_signals(frame, mapping)


def test_optional_index_capture_must_participate() -> None:
    frame = pd.DataFrame(
        {
            "Time_s": [0.0],
            "Cell": [3.8],
            "T_Module_1": [25.0],
        }
    )
    mapping = _mapping(cell_pattern=r"Cell(?:_(?P<index>\d+))?")

    with pytest.raises(ValueError, match="non-numeric index None"):
        canonicalize_battery_signals(frame, mapping)


def test_duplicate_source_signal_names_are_rejected() -> None:
    frame = pd.DataFrame(
        [[0.0, 3.8, 3.9, 25.0]],
        columns=["Time_s", "BMS_CellVoltage_1", "BMS_CellVoltage_1", "T_Module_1"],
    )

    with pytest.raises(ValueError, match="Duplicate source signal name"):
        canonicalize_battery_signals(frame, _mapping())


def test_non_string_source_signal_names_are_rejected() -> None:
    frame = pd.DataFrame(
        [[0.0, 3.8, 25.0]],
        columns=[0, "BMS_CellVoltage_1", "T_Module_1"],
    )

    with pytest.raises(TypeError, match="Source signal names must be strings"):
        canonicalize_battery_signals(frame, _mapping(timestamp="0"))
