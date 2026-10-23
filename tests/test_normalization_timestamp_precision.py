"""Normalization must reject source-clock regressions before float conversion."""

import pytest

from batterylog import (
    SignalMapping,
    SignalPattern,
    SourceUnits,
    ValidationConfig,
    normalize_measurement,
)
from batterylog import normalization as module


def _write_source(tmp_path, timestamps, mapped):
    source = tmp_path / "source.csv"
    header = "clock,V1,T1" if mapped else "timestamp_s,cell_1_v,temp_c"
    source.write_text(header + "\n" + "".join(f"{t},3.7,25\n" for t in timestamps))
    mapping = (
        SignalMapping(
            timestamp="clock",
            cell_voltage=SignalPattern(pattern=r"V(?P<index>\d+)"),
            temperature=SignalPattern(pattern=r"T(?P<index>\d+)"),
        )
        if mapped
        else None
    )
    return source, ValidationConfig(signals=mapping)


@pytest.mark.parametrize(
    "first,second",
    [
        ("9007199254740993", "9007199254740992"),
        ("1700000000.0000001", "1700000000.0000000"),
        ("1.0000000000000001", "1.0000000000000000"),
        ("18446744073709551615", "18446744073709551614"),
        ("-9007199254740992", "-9007199254740993"),
    ],
)
@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize("chunk_rows", [1, 100])
def test_normalization_rejects_hidden_source_clock_regression(
    tmp_path, monkeypatch, first, second, mapped, chunk_rows
):
    source, config = _write_source(tmp_path, [first, second], mapped)
    monkeypatch.setattr(module, "DEFAULT_CSV_CHUNK_ROWS", chunk_rows)
    with pytest.raises(ValueError, match="timestamp_s must be non-decreasing"):
        normalize_measurement(
            source, tmp_path / "out", units=SourceUnits("s", "V", "degC"), config=config
        )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.csv"]


@pytest.mark.parametrize(
    "timestamps",
    [
        ["1700000000.0000000", "1700000000.0000001", "1700000000.0000001"],
        ["1.0000000000000002", "1.00000000000000021", "1.00000000000000021"],
    ],
)
@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize("chunk_rows", [1, 100])
def test_normalization_accepts_ordered_neighbours_and_duplicate_source_times(
    tmp_path, monkeypatch, timestamps, mapped, chunk_rows
):
    source, config = _write_source(tmp_path, timestamps, mapped)
    monkeypatch.setattr(module, "DEFAULT_CSV_CHUNK_ROWS", chunk_rows)
    result = normalize_measurement(
        source, tmp_path / "out", units=SourceUnits("s", "V", "degC"), config=config
    )
    assert result["rows_written"] == 3
    assert result["analysis_performed"] is False
    assert (tmp_path / "out" / "normalized.csv").is_file()
