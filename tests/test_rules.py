import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from batterylog.analysis.rules import contiguous_true_ranges


def _covered_positions(ranges: list[tuple[int, int]]) -> list[int]:
    return [position for start, end in ranges for position in range(start, end + 1)]


def test_gap_grouping_requires_timestamps() -> None:
    mask = pd.Series([True, True])

    with pytest.raises(ValueError, match="timestamps are required"):
        contiguous_true_ranges(mask, max_gap_s=0.5)


def test_gap_grouping_requires_matching_lengths() -> None:
    mask = pd.Series([True, True])
    timestamps = pd.Series([0.0])

    with pytest.raises(ValueError, match="same length"):
        contiguous_true_ranges(
            mask,
            timestamps=timestamps,
            max_gap_s=0.5,
        )


@given(st.lists(st.booleans(), max_size=200))
def test_contiguous_ranges_cover_exactly_the_true_mask(mask_values: list[bool]) -> None:
    mask = pd.Series(mask_values, dtype=bool)

    ranges = contiguous_true_ranges(mask)

    expected = [position for position, active in enumerate(mask_values) if active]
    assert _covered_positions(ranges) == expected

    for start, end in ranges:
        assert start <= end
        assert all(mask_values[start : end + 1])


@st.composite
def _gap_cases(draw: st.DrawFn) -> tuple[list[bool], list[float], float]:
    size = draw(st.integers(min_value=1, max_value=150))
    mask = draw(st.lists(st.booleans(), min_size=size, max_size=size))
    gaps = draw(
        st.lists(
            st.integers(min_value=0, max_value=5),
            min_size=max(0, size - 1),
            max_size=max(0, size - 1),
        )
    )
    max_gap = float(draw(st.integers(min_value=0, max_value=5)))

    timestamps = [0.0]
    for gap in gaps:
        timestamps.append(timestamps[-1] + float(gap))

    return mask, timestamps, max_gap


@given(_gap_cases())
def test_gap_grouping_preserves_mask_and_splits_only_on_requested_boundaries(
    case: tuple[list[bool], list[float], float],
) -> None:
    mask_values, timestamp_values, max_gap = case
    mask = pd.Series(mask_values, dtype=bool)
    timestamps = pd.Series(timestamp_values, dtype=float)

    ranges = contiguous_true_ranges(
        mask,
        timestamps=timestamps,
        max_gap_s=max_gap,
    )

    expected = [position for position, active in enumerate(mask_values) if active]
    assert _covered_positions(ranges) == expected

    event_for_position: dict[int, int] = {}
    for event_id, (start, end) in enumerate(ranges):
        for position in range(start, end + 1):
            event_for_position[position] = event_id

    for position in range(1, len(mask_values)):
        if not (mask_values[position - 1] and mask_values[position]):
            continue

        gap = timestamp_values[position] - timestamp_values[position - 1]
        same_event = event_for_position[position - 1] == event_for_position[position]
        assert same_event is (gap <= max_gap)
