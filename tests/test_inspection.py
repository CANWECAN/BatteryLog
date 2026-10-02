import json
from typing import ClassVar

import pytest

from batterylog import (
    AnalysisService,
    SignalMapping,
    SignalPattern,
    ValidationConfig,
    ValidationLimits,
    inspect_measurement,
)
from batterylog.__main__ import run
from batterylog.loaders import mf4


def _vendor_config():
    return ValidationConfig(
        signals=SignalMapping(
            timestamp="clock",
            cell_voltage=SignalPattern(r"U_(?P<index>\d+)"),
            temperature=SignalPattern(r"T_(?P<index>\d+)"),
        )
    )


def test_csv_inspection_uses_header_only_and_does_not_change_files(tmp_path, monkeypatch):
    from batterylog.loaders import csv as csv_module

    source = tmp_path / "capture.csv"
    data = b"\xef\xbb\xbftimestamp_s,cell_2_v,cell_1_v,temp_c,notes\n0,broken,3.5,25,extra,field\n"
    source.write_bytes(data)
    before = sorted(tmp_path.iterdir())

    def no_row_scan(*args, **kwargs):
        raise AssertionError("inspection must not scan samples")

    monkeypatch.setattr(csv_module, "_validate_data_row_widths", no_row_scan)
    result = inspect_measurement(
        source, config=ValidationConfig(limits=ValidationLimits(cell_max_v=4))
    )
    assert result["metadata_status"] == "OK"
    assert result["scope"] == "channel_metadata_only"
    assert result["analysis_performed"] is False
    assert result["time_basis"] == "csv_column"
    assert [item["name"] for item in result["channels"]] == [
        "timestamp_s",
        "cell_2_v",
        "cell_1_v",
        "temp_c",
        "notes",
    ]
    assert all(item["unit"] is None for item in result["channels"])
    assert [item["canonical"] for item in result["bindings"]] == [
        "timestamp_s",
        "cell_1_v",
        "cell_2_v",
        "temp_c",
    ]
    assert source.read_bytes() == data
    assert sorted(tmp_path.iterdir()) == before


@pytest.mark.parametrize(
    ("header", "issue"),
    [
        ("cell_1_v,temp_c", "timestamp_s"),
        ("timestamp_s,temp_c", "No cell voltage"),
        ("timestamp_s,cell_1_v", "No temperature"),
        ("timestamp_s,cell_1_v,temp_c,temp_1_c", "Legacy temp_c"),
        ("timestamp_s,cell_1_v,cell_01_v,temp_c", "Duplicate cell signal index"),
        ("timestamp_s,cell_1_v,cell_1_v,temp_c", "Duplicate CSV column"),
        ("timestamp_s,cell_1_v,,temp_c", "empty column"),
    ],
)
def test_csv_inventory_survives_selection_errors(tmp_path, header, issue):
    source = tmp_path / "capture.csv"
    source.write_text(
        header + "\n" + ",".join("0" for _ in header.split(",")) + "\n", encoding="utf-8"
    )
    result = inspect_measurement(source)
    assert result["metadata_status"] == "ISSUES"
    assert result["bindings"] == []
    assert [item["name"] for item in result["channels"]] == header.split(",")
    assert issue in result["issues"][0]
    with pytest.raises(ValueError, match=issue):
        AnalysisService().analyze_path(source)


def test_vendor_csv_requires_explicit_mapping(tmp_path):
    source = tmp_path / "capture.csv"
    source.write_text('clock,U_01,"T_02",ignored\n', encoding="utf-8")
    assert inspect_measurement(source)["metadata_status"] == "ISSUES"
    result = inspect_measurement(source, config=_vendor_config())
    assert result["metadata_status"] == "OK"
    assert result["bindings"] == [
        {"source": "clock", "canonical": "timestamp_s"},
        {"source": "U_01", "canonical": "cell_1_v"},
        {"source": "T_02", "canonical": "temp_2_c"},
    ]


@pytest.mark.parametrize(
    ("limits", "issue"),
    [
        (
            ValidationLimits(pack_charge_max_a=20, pack_current_positive_direction="discharge"),
            "Pack-current",
        ),
        (
            ValidationLimits(pack_discharge_max_a=20, pack_current_positive_direction="discharge"),
            "Pack-current",
        ),
        (ValidationLimits(pack_voltage_cell_sum_max_delta_v=1), "Pack-voltage"),
    ],
)
def test_inspection_uses_configured_required_pack_channels(tmp_path, limits, issue):
    source = tmp_path / "capture.csv"
    source.write_text("timestamp_s,cell_1_v,temp_c\n", encoding="utf-8")
    result = inspect_measurement(source, config=ValidationConfig(limits=limits))
    assert result["metadata_status"] == "ISSUES"
    assert issue in result["issues"][0]


def test_inspection_accepts_optional_pack_channels(tmp_path):
    source = tmp_path / "capture.csv"
    source.write_text("timestamp_s,cell_1_v,temp_c,pack_current_a,pack_voltage_v\n")
    result = inspect_measurement(source)
    assert result["metadata_status"] == "OK"
    assert {item["canonical"] for item in result["bindings"]} == {
        "timestamp_s",
        "cell_1_v",
        "temp_c",
        "pack_current_a",
        "pack_voltage_v",
    }


@pytest.mark.parametrize("contents", [b"", b"\xff\n"])
def test_unreadable_csv_header_raises(tmp_path, contents):
    source = tmp_path / "capture.csv"
    source.write_bytes(contents)
    with pytest.raises(ValueError):
        inspect_measurement(source)


def test_inspection_rejects_invalid_config(tmp_path):
    with pytest.raises(TypeError, match="ValidationConfig"):
        inspect_measurement(tmp_path / "capture.csv", config={})


class FakeMdfError(Exception):
    pass


class MetadataMDF:
    channels_db: ClassVar[dict] = {"cell_1_v": ((0, 1),), "temp_c": ((1, 1),), "unused": ((0, 2),)}
    units: ClassVar[dict] = {"cell_1_v": "V", "temp_c": "degC", "unused": "mV"}
    closed = False

    def __init__(self, source, **kwargs):
        assert kwargs == {"use_display_names": False, "process_bus_logging": False}
        type(self).closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        type(self).closed = True

    def whereis(self, name):
        return self.channels_db[name]

    def get_channel_unit(self, *, name, group, index):
        return self.units[name]

    def select(self, *args, **kwargs):
        raise AssertionError("inspection must not decode samples")

    get_master = select
    iter_to_dataframe = select


@pytest.mark.parametrize("suffix", [".mf4", ".MDF"])
def test_mdf_inspection_lists_units_and_uses_virtual_master(tmp_path, monkeypatch, suffix):
    monkeypatch.setattr(mf4, "_load_asammdf", lambda: (MetadataMDF, FakeMdfError))
    result = inspect_measurement(tmp_path / ("capture" + suffix))
    assert result["metadata_status"] == "OK"
    assert result["source_format"] == "mf4"
    assert result["time_basis"] == "mdf_master"
    assert result["bindings"][0] == {"source": "timestamp_s", "canonical": "timestamp_s"}
    assert result["channels"][0] == {"name": "cell_1_v", "unit": "V", "group": 0, "index": 1}
    assert "timestamp_s" not in [item["name"] for item in result["channels"]]
    assert MetadataMDF.closed


@pytest.mark.parametrize("defect", ["unit", "ambiguous", "missing-temperature"])
def test_mdf_inventory_survives_selection_errors_and_closes(tmp_path, monkeypatch, defect):
    class InvalidMDF(MetadataMDF):
        channels_db: ClassVar[dict] = dict(MetadataMDF.channels_db)
        units: ClassVar[dict] = dict(MetadataMDF.units)

    if defect == "unit":
        InvalidMDF.units["cell_1_v"] = "mV"
    elif defect == "ambiguous":
        InvalidMDF.channels_db["cell_1_v"] = ((0, 1), (2, 1))
    else:
        del InvalidMDF.channels_db["temp_c"]
    monkeypatch.setattr(mf4, "_load_asammdf", lambda: (InvalidMDF, FakeMdfError))
    result = inspect_measurement(tmp_path / "capture.mf4")
    assert result["metadata_status"] == "ISSUES"
    assert result["channels"]
    assert result["bindings"] == []
    if defect == "ambiguous":
        assert len([item for item in result["channels"] if item["name"] == "cell_1_v"]) == 2
    if defect == "unit":
        assert "Automatic unit conversion is not supported" in result["issues"][0]
    assert InvalidMDF.closed


def test_mdf_vendor_mapping_uses_master_even_without_named_time_channel(tmp_path, monkeypatch):
    class VendorMDF(MetadataMDF):
        channels_db: ClassVar[dict] = {"U_01": ((0, 1),), "T_02": ((0, 2),)}
        units: ClassVar[dict] = {"U_01": "volt", "T_02": "°C"}

    monkeypatch.setattr(mf4, "_load_asammdf", lambda: (VendorMDF, FakeMdfError))
    result = inspect_measurement(tmp_path / "capture.mf4", config=_vendor_config())
    assert result["metadata_status"] == "OK"
    assert result["bindings"][0] == {"source": "clock", "canonical": "timestamp_s"}
    assert VendorMDF.closed


def test_mdf_read_failure_closes_with_retained_traceback(tmp_path, monkeypatch):
    class BrokenMDF(MetadataMDF):
        def get_channel_unit(self, **kwargs):
            raise FakeMdfError("broken metadata")

    monkeypatch.setattr(mf4, "_load_asammdf", lambda: (BrokenMDF, FakeMdfError))
    with pytest.raises(ValueError, match="Failed to read MDF") as error:
        inspect_measurement(tmp_path / "capture.mf4")
    assert error.value.__traceback__ is not None
    assert BrokenMDF.closed


@pytest.mark.parametrize(
    "options",
    [
        ["--batch", "--output-dir", "out"],
        ["--report", "out.html"],
        ["--json-out", "out.json"],
        ["--recursive"],
        ["--output-dir", "out"],
    ],
)
def test_inspection_rejects_analysis_output_options(tmp_path, capsys, options):
    assert run([str(tmp_path / "missing.csv"), "--inspect", *options]) == 2
    assert capsys.readouterr().out == ""
    assert list(tmp_path.iterdir()) == []


def test_inspection_cli_uses_yaml_and_required_signal_overrides(tmp_path, capsys):
    source = tmp_path / "capture.csv"
    source.write_text("clock,U_01,T_02\n0,invalid,25\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        'schema_version: 6\nsignals:\n  timestamp: clock\n  cell_voltage:\n    pattern: "U_(?P<index>\\\\d+)"\n'
        '  temperature:\n    pattern: "T_(?P<index>\\\\d+)"\n'
        "limits:\n  pack_current:\n    charge_max_a: 20\n    positive_direction: discharge\n",
        encoding="utf-8",
    )
    assert run([str(source), "--inspect", "--config", str(config)]) == 4
    first = json.loads(capsys.readouterr().out)
    assert "Pack-current" in first["issues"][0]
    assert run([str(source), "--inspect", "--config", str(config), "--no-pack-charge-max-a"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["metadata_status"] == "OK"
    assert run([str(source), "--config", str(config), "--no-pack-charge-max-a"]) == 4
    assert "non-numeric" in capsys.readouterr().err


def test_inspection_cli_unreadable_input_is_runtime_error(tmp_path, capsys):
    assert run([str(tmp_path / "missing.csv"), "--inspect"]) == 4
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


def test_inspection_missing_mdf_extra_reports_install_hint(tmp_path, monkeypatch, capsys):
    def missing():
        raise ImportError("install with 'pip install batterylog[mf4]'")

    monkeypatch.setattr(mf4, "_load_asammdf", missing)
    assert run([str(tmp_path / "capture.mf4"), "--inspect"]) == 4
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "pip install batterylog[mf4]" in captured.err
