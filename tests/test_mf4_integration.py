from pathlib import Path

import numpy as np
import pandas as pd
import pytest

asammdf = pytest.importorskip("asammdf", exc_type=ImportError)
from asammdf import MDF, Signal

from batterylog import SignalMapping, SignalPattern, ValidationLimits, analyze_battery_log
from batterylog.__main__ import run

LIMITS = ValidationLimits(
    cell_min_v=2.8,
    cell_max_v=4.2,
    imbalance_max_v=0.08,
    temperature_min_c=-20.0,
    temperature_max_c=55.0,
)


def _save_mdf(path: Path, groups: list[list[Signal]]) -> None:
    mdf = MDF(version="4.10")
    try:
        for signals in groups:
            mdf.append(signals, common_timebase=True)
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()


def _canonical_signals(frame: pd.DataFrame) -> list[Signal]:
    timestamps = frame["timestamp_s"].to_numpy(dtype=float)
    return [
        Signal(frame["cell_1_v"].to_numpy(dtype=float), timestamps, name="cell_1_v", unit="V"),
        Signal(frame["cell_2_v"].to_numpy(dtype=float), timestamps, name="cell_2_v", unit="V"),
        Signal(frame["temp_1_c"].to_numpy(dtype=float), timestamps, name="temp_1_c", unit="degC"),
    ]


def test_real_mf4_matches_equivalent_csv(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0, 3.0],
            "cell_1_v": [3.80, 4.30, 4.31, 3.80],
            "cell_2_v": [3.79, 3.90, 3.89, 3.79],
            "temp_1_c": [25.0, 56.0, 57.0, 25.0],
        }
    )
    csv_path = tmp_path / "equivalent.csv"
    mf4_path = tmp_path / "equivalent.mf4"
    frame.to_csv(csv_path, index=False)
    _save_mdf(mf4_path, [_canonical_signals(frame)])

    csv_result = analyze_battery_log(csv_path, limits=LIMITS)
    mf4_result = analyze_battery_log(mf4_path, limits=LIMITS)

    assert mf4_result == csv_result


def test_real_mf4_legacy_temp_c_matches_equivalent_csv(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0],
            "cell_1_v": [3.80, 4.30, 3.80],
            "cell_2_v": [3.79, 3.90, 3.79],
            "temp_c": [25.0, 56.0, 25.0],
        }
    )
    timestamps = frame["timestamp_s"].to_numpy(dtype=float)
    csv_path = tmp_path / "legacy-temp.csv"
    mf4_path = tmp_path / "legacy-temp.mf4"
    frame.to_csv(csv_path, index=False)
    _save_mdf(
        mf4_path,
        [
            [
                Signal(frame["cell_1_v"].to_numpy(), timestamps, name="cell_1_v", unit="V"),
                Signal(frame["cell_2_v"].to_numpy(), timestamps, name="cell_2_v", unit="V"),
                Signal(frame["temp_c"].to_numpy(), timestamps, name="temp_c", unit="degC"),
            ]
        ],
    )

    csv_result = analyze_battery_log(csv_path, limits=LIMITS)
    mf4_result = analyze_battery_log(mf4_path, limits=LIMITS)

    assert mf4_result == csv_result


def test_real_mf4_vendor_mapping_matches_vendor_csv(tmp_path: Path) -> None:
    timestamps = np.array([10.0, 11.0, 12.0])
    vendor = pd.DataFrame(
        {
            "vendor_time": timestamps,
            "U_Cell_01": [3.80, 4.30, 3.80],
            "U_Cell_02": [3.79, 3.90, 3.79],
            "T_Mod_01": [25.0, 56.0, 25.0],
        }
    )
    mapping = SignalMapping(
        timestamp="vendor_time",
        cell_voltage=SignalPattern(pattern=r"U_Cell_(?P<index>[0-9]+)"),
        temperature=SignalPattern(pattern=r"T_Mod_(?P<index>[0-9]+)"),
    )
    csv_path = tmp_path / "vendor.csv"
    mf4_path = tmp_path / "vendor.mf4"
    vendor.to_csv(csv_path, index=False)
    _save_mdf(
        mf4_path,
        [
            [
                Signal(vendor["U_Cell_01"].to_numpy(), timestamps, name="U_Cell_01", unit="V"),
                Signal(vendor["U_Cell_02"].to_numpy(), timestamps, name="U_Cell_02", unit="V"),
                Signal(vendor["T_Mod_01"].to_numpy(), timestamps, name="T_Mod_01", unit="°C"),
            ]
        ],
    )

    csv_result = analyze_battery_log(csv_path, limits=LIMITS, signal_mapping=mapping)
    mf4_result = analyze_battery_log(mf4_path, limits=LIMITS, signal_mapping=mapping)

    assert mf4_result == csv_result


def test_real_mf4_misaligned_rasters_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "misaligned.mf4"
    cell_time = np.array([0.0, 1.0, 2.0])
    temp_time = np.array([0.0, 2.0])
    _save_mdf(
        path,
        [
            [
                Signal(np.array([3.8, 3.9, 3.8]), cell_time, name="cell_1_v", unit="V"),
                Signal(np.array([3.79, 3.89, 3.79]), cell_time, name="cell_2_v", unit="V"),
            ],
            [Signal(np.array([25.0, 26.0]), temp_time, name="temp_1_c", unit="degC")],
        ],
    )

    with pytest.raises(ValueError, match="Required numeric value is missing or non-numeric"):
        analyze_battery_log(path, limits=LIMITS)


def test_real_mf4_duplicate_channel_name_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.mf4"
    timestamps = np.array([0.0, 1.0])
    _save_mdf(
        path,
        [
            [
                Signal(np.array([3.8, 3.9]), timestamps, name="cell_1_v", unit="V"),
                Signal(np.array([25.0, 26.0]), timestamps, name="temp_1_c", unit="degC"),
            ],
            [Signal(np.array([3.7, 3.8]), timestamps, name="cell_1_v", unit="V")],
        ],
    )

    with pytest.raises(ValueError, match="cell_1_v.*ambiguous"):
        analyze_battery_log(path, limits=LIMITS)


def test_real_mf4_cli_report_uses_file_backed_snapshot(tmp_path: Path, capsys) -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0],
            "cell_1_v": [3.8, 3.9],
            "cell_2_v": [3.79, 3.89],
            "temp_1_c": [25.0, 26.0],
        }
    )
    mf4_path = tmp_path / "report.mf4"
    report_path = tmp_path / "report.html"
    _save_mdf(mf4_path, [_canonical_signals(frame)])

    exit_code = run(
        [
            str(mf4_path),
            "--cell-max-v",
            "5.0",
            "--report",
            str(report_path),
        ]
    )

    assert exit_code == 0
    assert '"validation_status": "PASS"' in capsys.readouterr().out
    assert report_path.exists()
    html = report_path.read_text(encoding="utf-8")
    assert mf4_path.name in html
    assert html.count('class="timeseries-chart"') == 3
    assert "Cell-voltage envelope" in html
