"""Real MF4 status extraction, time alignment and CSV/streaming equivalence."""

from dataclasses import replace
from io import BytesIO

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("asammdf", exc_type=ImportError)
from asammdf import MDF, Signal

from batterylog import (
    AnalysisService,
    BalancingConfig,
    ContactorResponseConfig,
    DataQualityConfig,
    FailureModelConfig,
    PrechargeCurrentConfig,
    SignalMapping,
    SignalPattern,
    SourceUnits,
    UnloadedCurrentConfig,
    ValidationConfig,
    normalize_measurement,
    validate_result_semantics,
)
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.loaders import MdfFileLoader, MdfPathLoader


def _write(
    path, *, grouped=True, mapped=False, status=True, unit="", invalid=False, asynchronous=False
):
    times = np.arange(6, dtype=float)
    names = (
        ["U1", "U2", "U3", "T1", "I", "Pack"]
        if mapped
        else ["cell_1_v", "cell_2_v", "cell_3_v", "temp_c", "pack_current_a", "pack_voltage_v"]
    )
    frame = pd.DataFrame(
        {
            "timestamp_s": times,
            "cell_1_v": [3.5] * 6,
            "cell_2_v": [3.5] * 6,
            "cell_3_v": [3.25] * 6,
            "temp_c": [25] * 6,
            "pack_current_a": [0] * 6,
            "pack_voltage_v": [10.25] * 6,
        }
    )
    signals = []
    for source, canonical, eng_unit in zip(
        names, frame.columns[1:], ["V", "V", "V", "degC", "A", "V"]
    ):
        signals.append(Signal(frame[canonical].to_numpy(), times, name=source, unit=eng_unit))
    if status:
        status_times = times[::2] if asynchronous else times
        active = np.array(
            [False, True, True] if asynchronous else [False, True, True, True, True, False]
        )
        bits = (
            np.array([False, False, True, False, False, False])
            if invalid and not asynchronous
            else None
        )
        signals.append(Signal(active, status_times, name="Bal", unit=unit, invalidation_bits=bits))
        if not asynchronous:
            frame["Bal"] = active.astype(object)
            if invalid:
                frame.loc[2, "Bal"] = np.nan
    mdf = MDF(version="4.10")
    try:
        if grouped:
            mdf.append(signals, common_timebase=True)
        else:
            for signal in signals:
                mdf.append([signal], common_timebase=True)
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return frame


@pytest.mark.parametrize("grouped", [True, False])
@pytest.mark.parametrize("mapped", [True, False])
@pytest.mark.parametrize("entry", ["service", "path", "file"])
def test_real_mf4_named_boolean_status_matches_csv_and_chunks(tmp_path, grouped, mapped, entry):
    path = tmp_path / "capture.mf4"
    frame = _write(path, grouped=grouped, mapped=mapped)
    models = FailureModelConfig(1, balancing=BalancingConfig("Bal", 2, 0.03125, 0.125, 4))
    mapping = (
        SignalMapping(
            "clock",
            SignalPattern(r"U(?P<index>\d+)"),
            SignalPattern(r"T(?P<index>\d+)"),
            "I",
            "Pack",
        )
        if mapped
        else None
    )
    config = ValidationConfig(signals=mapping, failure_models=models)
    # The source mapping snapshot differs; compare the engineering evidence below.
    expected = _analyze_battery_frame(frame, failure_models=models)
    if entry == "service":
        actual = (
            AnalysisService(config).analyze_loader(MdfPathLoader(path, chunk_ram_bytes=64)).result
        )
    elif entry == "path":
        actual = analyze_measurement_loader(
            MdfPathLoader(path, chunk_ram_bytes=64), signal_mapping=mapping, failure_models=models
        )
    else:
        actual = analyze_measurement_loader(
            MdfFileLoader(BytesIO(path.read_bytes()), chunk_ram_bytes=64),
            signal_mapping=mapping,
            failure_models=models,
        )
    assert actual["failure_models"] == expected["failure_models"]
    assert actual["rows_input"] == 6
    assert actual["validation_status"] == "FAIL"
    validate_result_semantics(actual)


@pytest.mark.parametrize("grouped", [True, False])
def test_real_mf4_invalidation_interrupts_balancing_without_coercing_true_to_numeric(
    tmp_path, grouped
):
    path = tmp_path / "invalid.mf4"
    frame = _write(path, grouped=grouped, invalid=True)
    models = FailureModelConfig(1, balancing=BalancingConfig("Bal", 2, 0.03125, 0.125, 4))
    with pytest.raises(ValueError, match="Balancing status"):
        AnalysisService(ValidationConfig(failure_models=models)).analyze_path(path)
    config = ValidationConfig(
        failure_models=models, data_quality=DataQualityConfig("exclude_invalid_rows")
    )
    actual = AnalysisService(config).analyze_path(path).result
    expected = _analyze_battery_frame(
        frame, failure_models=models, data_quality=config.data_quality
    )
    assert actual["failure_models"] == expected["failure_models"]
    assert actual["validation_status"] == "NOT_EVALUATED"
    assert actual["rows_excluded"] == 0  # Status is its own explicit contract.


def test_missing_mf4_status_is_not_evaluated_and_non_dimensionless_is_rejected(tmp_path):
    path = tmp_path / "missing.mf4"
    _write(path, status=False)
    models = FailureModelConfig(1, balancing=BalancingConfig("Bal", 2, 0.03125, 0.125, 4))
    assert (
        AnalysisService(ValidationConfig(failure_models=models))
        .analyze_path(path)
        .result["validation_status"]
        == "NOT_EVALUATED"
    )
    path = tmp_path / "unit.mf4"
    _write(path, unit="V")
    with pytest.raises(ValueError, match="dimensionless"):
        AnalysisService(ValidationConfig(failure_models=models)).analyze_path(path)


def test_async_mf4_status_is_not_forward_filled(tmp_path):
    path = tmp_path / "async.mf4"
    _write(path, grouped=False, asynchronous=True)
    models = FailureModelConfig(1, balancing=BalancingConfig("Bal", 2, 0.03125, 0.125, 4))
    result = (
        AnalysisService(
            ValidationConfig(
                failure_models=models, data_quality=DataQualityConfig("exclude_invalid_rows")
            )
        )
        .analyze_path(path)
        .result
    )
    assert result["validation_status"] == "NOT_EVALUATED"
    assert all(item["incomplete_intervals"] for item in result["failure_models"]["evaluations"])
    assert all(not item["events"] for item in result["failure_models"]["evaluations"])


def test_mf4_normalization_retains_named_balancing_status(tmp_path):
    path = tmp_path / "source.mf4"
    frame = _write(path, grouped=False)
    models = FailureModelConfig(1, balancing=BalancingConfig("Bal", 2, 0.03125, 0.125, 4))
    config = ValidationConfig(failure_models=models)
    destination = tmp_path / "prepared"
    converted = normalize_measurement(
        path, destination, units=SourceUnits("s", "V", "degC", "A", "V"), config=config
    )
    result = AnalysisService(config).analyze_path(destination / "normalized.csv").result
    assert result == _analyze_battery_frame(frame, failure_models=models)
    assert (
        next(c for c in converted["conversions"] if c["canonical"] == "Bal")["target_unit"] == "1"
    )


def test_duplicate_mf4_status_and_measurement_role_rejected(tmp_path):
    path = tmp_path / "duplicate.mf4"
    _write(path)
    mdf = MDF(path)
    try:
        mdf.append(
            [Signal(np.ones(6, dtype=bool), np.arange(6, dtype=float), name="Bal", unit="")],
            common_timebase=True,
        )
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    models = FailureModelConfig(1, balancing=BalancingConfig("Bal", 2, 0.03125, 0.125, 4))
    with pytest.raises(ValueError, match="ambiguous"):
        AnalysisService(ValidationConfig(failure_models=models)).analyze_path(path)
    models = replace(models, balancing=replace(models.balancing, active_source="cell_1_v"))
    with pytest.raises(ValueError, match="measurement role"):
        AnalysisService(ValidationConfig(failure_models=models)).analyze_path(path)


@pytest.mark.parametrize("grouped", [True, False])
def test_scaled_one_bit_status_is_not_silently_cast_to_true(tmp_path, grouped):
    path = tmp_path / "scaled-status.mf4"
    times = np.arange(4, dtype=float)
    signals = [
        Signal(np.full(4, 3.5), times, name="cell_1_v", unit="V"),
        Signal(np.full(4, 3.25), times, name="cell_2_v", unit="V"),
        Signal(np.full(4, 25.0), times, name="temp_c", unit="degC"),
        Signal(
            np.array([0, 1, 1, 0], dtype=np.uint8),
            times,
            name="Bal",
            unit="1",
            bit_count=1,
            conversion={"a": 2.0, "b": 0.0},
        ),
    ]
    mdf = MDF(version="4.10")
    try:
        if grouped:
            mdf.append(signals, common_timebase=True)
        else:
            for signal in signals:
                mdf.append([signal], common_timebase=True)
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    models = FailureModelConfig(1, balancing=BalancingConfig("Bal", 2, 0.03125, 0.125, 4))
    with pytest.raises(ValueError, match="Balancing status"):
        AnalysisService(ValidationConfig(failure_models=models)).analyze_path(path)


def _write_unloaded(
    path, *, grouped=True, invalid=False, asynchronous=False, unit="1", scaled=False
):
    times = np.arange(6, dtype=float)
    frame = pd.DataFrame(
        {
            "timestamp_s": times,
            "cell_1_v": [3.5] * 6,
            "cell_2_v": [3.5] * 6,
            "temp_c": [25.0] * 6,
            "pack_current_a": [20, 1, -2, 2, 1, 20],
            "Unload": [False, True, True, True, True, False],
            "Bal": [False] * 6,
        }
    )
    signals = [
        Signal(frame[name].to_numpy(), times, name=name, unit=eng_unit)
        for name, eng_unit in (
            ("cell_1_v", "V"),
            ("cell_2_v", "V"),
            ("temp_c", "degC"),
            ("pack_current_a", "A"),
            ("Bal", "1"),
        )
    ]
    statuses = frame["Unload"].to_numpy(dtype=np.uint8 if scaled else bool)
    bits = np.array([False, False, True, False, False, False]) if invalid else None
    if invalid:
        frame["Unload"] = frame["Unload"].astype(object)
        frame.loc[2, "Unload"] = np.nan
    signal = Signal(
        statuses[::2] if asynchronous else statuses,
        times[::2] if asynchronous else times,
        name="Unload",
        unit=unit,
        invalidation_bits=bits,
        bit_count=1 if scaled else None,
        conversion={"a": 2.0, "b": 0.0} if scaled else None,
    )
    signals.append(signal)
    mdf = MDF(version="4.10")
    try:
        if grouped:
            mdf.append(signals, common_timebase=True)
        else:
            for signal in signals:
                mdf.append([signal], common_timebase=True)
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return frame


@pytest.mark.parametrize("grouped", [True, False])
@pytest.mark.parametrize("entry", ["service", "path", "file", "normalize"])
def test_real_mf4_unloaded_current_two_statuses_match_csv(tmp_path, grouped, entry):
    path = tmp_path / "source.mf4"
    frame = _write_unloaded(path, grouped=grouped)
    models = FailureModelConfig(
        1,
        balancing=BalancingConfig("Bal", 2, 0.01, 0.1, 4),
        unloaded_current=UnloadedCurrentConfig("Unload", 0.5, 2),
    )
    config = ValidationConfig(failure_models=models)
    expected = _analyze_battery_frame(frame, failure_models=models)
    if entry == "service":
        result = AnalysisService(config).analyze_path(path).result
    elif entry == "normalize":
        destination = tmp_path / "prepared"
        evidence = normalize_measurement(
            path, destination, units=SourceUnits("s", "V", "degC", "A"), config=config
        )
        assert {c["canonical"] for c in evidence["conversions"] if c["target_unit"] == "1"} == {
            "Unload",
            "Bal",
        }
        result = AnalysisService(config).analyze_path(destination / "normalized.csv").result
    else:
        loader = (
            MdfPathLoader(path, chunk_ram_bytes=48)
            if entry == "path"
            else MdfFileLoader(BytesIO(path.read_bytes()), chunk_ram_bytes=48)
        )
        result = analyze_measurement_loader(loader, failure_models=models)
    assert result == expected
    assert result["validation_status"] == "FAIL"
    validate_result_semantics(result)


@pytest.mark.parametrize(
    "grouped,defect",
    [
        (True, "invalidation"),
        (False, "invalidation"),
        (True, "scaled"),
        (False, "scaled"),
        (True, "unit"),
        (False, "unit"),
        (False, "async"),
    ],
)
def test_real_mf4_unloaded_status_never_infers_or_fills_missing_state(tmp_path, grouped, defect):
    path = tmp_path / "source.mf4"
    frame = _write_unloaded(
        path,
        grouped=grouped,
        invalid=defect == "invalidation",
        scaled=defect == "scaled",
        unit="A" if defect == "unit" else "1",
        asynchronous=defect == "async",
    )
    models = FailureModelConfig(1, unloaded_current=UnloadedCurrentConfig("Unload", 0.5, 2))
    service = AnalysisService(ValidationConfig(failure_models=models))
    with pytest.raises(
        ValueError, match="dimensionless" if defect == "unit" else "Unloaded status"
    ):
        service.analyze_path(path)
    if defect == "unit":
        return
    config = ValidationConfig(
        failure_models=models, data_quality=DataQualityConfig("exclude_invalid_rows")
    )
    result = AnalysisService(config).analyze_path(path).result
    assert result["failure_models"]["evaluations"][0]["status"] == "NOT_EVALUATED"
    assert result["rows_excluded"] == 0
    if defect == "invalidation":
        assert result == _analyze_battery_frame(
            frame, failure_models=models, data_quality=config.data_quality
        )


def _write_contactor(
    path,
    *,
    grouped=True,
    missing=False,
    invalid=False,
    unit="1",
    asynchronous=False,
    scaled=False,
    duplicate=False,
):
    times = np.arange(5, dtype=float)
    frame = pd.DataFrame(
        {
            "timestamp_s": times,
            "cell_1_v": [3.5] * 5,
            "cell_2_v": [3.5] * 5,
            "temp_c": [25.0] * 5,
            "Cmd": [False, True, True, True, True],
            "Feedback": [False] * 5,
        }
    )
    signals = [
        Signal(frame[n].to_numpy(), times, name=n, unit=u)
        for n, u in [("cell_1_v", "V"), ("cell_2_v", "V"), ("temp_c", "degC")]
    ]
    for name in ("Cmd", "Feedback"):
        if missing and name == "Feedback":
            frame = frame.drop(columns=name)
            continue
        selected = times[::2] if asynchronous and name == "Feedback" else times
        bits = (
            np.array([False, False, True, False, False]) if invalid and name == "Feedback" else None
        )
        samples = (
            frame[name].to_numpy()[::2]
            if asynchronous and name == "Feedback"
            else frame[name].to_numpy()
        )
        signal = Signal(samples, selected, name=name, unit=unit, invalidation_bits=bits)
        if scaled and name == "Cmd":
            from asammdf.blocks.v4_blocks import ChannelConversion
            from asammdf.blocks.v4_constants import CONVERSION_TYPE_LIN

            signal.conversion = ChannelConversion(conversion_type=CONVERSION_TYPE_LIN, a=2, b=0)
        signals.append(signal)
    if invalid:
        frame["Feedback"] = frame["Feedback"].astype(object)
        frame.loc[2, "Feedback"] = np.nan
    mdf = MDF(version="4.10")
    try:
        if grouped:
            mdf.append(signals, common_timebase=True)
        else:
            for signal in signals:
                mdf.append([signal], common_timebase=True)
        if duplicate:
            mdf.append([signals[-1]], common_timebase=True)
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return frame


@pytest.mark.parametrize("grouped", [True, False])
@pytest.mark.parametrize("entry", ["service", "path", "file", "normalize"])
def test_real_mf4_contactor_sources_match_csv(tmp_path, grouped, entry):
    path = tmp_path / "response.mf4"
    frame = _write_contactor(path, grouped=grouped)
    models = FailureModelConfig(1, contactor_response=ContactorResponseConfig("Cmd", "Feedback", 2))
    config = ValidationConfig(failure_models=models)
    expected = _analyze_battery_frame(frame, failure_models=models)
    if entry == "service":
        result = AnalysisService(config).analyze_path(path).result
    elif entry == "normalize":
        destination = tmp_path / "prepared"
        evidence = normalize_measurement(
            path, destination, units=SourceUnits("s", "V", "degC"), config=config
        )
        assert {c["canonical"] for c in evidence["conversions"] if c["target_unit"] == "1"} == {
            "Cmd",
            "Feedback",
        }
        result = AnalysisService(config).analyze_path(destination / "normalized.csv").result
    else:
        loader = (
            MdfPathLoader(path, chunk_ram_bytes=40)
            if entry == "path"
            else MdfFileLoader(BytesIO(path.read_bytes()), chunk_ram_bytes=40)
        )
        result = analyze_measurement_loader(loader, failure_models=models)
    assert result == expected and result["validation_status"] == "FAIL"
    validate_result_semantics(result)


@pytest.mark.parametrize("grouped", [True, False])
@pytest.mark.parametrize("defect", ["invalidation", "scaled", "unit", "missing", "duplicate"])
def test_real_mf4_contactor_rejects_invalid_and_ambiguous_states(tmp_path, grouped, defect):
    path = tmp_path / "response.mf4"
    frame = _write_contactor(
        path,
        grouped=grouped,
        invalid=defect == "invalidation",
        scaled=defect == "scaled",
        unit="V" if defect == "unit" else "1",
        missing=defect == "missing",
        duplicate=defect == "duplicate",
    )
    models = FailureModelConfig(1, contactor_response=ContactorResponseConfig("Cmd", "Feedback", 2))
    config = ValidationConfig(failure_models=models)
    if defect == "missing":
        assert AnalysisService(config).analyze_path(path).result == _analyze_battery_frame(
            frame, failure_models=models
        )
        return
    with pytest.raises(
        ValueError,
        match="dimensionless"
        if defect == "unit"
        else "ambiguous"
        if defect == "duplicate"
        else "Contactor .*status",
    ):
        AnalysisService(config).analyze_path(path)
    if defect in ("unit", "duplicate"):
        return
    config = replace(config, data_quality=DataQualityConfig("exclude_invalid_rows"))
    result = AnalysisService(config).analyze_path(path).result
    assert result["rows_excluded"] == 0
    assert result["failure_models"]["evaluations"][0]["status"] == "NOT_EVALUATED"
    if defect == "invalidation":
        assert result == _analyze_battery_frame(
            frame, failure_models=models, data_quality=config.data_quality
        )


def test_real_mf4_contactor_async_feedback_is_not_interpolated(tmp_path):
    path = tmp_path / "response.mf4"
    _write_contactor(path, grouped=False, asynchronous=True)
    models = FailureModelConfig(1, contactor_response=ContactorResponseConfig("Cmd", "Feedback", 2))
    with pytest.raises(ValueError, match="Contactor feedback.*data row 2"):
        AnalysisService(ValidationConfig(failure_models=models)).analyze_path(path)
    result = (
        AnalysisService(
            ValidationConfig(
                failure_models=models, data_quality=DataQualityConfig("exclude_invalid_rows")
            )
        )
        .analyze_path(path)
        .result
    )
    assert result["rows_excluded"] == 0
    assert result["failure_models"]["evaluations"][0]["status"] == "NOT_EVALUATED"
    assert result["failure_models"]["evaluations"][0]["events"] == []


def _write_precharge(
    path,
    *,
    grouped=True,
    mapped=False,
    status=True,
    unit="1",
    invalid=False,
    scaled=False,
    asynchronous=False,
    duplicate=False,
):
    times = np.arange(6, dtype=float)
    frame = pd.DataFrame(
        {
            "timestamp_s": times,
            "cell_1_v": [3.5] * 6,
            "cell_2_v": [3.5] * 6,
            "temp_c": [25.0] * 6,
            "pack_current_a": [0, -6, -5, -4.5, -1, 0],
            "Pre": [False, True, True, True, True, False],
        }
    )
    sources = (
        ["U1", "U2", "T1", "I"] if mapped else ["cell_1_v", "cell_2_v", "temp_c", "pack_current_a"]
    )
    signals = [
        Signal(frame[canonical].to_numpy(), times, name=source, unit=unit)
        for source, canonical, unit in zip(
            sources,
            ["cell_1_v", "cell_2_v", "temp_c", "pack_current_a"],
            ["V", "V", "degC", "A"],
            strict=True,
        )
    ]
    if status:
        bits = np.array([False, False, True, False, False, False]) if invalid else None
        selected = times[::2] if asynchronous else times
        samples = frame["Pre"].to_numpy()[::2] if asynchronous else frame["Pre"].to_numpy()
        phase = Signal(samples, selected, name="Pre", unit=unit, invalidation_bits=bits)
        if scaled:
            from asammdf.blocks.v4_blocks import ChannelConversion
            from asammdf.blocks.v4_constants import CONVERSION_TYPE_LIN

            phase.conversion = ChannelConversion(conversion_type=CONVERSION_TYPE_LIN, a=2, b=0)
        signals.append(phase)
    else:
        frame = frame.drop(columns="Pre")
    if invalid:
        frame["Pre"] = frame["Pre"].astype(object)
        frame.loc[2, "Pre"] = np.nan
    mdf = MDF(version="4.10")
    try:
        if grouped:
            mdf.append(signals, common_timebase=True)
        else:
            for signal in signals:
                mdf.append([signal], common_timebase=True)
        if duplicate:
            mdf.append([signals[-1]], common_timebase=True)
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return frame


@pytest.mark.parametrize("grouped", [True, False])
@pytest.mark.parametrize("mapped", [True, False])
@pytest.mark.parametrize("entry", ["service", "path", "file", "normalize"])
def test_real_mf4_precharge_matches_csv_across_mapping_and_adapters(
    tmp_path, grouped, mapped, entry
):
    path = tmp_path / "precharge.mf4"
    frame = _write_precharge(path, grouped=grouped, mapped=mapped)
    mapping = (
        SignalMapping(
            "clock",
            SignalPattern(r"U(?P<index>\d+)"),
            SignalPattern(r"T(?P<index>\d+)"),
            pack_current="I",
        )
        if mapped
        else None
    )
    models = FailureModelConfig(1, precharge_current=PrechargeCurrentConfig("Pre", 2, 4, 3))
    config = ValidationConfig(signals=mapping, failure_models=models)
    if mapped:
        frame = frame.rename(
            columns={
                "timestamp_s": "clock",
                "cell_1_v": "U1",
                "cell_2_v": "U2",
                "temp_c": "T1",
                "pack_current_a": "I",
            }
        )
    expected = _analyze_battery_frame(frame, signal_mapping=mapping, failure_models=models)
    if entry == "service":
        result = AnalysisService(config).analyze_path(path).result
    elif entry == "normalize":
        destination = tmp_path / "prepared"
        evidence = normalize_measurement(
            path, destination, units=SourceUnits("s", "V", "degC", "A"), config=config
        )
        assert next(c for c in evidence["conversions"] if c["canonical"] == "Pre") == {
            "source": "Pre",
            "canonical": "Pre",
            "source_unit": "1",
            "target_unit": "1",
            "divisor": 1.0,
            "offset": 0.0,
        }
        normalized = pd.read_csv(destination / "normalized.csv")
        assert normalized["pack_current_a"].tolist() == [0, -6, -5, -4.5, -1, 0]
        result = (
            AnalysisService(replace(config, signals=None))
            .analyze_path(destination / "normalized.csv")
            .result
        )
        # Canonical analysis has different mapping provenance but identical model evidence.
        assert result["failure_models"] == expected["failure_models"]
        assert result["validation_status"] == "FAIL"
        validate_result_semantics(result)
        return
    else:
        loader = (
            MdfPathLoader(path, chunk_ram_bytes=40)
            if entry == "path"
            else MdfFileLoader(BytesIO(path.read_bytes()), chunk_ram_bytes=40)
        )
        result = analyze_measurement_loader(loader, signal_mapping=mapping, failure_models=models)
    assert result == expected and result["validation_status"] == "FAIL"
    validate_result_semantics(result)


@pytest.mark.parametrize("grouped", [True, False])
@pytest.mark.parametrize("defect", ["invalidation", "scaled", "unit", "missing", "duplicate"])
def test_real_mf4_precharge_state_selection_and_unknown_observations(tmp_path, grouped, defect):
    path = tmp_path / "precharge.mf4"
    frame = _write_precharge(
        path,
        grouped=grouped,
        invalid=defect == "invalidation",
        scaled=defect == "scaled",
        unit="A" if defect == "unit" else "1",
        status=defect != "missing",
        duplicate=defect == "duplicate",
    )
    models = FailureModelConfig(1, precharge_current=PrechargeCurrentConfig("Pre", 2, 4, 3))
    config = ValidationConfig(failure_models=models)
    if defect == "missing":
        result = AnalysisService(config).analyze_path(path).result
        assert result == _analyze_battery_frame(frame, failure_models=models)
        assert result["failure_models"]["evaluations"][0]["status"] == "NOT_EVALUATED"
        return
    with pytest.raises(
        ValueError,
        match="dimensionless"
        if defect == "unit"
        else "ambiguous"
        if defect == "duplicate"
        else "Precharge status",
    ):
        AnalysisService(config).analyze_path(path)
    if defect in ("unit", "duplicate"):
        return
    config = replace(config, data_quality=DataQualityConfig("exclude_invalid_rows"))
    result = AnalysisService(config).analyze_path(path).result
    assert (
        result["rows_excluded"] == 0
        and result["failure_models"]["evaluations"][0]["status"] == "NOT_EVALUATED"
    )
    if defect == "invalidation":
        assert result == _analyze_battery_frame(
            frame, failure_models=models, data_quality=config.data_quality
        )


def test_real_mf4_precharge_async_status_is_not_filled(tmp_path):
    path = tmp_path / "precharge.mf4"
    _write_precharge(path, grouped=False, asynchronous=True)
    models = FailureModelConfig(1, precharge_current=PrechargeCurrentConfig("Pre", 2, 4, 3))
    with pytest.raises(ValueError, match="Precharge status.*data row 2"):
        AnalysisService(ValidationConfig(failure_models=models)).analyze_path(path)
    result = (
        AnalysisService(
            ValidationConfig(
                failure_models=models, data_quality=DataQualityConfig("exclude_invalid_rows")
            )
        )
        .analyze_path(path)
        .result
    )
    assert (
        result["rows_excluded"] == 0
        and result["failure_models"]["evaluations"][0]["status"] == "NOT_EVALUATED"
    )
    assert not result["failure_models"]["evaluations"][0]["events"]
