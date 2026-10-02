import hashlib
import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from batterylog import (
    AnalysisService,
    DataQualityConfig,
    SourceUnits,
    ValidationConfig,
    ValidationLimits,
    normalize_measurement,
)
from batterylog import normalization as module
from batterylog.__main__ import run

UNITS = SourceUnits("ms", "mV", "K", "mA", "mV")
HEADER = "timestamp_s,cell_1_v,cell_2_v,temp_c,pack_current_a,pack_voltage_v,ignored\n"
DATA = HEADER + "10000,3500,3600,298.15,-1500,7100,abc\n11000,4300,3900,328.15,2000,8200,def\n"


def _source(tmp_path, text=DATA):
    path = tmp_path / "input.csv"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("chunk_rows", [1, 2, 100])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_converted_csv_matches_independent_values_and_analysis(
    tmp_path, monkeypatch, chunk_rows, newline
):
    monkeypatch.setattr(module, "DEFAULT_CSV_CHUNK_ROWS", chunk_rows)
    source = _source(tmp_path)
    source.write_bytes(DATA.replace("\n", newline).encode("utf-8"))
    source_bytes = source.read_bytes()
    destination = tmp_path / "prepared"
    result = normalize_measurement(source, destination, units=UNITS)
    output = destination / "normalized.csv"
    actual = pd.read_csv(output)
    expected = pd.DataFrame(
        {
            "timestamp_s": [10.0, 11.0],
            "pack_current_a": [-1.5, 2.0],
            "pack_voltage_v": [7.1, 8.2],
            "cell_1_v": [3.5, 4.3],
            "cell_2_v": [3.6, 3.9],
            "temp_c": [25.0, 55.0],
        }
    )
    pd.testing.assert_frame_equal(actual, expected)
    assert result["rows_written"] == 2
    assert result["analysis_performed"] is False
    assert result["source"]["sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert result["normalized_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert json.loads((destination / "conversion.json").read_text()) == result
    assert source.read_bytes() == source_bytes
    assert len(result["conversions"]) == 6
    temperature = next(item for item in result["conversions"] if item["canonical"] == "temp_c")
    assert temperature == {
        "source": "temp_c",
        "canonical": "temp_c",
        "source_unit": "K",
        "target_unit": "degC",
        "divisor": 1.0,
        "offset": -273.15,
    }
    reference = tmp_path / "reference.csv"
    reference.write_text(
        "timestamp_s,pack_current_a,pack_voltage_v,cell_1_v,cell_2_v,temp_c\n"
        "10,-1.5,7.1,3.5,3.6,25\n11,2,8.2,4.3,3.9,55\n",
        encoding="utf-8",
    )
    service = AnalysisService(ValidationConfig(limits=ValidationLimits(cell_max_v=4.2)))
    assert service.analyze_path(output).result == service.analyze_path(reference).result


@pytest.mark.parametrize(
    "time_unit, times", [("s", "1,2"), ("ms", "1000,2000"), ("us", "1000000,2000000")]
)
def test_declared_time_units_and_identity_sensor_units(tmp_path, time_unit, times):
    a, b = times.split(",")
    source = _source(tmp_path, f"timestamp_s,cell_1_v,temp_c\n{a},3.5,25\n{b},3.6,26\n")
    result = normalize_measurement(
        source, tmp_path / "out", units=SourceUnits(time_unit, "V", "degC")
    )
    frame = pd.read_csv(tmp_path / "out/normalized.csv")
    assert frame["timestamp_s"].tolist() == [1.0, 2.0]
    assert frame["temp_c"].tolist() == [25.0, 26.0]
    assert result["rows_written"] == 2


@pytest.mark.parametrize(
    "change",
    [
        {"timestamp": "min"},
        {"cell_voltage": "MV"},
        {"temperature": "degF"},
        {"pack_current": "kA"},
        {"pack_voltage": "mv"},
        {"timestamp": None},
        {"cell_voltage": 1},
    ],
)
def test_unsupported_units_are_rejected(change):
    with pytest.raises((ValueError, TypeError)):
        replace(UNITS, **change)


@pytest.mark.parametrize("bad_value", ["", "bad", "True", "NaN", "inf", "1+2j"])
def test_invalid_values_are_not_repaired_even_in_exclusion_mode(tmp_path, bad_value):
    source = _source(tmp_path, f"timestamp_s,cell_1_v,temp_c\n0,{bad_value},298.15\n")
    with pytest.raises(ValueError):
        normalize_measurement(
            source,
            tmp_path / "out",
            units=SourceUnits("ms", "mV", "K"),
            config=ValidationConfig(data_quality=DataQualityConfig("exclude_invalid_rows")),
        )
    assert not (tmp_path / "out").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["input.csv"]


@pytest.mark.parametrize("chunk_rows", [1, 2, 100])
def test_timestamp_regression_is_rejected_across_chunks(tmp_path, monkeypatch, chunk_rows):
    monkeypatch.setattr(module, "DEFAULT_CSV_CHUNK_ROWS", chunk_rows)
    source = _source(tmp_path, "timestamp_s,cell_1_v,temp_c\n2000,3500,298.15\n1000,3500,298.15\n")
    with pytest.raises(ValueError, match="non-decreasing"):
        normalize_measurement(source, tmp_path / "out", units=SourceUnits("ms", "mV", "K"))
    assert not (tmp_path / "out").exists()


def test_source_regression_cannot_be_hidden_by_scaling_rounding(tmp_path, monkeypatch):
    a = 2199023255550.9998
    b = 2199023255550.9995
    assert a > b and a / 1000 == b / 1000
    source = _source(tmp_path)

    def chunks(*args, **kwargs):
        yield pd.DataFrame(
            {"timestamp_s": [a, b], "cell_1_v": [3500, 3500], "temp_c": [298.15, 298.15]}
        )

    monkeypatch.setattr(module, "iter_battery_csv_file", chunks)
    with pytest.raises(ValueError, match="Source timestamps"):
        normalize_measurement(source, tmp_path / "out", units=SourceUnits("ms", "mV", "K"))


def test_subnormal_conversion_underflow_is_rejected(tmp_path, monkeypatch):
    source = _source(tmp_path)

    def chunks(*args, **kwargs):
        yield pd.DataFrame(
            {"timestamp_s": [0.0], "cell_1_v": [np.nextafter(0.0, 1.0)], "temp_c": [298.15]}
        )

    monkeypatch.setattr(module, "iter_battery_csv_file", chunks)
    with pytest.raises(ValueError, match="underflow"):
        normalize_measurement(source, tmp_path / "out", units=SourceUnits("ms", "mV", "K"))


@pytest.mark.parametrize(
    "text, issue",
    [
        ("timestamp_s,cell_1_v,temp_c\n", "no data rows"),
        ("timestamp_s,cell_1_v,temp_c\n0,3500,298.15,extra\n", "Invalid CSV structure"),
        ("timestamp_s,cell_1_v,cell_1_v,temp_c\n0,3500,3500,298.15\n", "Duplicate CSV"),
    ],
)
def test_structure_errors_do_not_publish_output(tmp_path, text, issue):
    source = _source(tmp_path, text)
    with pytest.raises(ValueError, match=issue):
        normalize_measurement(source, tmp_path / "out", units=SourceUnits("ms", "mV", "K"))
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "units", [replace(UNITS, pack_current=None), replace(UNITS, pack_voltage=None)]
)
def test_present_pack_channels_require_explicit_units(tmp_path, units):
    with pytest.raises(ValueError, match="Declare a unit"):
        normalize_measurement(_source(tmp_path), tmp_path / "out", units=units)


def test_absent_pack_channel_rejects_unused_declaration(tmp_path):
    source = _source(tmp_path, "timestamp_s,cell_1_v,temp_c\n0,3500,298.15\n")
    with pytest.raises(ValueError, match="Declare a unit"):
        normalize_measurement(source, tmp_path / "out", units=UNITS)


@pytest.mark.parametrize("existing", ["directory", "file"])
def test_existing_destination_is_preserved(tmp_path, existing):
    source = _source(tmp_path)
    out = tmp_path / "out"
    if existing == "directory":
        out.mkdir()
        (out / "keep").write_text("keep")
    else:
        out.write_text("keep")
    with pytest.raises(ValueError, match="new output directory"):
        normalize_measurement(source, out, units=UNITS)
    assert ((out / "keep") if out.is_dir() else out).read_text() == "keep"


@pytest.mark.parametrize("exception", [OSError, KeyboardInterrupt])
def test_output_failure_or_interrupt_closes_reader_and_removes_staging(
    tmp_path, monkeypatch, exception
):
    source = _source(tmp_path)
    closed = []
    original = module.iter_battery_csv_file

    def tracked(*args, **kwargs):
        try:
            yield from original(*args, **kwargs)
        finally:
            closed.append(True)

    def fail(*args, **kwargs):
        raise exception("test interruption")

    monkeypatch.setattr(module, "iter_battery_csv_file", tracked)
    monkeypatch.setattr(pd.DataFrame, "to_csv", fail)
    with pytest.raises(exception) as error:
        normalize_measurement(source, tmp_path / "out", units=UNITS)
    assert error.value.__traceback__ is not None
    assert closed == [True]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["input.csv"]


def test_source_change_prevents_publication(tmp_path, monkeypatch):
    source = _source(tmp_path)
    original = module.sha256_file

    def mutate(path):
        source.write_text("changed")
        return original(path)

    monkeypatch.setattr(module, "sha256_file", mutate)
    with pytest.raises(ValueError, match="changed during analysis"):
        normalize_measurement(source, tmp_path / "out", units=UNITS)
    assert not (tmp_path / "out").exists()


def test_cli_mapping_config_evidence_and_separate_normalization_result(tmp_path, capsys):
    source = _source(tmp_path, "clock,U_01,T_01\n1000,3500,298.15\n")
    config = tmp_path / "mapping.yaml"
    config.write_text(
        "schema_version: 6\nsignals:\n  timestamp: clock\n  cell_voltage:\n"
        "    pattern: 'U_(?P<index>\\d+)'\n  temperature:\n    pattern: 'T_(?P<index>\\d+)'\n"
        "limits:\n  cell_voltage:\n    max_v: 3\n",
        encoding="utf-8",
    )
    arguments = [
        str(source),
        "--normalize",
        "--config",
        str(config),
        "--time-unit",
        "ms",
        "--cell-voltage-unit",
        "mV",
        "--temperature-unit",
        "K",
        "--output-dir",
        str(tmp_path / "out"),
    ]
    assert run(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["analysis_performed"] is False
    assert result["config"]["sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert result["conversions"][1]["source"] == "U_01"
    output = tmp_path / "out/normalized.csv"
    assert run([str(output), "--cell-max-v", "3"]) == 1
    assert json.loads(capsys.readouterr().out)["validation_status"] == "FAIL"


@pytest.mark.parametrize(
    "options",
    [
        ["--normalize"],
        ["--time-unit", "s"],
        ["--normalize", "--batch"],
        ["--normalize", "--inspect"],
        ["--normalize", "--time-unit", "min"],
        [
            "--normalize",
            "--output-dir",
            "out",
            "--time-unit",
            "s",
            "--cell-voltage-unit",
            "V",
            "--temperature-unit",
            "degC",
            "--report",
            "out.html",
        ],
    ],
)
def test_cli_rejects_incomplete_or_conflicting_options(tmp_path, capsys, options):
    assert run([str(tmp_path / "missing.csv"), *options]) == 2
    assert capsys.readouterr().out == ""
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("invalid", ["units", "config"])
def test_api_rejects_incorrect_types(tmp_path, invalid):
    kwargs = {"units": UNITS, "config": ValidationConfig()}
    kwargs[invalid] = {}
    with pytest.raises(TypeError):
        normalize_measurement(tmp_path / "input.csv", tmp_path / "out", **kwargs)
