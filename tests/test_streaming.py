from itertools import accumulate
from pathlib import Path

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from batterylog import EventDetectionConfig, SignalMapping, SignalPattern, ValidationLimits
from batterylog.analysis.core import _analyze_battery_frame
from batterylog.analysis.streaming import _analyze_battery_chunks, analyze_measurement_loader
from batterylog.loaders import iter_battery_csv, load_battery_csv

LIMITS = ValidationLimits(
    cell_min_v=2.8,
    cell_max_v=4.2,
    imbalance_max_v=0.08,
    temperature_min_c=-20.0,
    temperature_max_c=55.0,
)

CELL_VALUE = st.one_of(
    st.sampled_from([2.8, 2.79, 3.7, 4.2, 4.21]),
    st.floats(
        min_value=2.5,
        max_value=4.5,
        allow_nan=False,
        allow_infinity=False,
        width=32,
    ),
)
TEMP_VALUE = st.one_of(
    st.sampled_from([-20.0, -20.1, 25.0, 55.0, 55.1]),
    st.floats(
        min_value=-40.0,
        max_value=80.0,
        allow_nan=False,
        allow_infinity=False,
        width=32,
    ),
)


@st.composite
def battery_frames(draw) -> pd.DataFrame:
    row_count = draw(st.integers(min_value=1, max_value=30))
    gaps = draw(
        st.lists(
            st.one_of(
                st.sampled_from([0.0, 0.5, 1.0, 5.0]),
                st.floats(
                    min_value=0.0,
                    max_value=5.0,
                    allow_nan=False,
                    allow_infinity=False,
                    width=32,
                ),
            ),
            min_size=row_count,
            max_size=row_count,
        )
    )
    timestamps = list(accumulate(gaps))
    return pd.DataFrame(
        {
            "timestamp_s": timestamps,
            "temp_1_c": draw(st.lists(TEMP_VALUE, min_size=row_count, max_size=row_count)),
            "temp_2_c": draw(st.lists(TEMP_VALUE, min_size=row_count, max_size=row_count)),
            "cell_1_v": draw(st.lists(CELL_VALUE, min_size=row_count, max_size=row_count)),
            "cell_2_v": draw(st.lists(CELL_VALUE, min_size=row_count, max_size=row_count)),
            "cell_3_v": draw(st.lists(CELL_VALUE, min_size=row_count, max_size=row_count)),
        }
    )


def _write_boundary_fixture(path: Path) -> None:
    path.write_text(
        "timestamp_s,temp_1_c,temp_2_c,cell_1_v,cell_2_v,cell_3_v\n"
        "0,25,24,3.80,3.79,3.78\n"
        "1,56,54,4.30,3.90,3.88\n"
        "2,57,55,4.30,3.91,3.87\n"
        "3,58,56,4.35,3.92,3.86\n"
        "4,25,24,3.80,3.79,3.78\n"
        "5,-25,-19,3.00,2.70,2.95\n"
        "6,-30,-18,3.00,2.60,2.96\n"
        "7,25,24,3.80,3.79,3.78\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("chunk_rows", [1, 2, 3, 4, 5])
def test_streaming_matches_whole_frame_across_chunk_boundaries(
    tmp_path: Path,
    chunk_rows: int,
) -> None:
    path = tmp_path / "boundary.csv"
    _write_boundary_fixture(path)

    expected = _analyze_battery_frame(load_battery_csv(path), limits=LIMITS)
    actual = _analyze_battery_chunks(
        iter_battery_csv(path, chunk_rows=chunk_rows),
        limits=LIMITS,
    )

    assert actual == expected


def test_pack_signal_extrema_are_chunk_boundary_invariant(tmp_path: Path) -> None:
    path = tmp_path / "pack.csv"
    path.write_text(
        "timestamp_s,pack_current_a,pack_voltage_v,temp_c,cell_1_v\n"
        "0,-20,398,25,3.8\n"
        "1,0,400,26,3.9\n"
        "2,35,405,27,3.85\n",
        encoding="utf-8",
    )

    expected = _analyze_battery_frame(load_battery_csv(path))
    actual = _analyze_battery_chunks(
        iter_battery_csv(path, chunk_rows=1),
    )

    assert actual == expected
    assert actual["min_pack_current_a"] == -20.0
    assert actual["max_pack_current_a"] == 35.0
    assert actual["min_pack_voltage_v"] == 398.0
    assert actual["max_pack_voltage_v"] == 405.0


def test_streaming_preserves_first_equal_peak_across_chunk_boundary(tmp_path: Path) -> None:
    path = tmp_path / "equal_peak.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v,cell_2_v\n"
        "0,25,3.80,3.79\n"
        "1,25,4.30,3.90\n"
        "2,25,4.30,3.91\n"
        "3,25,3.80,3.79\n",
        encoding="utf-8",
    )
    limits = ValidationLimits(cell_max_v=4.2)

    result = _analyze_battery_chunks(
        iter_battery_csv(path, chunk_rows=2),
        limits=limits,
    )

    assert result["violations"] == [
        {
            "code": "CELL_OVERVOLTAGE",
            "start_time_s": 1.0,
            "end_time_s": 2.0,
            "peak_time_s": 1.0,
            "measured_value": 4.3,
            "limit_value": 4.2,
            "unit": "V",
            "signals": ["cell_1_v"],
        }
    ]


def test_streaming_max_gap_s_splits_event_across_chunk_boundary(tmp_path: Path) -> None:
    path = tmp_path / "gap.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v,cell_2_v\n"
        "0,25,3.80,3.79\n"
        "1,25,4.30,3.90\n"
        "10,25,4.31,3.91\n"
        "11,25,3.80,3.79\n",
        encoding="utf-8",
    )
    limits = ValidationLimits(cell_max_v=4.2)
    event_detection = EventDetectionConfig(max_gap_s=2.0)

    expected = _analyze_battery_frame(
        load_battery_csv(path),
        limits=limits,
        event_detection=event_detection,
    )
    actual = _analyze_battery_chunks(
        iter_battery_csv(path, chunk_rows=2),
        limits=limits,
        event_detection=event_detection,
    )

    assert actual == expected
    assert len(actual["violations"]) == 2


def test_streaming_rejects_timestamp_regression_between_chunks(tmp_path: Path) -> None:
    path = tmp_path / "timestamp_regression.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v\n0,25,3.80\n1,25,3.81\n0.5,25,3.82\n2,25,3.83\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="timestamp_s must be non-decreasing"):
        _analyze_battery_chunks(
            iter_battery_csv(path, chunk_rows=2),
            limits=ValidationLimits(cell_max_v=4.2),
        )


def test_streaming_invalid_value_reports_global_data_row(tmp_path: Path) -> None:
    path = tmp_path / "invalid_second_chunk.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v\n0,25,3.80\n1,25,3.81\n2,25,bad\n3,25,3.83\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"data row 3 .*column 'cell_1_v': 'bad'"):
        _analyze_battery_chunks(
            iter_battery_csv(path, chunk_rows=2),
            limits=ValidationLimits(cell_max_v=4.2),
        )


@given(
    frame=battery_frames(),
    chunk_rows=st.integers(min_value=1, max_value=10),
    max_gap_s=st.one_of(
        st.none(),
        st.sampled_from([0.0, 0.5, 1.0, 2.0, 5.0]),
    ),
)
def test_streaming_is_differentially_equivalent_to_whole_frame(
    frame: pd.DataFrame,
    chunk_rows: int,
    max_gap_s: float | None,
) -> None:
    event_detection = EventDetectionConfig(max_gap_s=max_gap_s)
    expected = _analyze_battery_frame(
        frame.copy(),
        limits=LIMITS,
        event_detection=event_detection,
    )
    chunks = [
        frame.iloc[start : start + chunk_rows].copy() for start in range(0, len(frame), chunk_rows)
    ]
    actual = _analyze_battery_chunks(
        chunks,
        limits=LIMITS,
        event_detection=event_detection,
    )

    assert actual == expected


def test_standard_file_analysis_does_not_materialize_source_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "streamed.csv"
    _write_boundary_fixture(path)
    real_read_bytes = Path.read_bytes
    guarded_path = path.resolve()

    def guarded_read_bytes(candidate: Path) -> bytes:
        if candidate.resolve() == guarded_path:
            raise AssertionError("standard CSV analysis must not read the whole source into bytes")
        return real_read_bytes(candidate)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    from batterylog import analyze_battery_log

    result = analyze_battery_log(path, limits=LIMITS)
    assert result["rows_analyzed"] == 8


@pytest.mark.parametrize("chunk_rows", [0, -1, True])
def test_csv_chunk_iterator_rejects_invalid_chunk_size(
    tmp_path: Path,
    chunk_rows: int,
) -> None:
    path = tmp_path / "sample.csv"
    path.write_text("timestamp_s,temp_c,cell_1_v\n0,25,3.8\n", encoding="utf-8")

    with pytest.raises(ValueError, match="chunk_rows must be a positive integer"):
        next(iter_battery_csv(path, chunk_rows=chunk_rows))


class _FakeMeasurementLoader:
    source_format = "fake"

    def __init__(self, chunks: list[pd.DataFrame]) -> None:
        self._chunks = chunks
        self.seen_mapping: SignalMapping | None = None

    def iter_chunks(
        self,
        *,
        signal_mapping: SignalMapping | None,
    ):
        self.seen_mapping = signal_mapping
        yield from self._chunks


def test_generic_loader_contract_is_csv_independent() -> None:
    raw = pd.DataFrame(
        {
            "time_vendor": [0.0, 1.0, 2.0],
            "U_Cell_01": [3.8, 4.3, 3.8],
            "U_Cell_02": [3.79, 3.9, 3.79],
            "T_Mod_01": [25.0, 56.0, 25.0],
        }
    )
    mapping = SignalMapping(
        timestamp="time_vendor",
        cell_voltage=SignalPattern(pattern=r"U_Cell_(?P<index>[0-9]+)"),
        temperature=SignalPattern(pattern=r"T_Mod_(?P<index>[0-9]+)"),
    )
    loader = _FakeMeasurementLoader([raw.iloc[:2].copy(), raw.iloc[2:].copy()])

    expected = _analyze_battery_frame(raw, limits=LIMITS, signal_mapping=mapping)
    actual = analyze_measurement_loader(loader, limits=LIMITS, signal_mapping=mapping)

    assert actual == expected
    assert loader.seen_mapping is mapping


def test_pack_overcurrent_streaming_matches_whole_frame_across_chunk_boundary() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0, 3.0],
            "pack_current_a": [-60.0, -55.0, 0.0, 130.0],
            "temp_c": [25.0, 25.0, 25.0, 25.0],
            "cell_1_v": [3.8, 3.8, 3.8, 3.8],
        }
    )
    limits = ValidationLimits(
        pack_charge_max_a=50.0,
        pack_discharge_max_a=100.0,
        pack_current_positive_direction="discharge",
    )

    expected = _analyze_battery_frame(frame, limits=limits)
    actual = _analyze_battery_chunks(
        [frame.iloc[:1].copy(), frame.iloc[1:3].copy(), frame.iloc[3:].copy()],
        limits=limits,
    )

    assert actual == expected

def test_temperature_spread_streaming_matches_whole_frame_across_chunk_boundary() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0, 3.0],
            "temp_1_c": [20.0, 22.0, 24.0, 25.0],
            "temp_2_c": [30.0, 34.0, 40.0, 30.0],
            "cell_1_v": [3.8, 3.8, 3.8, 3.8],
        }
    )
    limits = ValidationLimits(temperature_spread_max_c=10.0)
    expected = _analyze_battery_frame(frame, limits=limits)
    actual = _analyze_battery_chunks(
        [frame.iloc[:2].copy(), frame.iloc[2:3].copy(), frame.iloc[3:].copy()],
        limits=limits,
    )
    assert actual == expected
