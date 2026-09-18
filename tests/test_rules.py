import pandas as pd
import pytest

from batterylog.analysis.rules import contiguous_true_ranges


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
