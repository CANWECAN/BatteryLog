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
    DataQualityConfig,
    FailureModelConfig,
    SignalMapping,
    SignalPattern,
    SourceUnits,
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
