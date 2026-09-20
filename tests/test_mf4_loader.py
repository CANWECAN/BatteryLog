from io import BytesIO
from pathlib import Path
from typing import ClassVar

import pandas as pd
import pytest

from batterylog import SignalMapping, SignalPattern, ValidationLimits
from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.loaders import CsvFileLoader, CsvPathLoader, MdfFileLoader, MdfPathLoader
from batterylog.loaders import mf4 as mf4_module
from batterylog.loaders.factory import measurement_loader_for_file, measurement_loader_for_path


class FakeMdfException(Exception):
    pass


class FakeMDF:
    last_init: tuple[object, dict[str, object]] | None = None
    channels_db: ClassVar[dict[str, tuple[tuple[int, int], ...]]] = {
        "cell_1_v": ((0, 1),),
        "cell_2_v": ((0, 2),),
        "temp_1_c": ((0, 3),),
    }
    units: ClassVar[dict[str, str]] = {
        "cell_1_v": "V",
        "cell_2_v": "V",
        "temp_1_c": "degC",
    }
    frame: ClassVar[pd.DataFrame] = pd.DataFrame(
        {
            "cell_1_v": [3.8, 4.3, 3.8],
            "cell_2_v": [3.79, 3.9, 3.79],
            "temp_1_c": [25.0, 56.0, 25.0],
        },
        index=pd.Index([0.0, 1.0, 2.0], name="timestamps"),
    )
    iter_kwargs: dict[str, object] | None = None

    def __init__(self, source, **kwargs) -> None:
        type(self).last_init = (source, kwargs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def whereis(self, name: str):
        return self.channels_db.get(name, ())

    def get_channel_unit(self, *, name: str, group: int, index: int) -> str:
        del group, index
        return self.units[name]

    def iter_to_dataframe(self, **kwargs):
        type(self).iter_kwargs = kwargs
        selected_names = [item[0] for item in kwargs["channels"]]
        yield self.frame.loc[:, selected_names].copy()


def _install_fake_mdf(monkeypatch: pytest.MonkeyPatch, cls=FakeMDF) -> None:
    monkeypatch.setattr(mf4_module, "_load_asammdf", lambda: (cls, FakeMdfException))


def test_loader_factory_dispatches_mdf_suffixes() -> None:
    assert isinstance(measurement_loader_for_path("capture.mf4"), MdfPathLoader)
    assert isinstance(measurement_loader_for_path("capture.MDF"), MdfPathLoader)
    assert isinstance(measurement_loader_for_path("capture.csv"), CsvPathLoader)

    handle = BytesIO(b"")
    assert isinstance(measurement_loader_for_file(handle, source_name="capture.mf4"), MdfFileLoader)
    assert isinstance(measurement_loader_for_file(handle, source_name="capture.csv"), CsvFileLoader)
    assert isinstance(measurement_loader_for_file(handle), CsvFileLoader)


def test_mdf_loader_uses_fail_closed_alignment_and_physical_values(monkeypatch) -> None:
    _install_fake_mdf(monkeypatch)
    loader = MdfPathLoader(Path("capture.mf4"), chunk_ram_bytes=123456)

    chunks = list(loader.iter_chunks(signal_mapping=None))

    assert len(chunks) == 1
    assert chunks[0].columns.tolist() == ["timestamp_s", "cell_1_v", "cell_2_v", "temp_1_c"]
    assert chunks[0]["timestamp_s"].tolist() == [0.0, 1.0, 2.0]
    assert FakeMDF.last_init == (
        Path("capture.mf4"),
        {"use_display_names": False, "process_bus_logging": False},
    )
    assert FakeMDF.iter_kwargs is not None
    assert FakeMDF.iter_kwargs["time_from_zero"] is False
    assert FakeMDF.iter_kwargs["use_interpolation"] is False
    assert FakeMDF.iter_kwargs["interpolate_outwards_with_nan"] is True
    assert FakeMDF.iter_kwargs["raw"] is False
    assert FakeMDF.iter_kwargs["numeric_1D_only"] is True
    assert FakeMDF.iter_kwargs["chunk_ram_size"] == 123456


def test_mdf_loader_passes_vendor_mapping_to_existing_canonicalizer(monkeypatch) -> None:
    class VendorMDF(FakeMDF):
        channels_db: ClassVar[dict[str, tuple[tuple[int, int], ...]]] = {
            "vendor_time": ((1, 0),),
            "U_Cell_01": ((1, 1),),
            "U_Cell_02": ((1, 2),),
            "T_Mod_01": ((1, 3),),
        }
        units: ClassVar[dict[str, str]] = {
            "vendor_time": "s",
            "U_Cell_01": "V",
            "U_Cell_02": "volt",
            "T_Mod_01": "°C",
        }
        frame: ClassVar[pd.DataFrame] = pd.DataFrame(
            {
                "U_Cell_01": [3.8, 4.3, 3.8],
                "U_Cell_02": [3.79, 3.9, 3.79],
                "T_Mod_01": [25.0, 56.0, 25.0],
            },
            index=pd.Index([10.0, 11.0, 12.0], name="timestamps"),
        )

    _install_fake_mdf(monkeypatch, VendorMDF)
    mapping = SignalMapping(
        timestamp="vendor_time",
        cell_voltage=SignalPattern(pattern=r"U_Cell_(?P<index>[0-9]+)"),
        temperature=SignalPattern(pattern=r"T_Mod_(?P<index>[0-9]+)"),
    )
    result = analyze_measurement_loader(
        MdfPathLoader(Path("capture.mf4")),
        limits=ValidationLimits(cell_max_v=4.2, temperature_max_c=55.0),
        signal_mapping=mapping,
    )

    assert result["validation_status"] == "FAIL"
    assert result["cells_detected"] == 2
    assert result["temperature_sensors_detected"] == 1
    assert result["max_cell_voltage_v"] == 4.3
    assert result["max_temperature_c"] == 56.0


def test_mdf_loader_rejects_ambiguous_channel(monkeypatch) -> None:
    class AmbiguousMDF(FakeMDF):
        channels_db: ClassVar[dict[str, tuple[tuple[int, int], ...]]] = {
            **FakeMDF.channels_db,
            "cell_1_v": ((0, 1), (2, 4)),
        }

    _install_fake_mdf(monkeypatch, AmbiguousMDF)

    with pytest.raises(ValueError, match="cell_1_v.*ambiguous"):
        list(MdfPathLoader(Path("capture.mf4")).iter_chunks(signal_mapping=None))


def test_mdf_loader_rejects_unsupported_units(monkeypatch) -> None:
    class MillivoltMDF(FakeMDF):
        units: ClassVar[dict[str, str]] = {**FakeMDF.units, "cell_1_v": "mV"}

    _install_fake_mdf(monkeypatch, MillivoltMDF)

    with pytest.raises(ValueError, match="Automatic unit conversion is not supported"):
        list(MdfPathLoader(Path("capture.mf4")).iter_chunks(signal_mapping=None))


def test_mdf_loader_rejects_missing_canonical_cell_channels(monkeypatch) -> None:
    class NoCellMDF(FakeMDF):
        channels_db: ClassVar[dict[str, tuple[tuple[int, int], ...]]] = {
            "temp_1_c": ((0, 3),),
        }
        units: ClassVar[dict[str, str]] = {"temp_1_c": "degC"}

    _install_fake_mdf(monkeypatch, NoCellMDF)

    with pytest.raises(ValueError, match="No cell voltage columns found"):
        list(MdfPathLoader(Path("capture.mf4")).iter_chunks(signal_mapping=None))


def test_mdf_loader_rejects_missing_canonical_temperature_channels(monkeypatch) -> None:
    class NoTemperatureMDF(FakeMDF):
        channels_db: ClassVar[dict[str, tuple[tuple[int, int], ...]]] = {
            "cell_1_v": ((0, 1),),
        }
        units: ClassVar[dict[str, str]] = {"cell_1_v": "V"}

    _install_fake_mdf(monkeypatch, NoTemperatureMDF)

    with pytest.raises(ValueError, match="No temperature columns found"):
        list(MdfPathLoader(Path("capture.mf4")).iter_chunks(signal_mapping=None))


def test_mdf_loader_rejects_missing_extracted_channel(monkeypatch) -> None:
    class OmittedMDF(FakeMDF):
        def iter_to_dataframe(self, **kwargs):
            del kwargs
            yield self.frame.drop(columns=["temp_1_c"])

    _install_fake_mdf(monkeypatch, OmittedMDF)

    with pytest.raises(ValueError, match="omitted required channel.*temp_1_c"):
        list(MdfPathLoader(Path("capture.mf4")).iter_chunks(signal_mapping=None))


def test_mdf_no_interpolation_nan_fails_closed(monkeypatch) -> None:
    class MisalignedMDF(FakeMDF):
        frame: ClassVar[pd.DataFrame] = FakeMDF.frame.copy()
        frame.loc[1.0, "temp_1_c"] = float("nan")

    _install_fake_mdf(monkeypatch, MisalignedMDF)

    with pytest.raises(ValueError, match="Required numeric value is missing or non-numeric"):
        analyze_measurement_loader(
            MdfPathLoader(Path("capture.mf4")),
            limits=ValidationLimits(cell_max_v=4.2),
        )


def test_mdf_loader_translates_asammdf_format_errors(monkeypatch) -> None:
    class BrokenMDF(FakeMDF):
        def __enter__(self):
            raise FakeMdfException("corrupt data block")

    _install_fake_mdf(monkeypatch, BrokenMDF)

    with pytest.raises(ValueError, match="Failed to read MDF measurement: corrupt data block"):
        list(MdfPathLoader(Path("broken.mf4")).iter_chunks(signal_mapping=None))


def test_mdf_loader_requires_positive_chunk_budget(monkeypatch) -> None:
    _install_fake_mdf(monkeypatch)

    with pytest.raises(ValueError, match="chunk_ram_bytes must be a positive integer"):
        list(MdfPathLoader(Path("capture.mf4"), chunk_ram_bytes=0).iter_chunks(signal_mapping=None))


def test_mdf_loader_rejects_missing_unit_metadata(monkeypatch) -> None:
    class MissingUnitMDF(FakeMDF):
        units: ClassVar[dict[str, str]] = {**FakeMDF.units, "temp_1_c": ""}

    _install_fake_mdf(monkeypatch, MissingUnitMDF)

    with pytest.raises(ValueError, match="temp_1_c.*<missing>.*expected degC/°C"):
        list(MdfPathLoader(Path("capture.mf4")).iter_chunks(signal_mapping=None))


def test_mdf_optional_dependency_error_has_install_hint(monkeypatch) -> None:
    monkeypatch.setattr(mf4_module, "find_spec", lambda name: None)

    with pytest.raises(ImportError, match=r"batterylog\[mf4\]"):
        mf4_module._load_asammdf()


def test_mdf_backend_import_failure_has_platform_hint(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__
    monkeypatch.setattr(mf4_module, "find_spec", lambda name: object())

    def blocked_import(name, *args, **kwargs):
        if name == "asammdf":
            raise ImportError("DLL load failed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(ImportError, match="platform/native-library policy"):
        mf4_module._load_asammdf()


def test_mdf_loader_rejects_non_string_unit_metadata(monkeypatch) -> None:
    class NonStringUnitMDF(FakeMDF):
        def get_channel_unit(self, *, name: str, group: int, index: int):
            if name == "temp_1_c":
                return None
            return super().get_channel_unit(name=name, group=group, index=index)

    _install_fake_mdf(monkeypatch, NonStringUnitMDF)

    with pytest.raises(ValueError, match="temp_1_c.*<missing>.*expected degC/°C"):
        list(MdfPathLoader(Path("capture.mf4")).iter_chunks(signal_mapping=None))


def test_mdf_loader_rejects_inconsistent_channel_lookup(monkeypatch) -> None:
    class InconsistentMDF(FakeMDF):
        def whereis(self, name: str):
            if name == "cell_1_v":
                return ()
            return super().whereis(name)

    _install_fake_mdf(monkeypatch, InconsistentMDF)

    with pytest.raises(ValueError, match="Mapped MDF channel 'cell_1_v' is missing"):
        list(MdfPathLoader(Path("capture.mf4")).iter_chunks(signal_mapping=None))
