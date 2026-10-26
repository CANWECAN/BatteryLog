"""Origin-independent CSV preparation, with explicit source-clock evidence."""

import hashlib
import json
from decimal import Decimal, Inexact, Subnormal, localcontext
from fractions import Fraction

import pandas as pd
import pytest

from batterylog import (
    FailureModelConfig,
    SignalMapping,
    SignalPattern,
    SourceUnits,
    TemperatureRiseConfig,
    ValidationConfig,
    analyze_battery_log,
    normalize_measurement,
)
from batterylog import normalization as module
from batterylog.__main__ import run


def _source(tmp_path, times, temperatures=None, *, mapped=False):
    path = tmp_path / "source.csv"
    temperatures = [25] * len(times) if temperatures is None else temperatures
    header = "clock,U1,T1" if mapped else "timestamp_s,cell_1_v,temp_c"
    path.write_text(
        header + "\n" + "".join(f"{t},3.7,{v}\n" for t, v in zip(times, temperatures)),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "origin,unit,scale",
    [
        ("0", "s", 1),
        ("1700000000", "s", 1),
        ("-1700000000000", "ms", 1000),
        ("1700000000000000", "us", 1000000),
    ],
)
@pytest.mark.parametrize("chunk_rows", [1, 100])
@pytest.mark.parametrize("minimum", [0.05, 0.1])
@pytest.mark.parametrize("rise,status", [("0.124", "PASS"), ("0.125", "PASS"), ("0.126", "FAIL")])
def test_rate_classification_and_eligible_pairs_are_origin_independent(
    tmp_path, monkeypatch, origin, unit, scale, chunk_rows, minimum, rise, status
):
    times = [str(Decimal(origin) + Decimal(i) * scale / 10) for i in range(6)]
    temperatures = [str(Decimal(25) + Decimal(i) * Decimal(rise)) for i in range(6)]
    source = _source(tmp_path, times, temperatures)
    monkeypatch.setattr(module, "DEFAULT_CSV_CHUNK_ROWS", chunk_rows)
    destination = tmp_path / "prepared"
    result = normalize_measurement(
        source, destination, units=SourceUnits(unit, "V", "degC"), relative_time=True
    )
    prepared = destination / "normalized.csv"
    assert pd.read_csv(prepared)["timestamp_s"].tolist() == [i / 10 for i in range(6)]
    analysis = analyze_battery_log(
        prepared,
        failure_models=FailureModelConfig(1, temperature_rise=TemperatureRiseConfig(75, minimum)),
    )
    model = analysis["failure_models"]["evaluations"][0]
    assert analysis["validation_status"] == model["status"] == status
    assert model["evaluated_samples"] == 5
    if status == "FAIL":
        assert len(model["events"]) == 1
        event = model["events"][0]
        assert event["sample_count"] == 5
        assert 0.1 <= event["peak_time_s"] <= 0.5
        assert event["evidence"]["interval_s"] == pytest.approx(0.1)
    else:
        assert model["events"] == []
    assert result["time_basis"]["source_origin"] == times[0]
    assert result["normalization_schema_version"] == 2


@pytest.mark.parametrize("chunk_rows", [1, 2, 100])
def test_exact_origin_mapping_duplicates_and_source_hashes(tmp_path, monkeypatch, chunk_rows):
    times = [
        "9007199254740993.0000000",
        "9007199254740993.0000001",
        "9007199254740993.0000001",
        "9007199254740993.0000003",
    ]
    source = _source(tmp_path, times, mapped=True)
    original = source.read_bytes()
    config = ValidationConfig(
        signals=SignalMapping(
            "clock", SignalPattern(r"U(?P<index>\d+)"), SignalPattern(r"T(?P<index>\d+)")
        )
    )
    monkeypatch.setattr(module, "DEFAULT_CSV_CHUNK_ROWS", chunk_rows)
    destination = tmp_path / "prepared"
    result = normalize_measurement(
        source,
        destination,
        units=SourceUnits("s", "V", "degC"),
        config=config,
        relative_time=True,
    )
    output = destination / "normalized.csv"
    frame = pd.read_csv(output)
    assert frame["timestamp_s"].tolist() == [0, 1e-7, 1e-7, 3e-7]
    assert len(frame) == result["rows_written"] == 4
    assert result["source"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert result["normalized_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert source.read_bytes() == original
    assert result["conversions"][0]["source"] == "clock"
    assert result["time_basis"] == {
        "mode": "relative_to_first_sample",
        "source_origin": times[0],
        "source_unit": "s",
        "divisor": 1,
        "output_unit": "s",
        "arithmetic": "exact_decimal_difference_then_binary64",
    }
    # The manifest defines the inverse relationship without binary64 epoch addition.
    absolute = Decimal(result["time_basis"]["source_origin"]) + Decimal("0.0000003")
    assert absolute == Decimal(times[-1])
    assert json.loads((destination / "conversion.json").read_text()) == result
    assert result["analysis_performed"] is False


def test_relative_clock_does_not_inherit_decimal_context(tmp_path):
    source = _source(tmp_path, ["1700000000", "1700000000.1"])
    with localcontext() as context:
        context.prec, context.Emax, context.Emin = 2, 6, -2
        context.traps[Inexact] = context.traps[Subnormal] = True
        normalize_measurement(
            source,
            tmp_path / "out",
            units=SourceUnits("s", "V", "degC"),
            relative_time=True,
        )
        assert (context.prec, context.Emax, context.Emin) == (2, 6, -2)
        assert not any(context.flags.values())
    assert pd.read_csv(tmp_path / "out/normalized.csv")["timestamp_s"].tolist() == [0, 0.1]


@pytest.mark.parametrize(
    "times,match",
    [
        (["1700000000.0000001", "1700000000.0000000"], "non-decreasing"),
        (["1700000000", "nan"], "numeric"),
        (["1700000000", "Infinity"], "numeric"),
        (["0", "1e129"], "Relative-time timestamp"),
        (["0", "1e-129"], "Relative-time timestamp"),
        (["0", "0." + "0" * 254 + "1"], "Relative-time timestamp"),
        (["0", "9007199254740992", "9007199254740993"], "collapses distinct"),
    ],
)
@pytest.mark.parametrize("chunk_rows", [1, 100])
def test_relative_clock_rejects_bad_or_unrepresentable_time_atomically(
    tmp_path, monkeypatch, times, match, chunk_rows
):
    source = _source(tmp_path, times)
    monkeypatch.setattr(module, "DEFAULT_CSV_CHUNK_ROWS", chunk_rows)
    with pytest.raises(ValueError, match=match):
        normalize_measurement(
            source,
            tmp_path / "out",
            units=SourceUnits("s", "V", "degC"),
            relative_time=True,
        )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.csv"]


def test_default_preserves_source_clock_and_existing_envelope(tmp_path):
    source = _source(tmp_path, ["1700000000", "1700000000.1"])
    result = normalize_measurement(source, tmp_path / "out", units=SourceUnits("s", "V", "degC"))
    assert "time_basis" not in result
    assert result["normalization_schema_version"] == 1
    assert pd.read_csv(tmp_path / "out/normalized.csv")["timestamp_s"].iloc[0] == 1700000000


@pytest.mark.parametrize("value", [1, "true", None])
def test_relative_time_requires_boolean_before_output_creation(tmp_path, value):
    with pytest.raises(TypeError, match="relative_time must be a bool"):
        normalize_measurement(
            tmp_path / "missing.csv",
            tmp_path / "out",
            units=SourceUnits("s", "V", "degC"),
            relative_time=value,
        )
    assert not list(tmp_path.iterdir())


def test_relative_time_rejects_mdf_without_claiming_recovered_precision(tmp_path):
    with pytest.raises(ValueError, match="Relative-time preparation currently requires CSV"):
        normalize_measurement(
            tmp_path / "source.mf4",
            tmp_path / "out",
            units=SourceUnits("s", "V", "degC"),
            relative_time=True,
        )
    assert not list(tmp_path.iterdir())


def test_relative_normalization_keeps_real_gaps_and_observed_temperature_changes(tmp_path):
    source = _source(
        tmp_path,
        ["1700000000", "1700000000.1", "1700000010.1", "1700000010.2"],
        [25, 25, 70, 70.25],
    )
    normalize_measurement(
        source, tmp_path / "out", units=SourceUnits("s", "V", "degC"), relative_time=True
    )
    result = analyze_battery_log(
        tmp_path / "out/normalized.csv",
        failure_models=FailureModelConfig(1, temperature_rise=TemperatureRiseConfig(75, 0.05)),
    )
    model = result["failure_models"]["evaluations"][0]
    assert model["evaluated_samples"] == 2  # No interpolation over the 10-second gap.
    assert model["status"] == "FAIL"
    assert model["events"][0]["peak_time_s"] == 10.2


@pytest.mark.parametrize("interrupt", [False, True])
def test_relative_preparation_does_not_publish_after_source_change_or_interrupt(
    tmp_path, monkeypatch, interrupt
):
    source = _source(tmp_path, ["1700000000", "1700000000.1"])
    original = module.sha256_file

    def changed(path):
        if interrupt:
            raise KeyboardInterrupt
        source.write_text(source.read_text() + "1700000000.2,3.7,25\n")
        return original(path)

    monkeypatch.setattr(module, "sha256_file", changed)
    with pytest.raises(KeyboardInterrupt if interrupt else ValueError):
        normalize_measurement(
            source, tmp_path / "out", units=SourceUnits("s", "V", "degC"), relative_time=True
        )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.csv"]


def test_cli_relative_time_is_explicit_and_emits_clock_evidence(tmp_path, capsys):
    source = _source(tmp_path, ["1700000000", "1700000000.1"])
    assert run([str(source), "--relative-time"]) == 2
    assert capsys.readouterr().out == ""
    assert (
        run(
            [
                str(source),
                "--normalize",
                "--relative-time",
                "--time-unit",
                "s",
                "--cell-voltage-unit",
                "V",
                "--temperature-unit",
                "degC",
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert Fraction(Decimal(result["time_basis"]["source_origin"])) == 1700000000
    assert pd.read_csv(tmp_path / "out/normalized.csv")["timestamp_s"].tolist() == [0, 0.1]
