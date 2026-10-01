from collections.abc import Iterator
from dataclasses import FrozenInstanceError
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from batterylog import (
    AnalysisService,
    DataQualityConfig,
    EventDetectionConfig,
    SignalMapping,
    SignalPattern,
    ValidationConfig,
    ValidationLimits,
    analyze_battery_log,
)
from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.loaders import CsvFileLoader
from batterylog.reporting import render_json_result

GOLDEN_DIR = Path(__file__).with_name("golden")
CASES = [
    (
        b"timestamp_s,temp_c,cell_1_v\n0,25,3.8\n",
        ValidationConfig(),
        "semantic_not_evaluated.json",
    ),
    (
        b"timestamp_s,temp_1_c,temp_2_c,cell_1_v,cell_2_v\n0,25,24,3.8,3.7\n1,56,50,4.3,3.9\n",
        ValidationConfig(
            limits=ValidationLimits(imbalance_max_v=0.08, cell_max_v=4.2, temperature_max_c=55.0),
        ),
        "semantic_multi_rule_fail.json",
    ),
    (
        b"timestamp_s,temp_c,cell_1_v,cell_2_v\n0,25,3.8,3.7\n1,bad,4.5,3.0\n2,26,4.0,3.9\n",
        ValidationConfig(
            limits=ValidationLimits(imbalance_max_v=0.08),
            data_quality=DataQualityConfig("exclude_invalid_rows"),
        ),
        "semantic_data_quality_fail.json",
    ),
]


@pytest.mark.parametrize("data,config,golden_name", CASES)
@pytest.mark.parametrize("entrypoint", ["path", "file", "loader"])
@pytest.mark.parametrize("report_max_points", [None, 14])
def test_service_matches_fixed_serialized_goldens(
    tmp_path, data, config, golden_name, entrypoint, report_max_points
) -> None:
    service = AnalysisService(config)
    if entrypoint == "path":
        source = tmp_path / "input.csv"
        source.write_bytes(data)
        output = service.analyze_path(str(source), report_max_points=report_max_points)
    elif entrypoint == "file":
        handle = BytesIO(data)
        handle.seek(5)
        output = service.analyze_file(handle, report_max_points=report_max_points)
        assert not handle.closed
    else:
        output = service.analyze_loader(
            CsvFileLoader(BytesIO(data), chunk_rows=1), report_max_points=report_max_points
        )

    assert render_json_result(output.result) == (GOLDEN_DIR / golden_name).read_text("utf-8")
    if report_max_points is None:
        assert output.report_series is None
    else:
        assert output.report_series is not None
        assert output.report_series.source_rows == output.result["rows_analyzed"]
        assert len(output.report_series.points) == output.result["rows_analyzed"]


class OnePassLoader:
    source_format = "csv"

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls = 0
        self.mappings: list[SignalMapping | None] = []

    def iter_chunks(self, *, signal_mapping: SignalMapping | None) -> Iterator[pd.DataFrame]:
        self.calls += 1
        assert self.calls == 1, "loader must not be analyzed twice for plots"
        self.mappings.append(signal_mapping)
        yield from CsvFileLoader(BytesIO(self.data), chunk_rows=1).iter_chunks(
            signal_mapping=signal_mapping
        )


@pytest.mark.parametrize("report_max_points", [None, 14])
def test_service_preserves_mapping_gaps_polarity_and_single_pass(report_max_points) -> None:
    mapping = SignalMapping(
        timestamp="Time",
        cell_voltage=SignalPattern(r"C(?P<index>\d+)"),
        temperature=SignalPattern(r"T(?P<index>\d+)"),
        pack_current="Current",
        pack_voltage="Voltage",
    )
    config = ValidationConfig(
        signals=mapping,
        limits=ValidationLimits(
            pack_charge_max_a=10.0,
            pack_discharge_max_a=20.0,
            pack_current_positive_direction="discharge",
            pack_voltage_cell_sum_max_delta_v=0.125,
        ),
        event_detection=EventDetectionConfig(max_gap_s=1.0),
    )
    loader = OnePassLoader(
        b"Time,C1,C2,T1,Current,Voltage\n0,3.5,3.5,25,-15,7.25\n2,3.5,3.5,25,-15,7.25\n"
    )
    result = (
        AnalysisService(config).analyze_loader(loader, report_max_points=report_max_points).result
    )

    assert loader.calls == 1
    assert loader.mappings == [mapping]
    assert result["validation_status"] == "FAIL"
    assert result["signal_mapping"]["timestamp_source"] == "Time"
    assert result["limits_applied"]["pack_current_positive_direction"] == "discharge"
    assert result["analysis_options"] == {"max_event_gap_s": 1.0}
    assert [
        (event["code"], event["start_time_s"], event["sample_count"])
        for event in result["violations"]
    ] == [
        ("PACK_CHARGE_OVERCURRENT", 0.0, 1),
        ("PACK_VOLTAGE_CELL_SUM_MISMATCH", 0.0, 1),
        ("PACK_CHARGE_OVERCURRENT", 2.0, 1),
        ("PACK_VOLTAGE_CELL_SUM_MISMATCH", 2.0, 1),
    ]
    assert [event["measured_value"] for event in result["violations"]] == [-15.0, 0.25, -15.0, 0.25]
    assert [event["limit_value"] for event in result["violations"]] == [-10.0, 0.125, -10.0, 0.125]


def test_service_can_be_reused_without_leaking_results_or_series() -> None:
    service = AnalysisService(ValidationConfig(limits=ValidationLimits(cell_max_v=4.0)))
    first = service.analyze_file(
        BytesIO(b"timestamp_s,cell_1_v,temp_c\n0,4.5,30\n"), report_max_points=14
    )
    second = service.analyze_file(BytesIO(b"timestamp_s,cell_1_v,temp_c\n0,3.5,20\n"))
    assert first.result["validation_status"] == "FAIL"
    assert second.result["validation_status"] == "PASS"
    assert second.result["max_cell_voltage_v"] == 3.5
    assert second.result["violations"] == []
    assert second.report_series is None
    with pytest.raises(FrozenInstanceError):
        service.config = ValidationConfig()


def test_service_rejects_invalid_configuration() -> None:
    with pytest.raises(TypeError, match="config must be a ValidationConfig"):
        AnalysisService(None)


@pytest.mark.parametrize("budget", [True, 13, 0, -1, 14.5, "14"])
def test_invalid_plot_budget_fails_before_consuming_source(budget) -> None:
    loader = OnePassLoader(CASES[0][0])
    with pytest.raises((TypeError, ValueError), match="max_points"):
        AnalysisService().analyze_loader(loader, report_max_points=budget)
    assert loader.calls == 0


def test_service_preserves_strict_errors_and_legacy_python_api(tmp_path) -> None:
    source = tmp_path / "bad.csv"
    source.write_bytes(b"timestamp_s,cell_1_v,temp_c\n0,3.5,bad\n")
    for analyze in (AnalysisService().analyze_path, analyze_battery_log):
        with pytest.raises(ValueError, match=r"data row 1 .*column 'temp_c'"):
            analyze(source)

    source.write_bytes(b"timestamp_s,cell_1_v,temp_c\n0,3.5,25\n")
    limits = ValidationLimits(temperature_max_c=20.0)
    with pytest.warns(DeprecationWarning):
        legacy = analyze_battery_log(source, temp_warning_c=30.0, limits=limits)
    output = AnalysisService(
        ValidationConfig(limits=ValidationLimits(temperature_max_c=30.0))
    ).analyze_path(source)
    assert output.result == legacy


@pytest.mark.parametrize("report_max_points", [None, 14])
def test_service_closes_csv_path_reader_on_error_with_retained_traceback(
    tmp_path, monkeypatch, report_max_points
) -> None:
    source = tmp_path / "bad.csv"
    source.write_bytes(b"timestamp_s,cell_1_v,temp_c\n0,3.5,bad\n")
    handles = []
    original_open = Path.open

    def tracked_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        if path == source:
            handles.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", tracked_open)
    with pytest.raises(ValueError, match="temp_c") as error:
        AnalysisService().analyze_path(source, report_max_points=report_max_points)
    assert error.value.__traceback__ is not None
    assert len(handles) == 1
    assert handles[0].closed


@pytest.mark.parametrize("entrypoint", ["service", "legacy"])
def test_analysis_closes_generator_on_error_without_closing_caller_handle(entrypoint) -> None:
    handle = BytesIO(b"timestamp_s,cell_1_v,temp_c\n0,3.5,bad\n")

    class TrackedLoader:
        source_format = "csv"

        def __init__(self):
            self.finished = False

        def iter_chunks(self, *, signal_mapping):
            try:
                yield from CsvFileLoader(handle).iter_chunks(signal_mapping=signal_mapping)
            finally:
                self.finished = True

    loader = TrackedLoader()
    analyze = (
        AnalysisService().analyze_loader if entrypoint == "service" else analyze_measurement_loader
    )
    with pytest.raises(ValueError, match="temp_c") as error:
        analyze(loader)
    assert error.value.__traceback__ is not None
    assert loader.finished
    assert not handle.closed


def test_service_accepts_iterator_without_close() -> None:
    class ListLoader:
        source_format = "csv"

        def iter_chunks(self, *, signal_mapping):
            return iter([pd.DataFrame({"timestamp_s": [0], "cell_1_v": [3.5], "temp_c": [25]})])

    result = AnalysisService().analyze_loader(ListLoader()).result
    assert result["rows_analyzed"] == 1
    assert result["validation_status"] == "NOT_EVALUATED"
