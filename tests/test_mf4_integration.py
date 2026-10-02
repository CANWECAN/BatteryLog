import json
import runpy
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

asammdf = pytest.importorskip("asammdf", exc_type=ImportError)
from asammdf import MDF, Signal

from batterylog import (
    AnalysisService,
    DataQualityConfig,
    SignalMapping,
    SignalPattern,
    ValidationConfig,
    ValidationLimits,
    analyze_battery_log,
    analyze_directory,
    inspect_measurement,
)
from batterylog.__main__ import run
from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.loaders import MdfPathLoader
from batterylog.loaders import mf4 as mf4_module
from batterylog.reporting import render_json_result

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("layout", ["single-group", "multi-group"])
@pytest.mark.parametrize("scenario", ["steady", "event-pressure"])
def test_benchmark_sources_have_independent_event_counts(tmp_path, layout, scenario) -> None:
    benchmark = runpy.run_path(str(ROOT / "benchmarks/benchmark_mf4_analysis.py"))
    path = tmp_path / "benchmark.mf4"
    benchmark["_write_synthetic_mf4"](
        path,
        rows=5,
        cells=2,
        temperatures=1,
        layout=layout,
        scenario=scenario,
    )
    result = analyze_battery_log(path, limits=LIMITS)
    assert result["rows_analyzed"] == 5
    assert result["rows_excluded"] == 0
    assert result["validation_status"] == ("PASS" if scenario == "steady" else "FAIL")
    expected = 3 if scenario == "event-pressure" else 0
    assert sum(e["code"] == "CELL_OVERVOLTAGE" for e in result["violations"]) == expected
    assert sum(e["code"] == "CELL_IMBALANCE_HIGH" for e in result["violations"]) == expected


LIMITS = ValidationLimits(
    cell_min_v=2.8,
    cell_max_v=4.2,
    imbalance_max_v=0.08,
    temperature_min_c=-20.0,
    temperature_max_c=55.0,
)
CURRENT_LIMITS = ValidationLimits(
    cell_min_v=2.8,
    cell_max_v=4.2,
    imbalance_max_v=0.08,
    temperature_min_c=-20.0,
    temperature_max_c=55.0,
    pack_charge_max_a=15.0,
    pack_discharge_max_a=30.0,
    pack_current_positive_direction="discharge",
)


def _save_mdf(path: Path, groups: list[list[Signal]]) -> None:
    mdf = MDF(version="4.10")
    try:
        for signals in groups:
            mdf.append(signals, common_timebase=True)
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()


@pytest.mark.parametrize("layout", ["single-group", "multi-group"])
@pytest.mark.parametrize("voltage_unit", ["V", "mV"])
def test_real_mf4_inspection_checks_metadata_without_decoding(
    tmp_path, monkeypatch, capsys, layout, voltage_unit
):
    source = tmp_path / "inspect.mf4"
    timestamps = np.array([0.0, 1.0])
    voltage = Signal(np.array([3.5, np.nan]), timestamps, name="cell_1_v", unit=voltage_unit)
    temperature = Signal(np.array([25.0, 25.0]), timestamps, name="temp_c", unit="degC")
    _save_mdf(
        source, [[voltage, temperature]] if layout == "single-group" else [[voltage], [temperature]]
    )
    original = source.read_bytes()
    backend, exception = mf4_module._load_asammdf()
    exits = []

    class MetadataOnlyMDF(backend):
        def select(self, *args, **kwargs):
            raise AssertionError("inspection must not decode samples")

        get_master = select
        iter_to_dataframe = select

        def __exit__(self, *args):
            super().__exit__(*args)
            exits.append(self)

    monkeypatch.setattr(mf4_module, "_load_asammdf", lambda: (MetadataOnlyMDF, exception))
    result = inspect_measurement(source)
    expected = "OK" if voltage_unit == "V" else "ISSUES"
    assert result["metadata_status"] == expected
    assert result["analysis_performed"] is False
    assert {item["name"] for item in result["channels"]} >= {"time", "cell_1_v", "temp_c"}
    cell = next(item for item in result["channels"] if item["name"] == "cell_1_v")
    assert cell["unit"] == voltage_unit
    assert run([str(source), "--inspect"]) == (0 if voltage_unit == "V" else 4)
    assert json.loads(capsys.readouterr().out) == result
    assert len(exits) == 2
    assert source.read_bytes() == original
    monkeypatch.setattr(mf4_module, "_load_asammdf", lambda: (backend, exception))
    with pytest.raises(ValueError, match="missing|unit"):
        AnalysisService().analyze_path(source)


@pytest.mark.parametrize("entrypoint", ["path", "file"])
@pytest.mark.parametrize("report_max_points", [None, 20])
def test_real_mf4_context_exits_after_analysis_failure(
    tmp_path, monkeypatch, entrypoint, report_max_points
):
    source = tmp_path / "invalid.mf4"
    timestamps = np.array([0.0, 1.0])
    _save_mdf(
        source,
        [
            [
                Signal(np.array([3.5, np.nan]), timestamps, name="cell_1_v", unit="V"),
                Signal(np.array([25.0, 25.0]), timestamps, name="temp_c", unit="degC"),
            ]
        ],
    )
    backend, exception = mf4_module._load_asammdf()
    exits = []

    class TrackedMDF(backend):
        def __exit__(self, exc_type, exc, tb):
            super().__exit__(exc_type, exc, tb)
            exits.append(self)

    monkeypatch.setattr(mf4_module, "_load_asammdf", lambda: (TrackedMDF, exception))
    with source.open("rb") as handle:
        with pytest.raises(ValueError, match="cell_1_v") as error:
            if entrypoint == "path":
                AnalysisService().analyze_path(source, report_max_points=report_max_points)
            else:
                AnalysisService().analyze_file(
                    handle, source_name=source.name, report_max_points=report_max_points
                )
        assert error.value.__traceback__ is not None
        assert len(exits) == 1
        assert not handle.closed


@pytest.mark.parametrize("chunk_ram_bytes", [64, 1024 * 1024])
def test_real_mf4_matches_independent_all_rule_boundary_golden(
    tmp_path: Path, chunk_ram_bytes: int
) -> None:
    timestamps = np.array([0.0, 1.0])
    channels = [
        ("pack_current_a", "A", [10.0, -15.0]),
        ("pack_voltage_v", "V", [7.0, 8.75]),
        ("cell_1_v", "V", [3.0, 4.25]),
        ("cell_2_v", "V", [4.0, 4.25]),
        ("temp_1_c", "degC", [-20.0, 50.0]),
        ("temp_2_c", "degC", [-10.0, 50.0]),
    ]
    source = tmp_path / "boundary-golden.mf4"
    _save_mdf(
        source,
        [
            [
                Signal(np.array(values), timestamps, name=name, unit=unit)
                for name, unit, values in channels
            ]
        ],
    )
    limits = ValidationLimits(
        cell_min_v=3.0,
        cell_max_v=4.25,
        imbalance_max_v=1.0,
        temperature_min_c=-20.0,
        temperature_max_c=50.0,
        temperature_spread_max_c=10.0,
        pack_charge_max_a=10.0,
        pack_discharge_max_a=15.0,
        pack_current_positive_direction="charge",
        pack_voltage_cell_sum_max_delta_v=0.25,
    )
    expected = (ROOT / "tests/golden/semantic_all_rules_pass.json").read_text(encoding="utf-8")
    result = analyze_measurement_loader(
        MdfPathLoader(source, chunk_ram_bytes=chunk_ram_bytes), limits=limits
    )

    # The oracle is fixed JSON, not equivalent CSV analyzed by the same kernel.
    assert render_json_result(result) == expected


def test_real_mf4_batch_matches_single_file_results_and_csv(tmp_path):
    from batterylog import AnalysisService, ValidationConfig

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "measurement.mf4"
    timestamps = np.array([0.0, 1.0])
    _save_mdf(
        source,
        [
            [
                Signal(np.array([3.5, 4.5]), timestamps, name="cell_1_v", unit="V"),
                Signal(np.array([25.0, 25.0]), timestamps, name="temp_c", unit="degC"),
            ]
        ],
    )
    (inputs / "measurement.csv").write_text(
        "timestamp_s,cell_1_v,temp_c\n0,3.5,25\n1,4.5,25\n", encoding="utf-8"
    )
    out = tmp_path / "results"
    service = AnalysisService(ValidationConfig(limits=ValidationLimits(cell_max_v=4.2)))
    summary = analyze_directory(inputs, out, service=service)

    assert [item["status"] for item in summary["files"]] == ["FAIL", "FAIL"]
    results = [json.loads((out / item["result_json"]).read_text()) for item in summary["files"]]
    assert results[0] == results[1] == service.analyze_path(source).result
    assert results[0]["violations"][0]["sample_count"] == 1
    assert all((out / item["report_html"]).is_file() for item in summary["files"])


def _canonical_signals(frame: pd.DataFrame) -> list[Signal]:
    timestamps = frame["timestamp_s"].to_numpy(dtype=float)
    signals: list[Signal] = []
    if "pack_current_a" in frame:
        signals.append(
            Signal(
                frame["pack_current_a"].to_numpy(dtype=float),
                timestamps,
                name="pack_current_a",
                unit="A",
            )
        )
    if "pack_voltage_v" in frame:
        signals.append(
            Signal(
                frame["pack_voltage_v"].to_numpy(dtype=float),
                timestamps,
                name="pack_voltage_v",
                unit="V",
            )
        )
    signals.extend(
        [
            Signal(
                frame["cell_1_v"].to_numpy(dtype=float),
                timestamps,
                name="cell_1_v",
                unit="V",
            ),
            Signal(
                frame["cell_2_v"].to_numpy(dtype=float),
                timestamps,
                name="cell_2_v",
                unit="V",
            ),
            Signal(
                frame["temp_1_c"].to_numpy(dtype=float),
                timestamps,
                name="temp_1_c",
                unit="degC",
            ),
        ]
    )
    return signals


@pytest.mark.parametrize("entrypoint", ["path", "file", "loader"])
@pytest.mark.parametrize("report_max_points", [None, 14])
def test_real_mf4_service_matches_fixed_golden(tmp_path, entrypoint, report_max_points) -> None:
    path = tmp_path / "generated.mf4"
    timestamps = np.array([0.0, 1.0])
    _save_mdf(
        path,
        [
            [
                Signal(np.array([3.8, 4.3]), timestamps, name="cell_1_v", unit="V"),
                Signal(np.array([3.7, 3.9]), timestamps, name="cell_2_v", unit="V"),
                Signal(np.array([25.0, 56.0]), timestamps, name="temp_1_c", unit="degC"),
                Signal(np.array([24.0, 50.0]), timestamps, name="temp_2_c", unit="degC"),
            ]
        ],
    )
    # The writer normalizes its output suffix; rename an existing fixture to
    # exercise case-insensitive source dispatch without guessing the save name.
    path = path.rename(tmp_path / "service.MF4")
    service = AnalysisService(
        ValidationConfig(
            limits=ValidationLimits(
                imbalance_max_v=0.08,
                cell_max_v=4.2,
                temperature_max_c=55.0,
            )
        )
    )
    if entrypoint == "path":
        output = service.analyze_path(path, report_max_points=report_max_points)
    elif entrypoint == "file":
        with path.open("rb") as handle:
            handle.seek(7)
            output = service.analyze_file(
                handle, source_name=path.name, report_max_points=report_max_points
            )
            assert not handle.closed
    else:
        output = service.analyze_loader(
            MdfPathLoader(path, chunk_ram_bytes=64), report_max_points=report_max_points
        )

    expected = (ROOT / "tests/golden/semantic_multi_rule_fail.json").read_text("utf-8")
    assert render_json_result(output.result) == expected
    if report_max_points is None:
        assert output.report_series is None
    else:
        assert output.report_series is not None
        assert output.report_series.source_rows == 2
        assert len(output.report_series.points) == 2


def test_real_mf4_matches_equivalent_csv(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0, 3.0],
            "pack_current_a": [-20.0, -5.0, 10.0, 35.0],
            "pack_voltage_v": [398.0, 400.0, 403.0, 405.0],
            "cell_1_v": [3.80, 4.30, 4.31, 3.80],
            "cell_2_v": [3.79, 3.90, 3.89, 3.79],
            "temp_1_c": [25.0, 56.0, 57.0, 25.0],
        }
    )
    csv_path = tmp_path / "equivalent.csv"
    mf4_path = tmp_path / "equivalent.mf4"
    frame.to_csv(csv_path, index=False)
    _save_mdf(mf4_path, [_canonical_signals(frame)])

    csv_result = analyze_battery_log(csv_path, limits=CURRENT_LIMITS)
    mf4_result = analyze_battery_log(mf4_path, limits=CURRENT_LIMITS)

    assert mf4_result == csv_result
    assert {event["code"] for event in mf4_result["violations"]} >= {
        "PACK_CHARGE_OVERCURRENT",
        "PACK_DISCHARGE_OVERCURRENT",
    }
    assert mf4_result["min_pack_current_a"] == -20.0
    assert mf4_result["max_pack_current_a"] == 35.0
    assert mf4_result["min_pack_voltage_v"] == 398.0
    assert mf4_result["max_pack_voltage_v"] == 405.0


def test_pack_voltage_cell_sum_rule_matches_real_mf4_and_csv(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0, 3.0],
            "cell_1_v": [3.5] * 4,
            "cell_2_v": [3.5] * 4,
            "temp_1_c": [25.0] * 4,
            "pack_voltage_v": [7.0, 7.25, 7.25, 7.0],
        }
    )
    csv_path = tmp_path / "cell-sum.csv"
    mf4_path = tmp_path / "cell-sum.mf4"
    frame.to_csv(csv_path, index=False)
    _save_mdf(mf4_path, [_canonical_signals(frame)])
    limits = ValidationLimits(pack_voltage_cell_sum_max_delta_v=0.125)

    expected = analyze_battery_log(csv_path, limits=limits)
    actual = analyze_battery_log(mf4_path, limits=limits)
    assert actual == expected
    assert actual["violations"][0]["sample_count"] == 2
    assert actual["violations"][0]["signed_error_v"] == 0.25


def test_real_mf4_single_group_multichunk_matches_csv(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": np.arange(12, dtype=float),
            "cell_1_v": [3.80, 3.81, 4.30, 4.31, 3.82, 3.81, 3.80, 3.79, 3.78, 3.80, 3.81, 3.80],
            "cell_2_v": [3.79, 3.80, 3.90, 3.89, 3.81, 3.80, 3.79, 3.78, 3.77, 3.79, 3.80, 3.79],
            "temp_1_c": [25.0, 25.5, 56.0, 57.0, 30.0, 29.0, 28.0, 27.0, 26.0, 25.0, 24.0, 25.0],
        }
    )
    csv_path = tmp_path / "multichunk.csv"
    mf4_path = tmp_path / "multichunk.mf4"
    frame.to_csv(csv_path, index=False)
    _save_mdf(mf4_path, [_canonical_signals(frame)])

    csv_result = analyze_battery_log(csv_path, limits=LIMITS)
    mf4_result = analyze_measurement_loader(
        MdfPathLoader(mf4_path, chunk_ram_bytes=64),
        limits=LIMITS,
    )

    assert mf4_result == csv_result


def test_real_mf4_single_group_invalidation_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "invalid-sample.mf4"
    timestamps = np.array([0.0, 1.0, 2.0])
    invalid = np.array([False, True, False])
    _save_mdf(
        path,
        [
            [
                Signal(
                    np.array([3.8, 9.9, 3.8]),
                    timestamps,
                    name="cell_1_v",
                    unit="V",
                    invalidation_bits=invalid,
                ),
                Signal(np.array([3.79, 3.79, 3.79]), timestamps, name="cell_2_v", unit="V"),
                Signal(np.array([25.0, 25.0, 25.0]), timestamps, name="temp_1_c", unit="degC"),
            ]
        ],
    )

    with pytest.raises(ValueError, match="Required numeric value is missing or non-numeric"):
        analyze_battery_log(path, limits=LIMITS)


def test_real_mf4_boolean_measurement_is_non_numeric(tmp_path: Path) -> None:
    path = tmp_path / "boolean-sample.mf4"
    timestamps = np.array([0.0])
    _save_mdf(
        path,
        [
            [
                Signal(np.array([True]), timestamps, name="cell_1_v", unit="V"),
                Signal(np.array([3.79]), timestamps, name="cell_2_v", unit="V"),
                Signal(np.array([25.0]), timestamps, name="temp_1_c", unit="degC"),
            ]
        ],
    )

    with pytest.raises(ValueError, match="Required numeric value is missing or non-numeric"):
        analyze_battery_log(path, limits=LIMITS)

    result = analyze_battery_log(
        path,
        limits=LIMITS,
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )
    assert result["validation_status"] == "FAIL"
    assert result["rows_analyzed"] == 0
    assert result["rows_excluded"] == 1
    assert result["data_quality"]["events"] == [
        {
            "code": "NON_NUMERIC_REQUIRED_VALUE",
            "start_row": 1,
            "end_row": 1,
            "signals": ["cell_1_v"],
            "affected_values": 1,
        }
    ]


def test_real_mf4_invalidation_can_be_excluded_with_structured_evidence(tmp_path: Path) -> None:
    path = tmp_path / "invalid-sample-excluded.mf4"
    timestamps = np.array([0.0, 1.0, 2.0])
    invalid = np.array([False, True, False])
    _save_mdf(
        path,
        [
            [
                Signal(
                    np.array([3.8, 9.9, 3.8]),
                    timestamps,
                    name="cell_1_v",
                    unit="V",
                    invalidation_bits=invalid,
                ),
                Signal(np.array([3.79, 3.79, 3.79]), timestamps, name="cell_2_v", unit="V"),
                Signal(np.array([25.0, 25.0, 25.0]), timestamps, name="temp_1_c", unit="degC"),
            ]
        ],
    )

    result = analyze_battery_log(
        path,
        limits=LIMITS,
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )

    assert result["validation_status"] == "FAIL"
    assert result["rows_input"] == 3
    assert result["rows_analyzed"] == 2
    assert result["rows_excluded"] == 1
    assert result["data_quality"]["events"] == [
        {
            "code": "MISSING_REQUIRED_VALUE",
            "start_row": 2,
            "end_row": 2,
            "signals": ["cell_1_v"],
            "affected_values": 1,
        }
    ]
    assert result["max_cell_voltage_v"] == pytest.approx(3.8)


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
            "PackCurrent": [-20.0, 0.0, 35.0],
            "PackVoltage": [398.0, 401.0, 405.0],
            "U_Cell_01": [3.80, 4.30, 3.80],
            "U_Cell_02": [3.79, 3.90, 3.79],
            "T_Mod_01": [25.0, 56.0, 25.0],
        }
    )
    mapping = SignalMapping(
        timestamp="vendor_time",
        cell_voltage=SignalPattern(pattern=r"U_Cell_(?P<index>[0-9]+)"),
        temperature=SignalPattern(pattern=r"T_Mod_(?P<index>[0-9]+)"),
        pack_current="PackCurrent",
        pack_voltage="PackVoltage",
    )
    csv_path = tmp_path / "vendor.csv"
    mf4_path = tmp_path / "vendor.mf4"
    vendor.to_csv(csv_path, index=False)
    _save_mdf(
        mf4_path,
        [
            [
                Signal(
                    vendor["PackCurrent"].to_numpy(),
                    timestamps,
                    name="PackCurrent",
                    unit="ampere",
                ),
                Signal(
                    vendor["PackVoltage"].to_numpy(),
                    timestamps,
                    name="PackVoltage",
                    unit="volt",
                ),
                Signal(vendor["U_Cell_01"].to_numpy(), timestamps, name="U_Cell_01", unit="V"),
                Signal(vendor["U_Cell_02"].to_numpy(), timestamps, name="U_Cell_02", unit="V"),
                Signal(vendor["T_Mod_01"].to_numpy(), timestamps, name="T_Mod_01", unit="°C"),
            ]
        ],
    )

    csv_result = analyze_battery_log(
        csv_path,
        limits=CURRENT_LIMITS,
        signal_mapping=mapping,
    )
    mf4_result = analyze_battery_log(
        mf4_path,
        limits=CURRENT_LIMITS,
        signal_mapping=mapping,
    )

    assert mf4_result == csv_result
    assert mf4_result["signal_mapping"]["pack_current_source"] == "PackCurrent"
    assert mf4_result["signal_mapping"]["pack_voltage_source"] == "PackVoltage"


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


@pytest.mark.parametrize("layout", ["single-group", "multi-group"])
@pytest.mark.parametrize("scenario", ["steady", "event-pressure"])
def test_mf4_benchmark_smoke_exercises_analysis_and_report_paths(
    tmp_path: Path, layout: str, scenario: str
) -> None:
    json_path = tmp_path / "benchmark.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "benchmarks" / "benchmark_mf4_analysis.py"),
            "--layout",
            layout,
            "--scenario",
            scenario,
            "--rows",
            "40",
            "80",
            "--cells",
            "4",
            "--temperatures",
            "2",
            "--modes",
            "analysis",
            "report",
            "--sample-interval-ms",
            "5",
            "--repeats",
            "1",
            "--json-out",
            str(json_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "channels=4 cells + 2 temperatures" in completed.stdout
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["repeats"] == 1
    assert payload["environment"]["cells"] == 4
    assert payload["environment"]["temperature_sensors"] == 2

    cases = payload["cases"]
    assert len(cases) == 4
    assert {(case["rows"], case["mode"]) for case in cases} == {
        (40, "analysis"),
        (40, "report"),
        (80, "analysis"),
        (80, "report"),
    }
    for case in cases:
        assert case["status"] == ("FAIL" if scenario == "event-pressure" else "PASS")
        assert case["layout"] == layout
        assert case["scenario"] == scenario
        assert case["events_by_rule"] == (
            {"CELL_OVERVOLTAGE": case["rows"] // 2, "CELL_IMBALANCE_HIGH": case["rows"] // 2}
            if scenario == "event-pressure"
            else {}
        )
        assert case["cells"] == 4
        assert case["temperature_sensors"] == 2
        assert case["elapsed_s"] > 0.0
        assert case["rows_per_s"] > 0.0
        assert case["mf4_bytes"] > 0
        assert case["rss_baseline_bytes"] > 0
        assert case["rss_peak_sampled_bytes"] >= case["rss_baseline_bytes"]
        assert case["rss_delta_sampled_bytes"] >= 0
        if case["rss_peak_native_bytes"] is not None:
            assert case["rss_peak_native_bytes"] > 0
            assert case["rss_delta_native_bytes"] >= 0
        else:
            assert case["rss_delta_native_bytes"] is None
        if case["mode"] == "report":
            assert case["report_bytes"] > 0
        else:
            assert case["report_bytes"] is None
