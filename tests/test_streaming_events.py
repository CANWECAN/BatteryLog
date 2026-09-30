import pandas as pd
import pytest

from batterylog.analysis.evaluation import RuleEvaluation
from batterylog.analysis.streaming_events import StreamingEventAccumulator
from batterylog.config import ValidationLimits
from batterylog.models import RuleCode, ViolationEvent


def _event(
    *,
    code: RuleCode,
    time_s: float,
    measured: float,
    signal: str,
    limit: float = 0.1,
) -> ViolationEvent:
    return {
        "code": code,
        "start_time_s": time_s,
        "end_time_s": time_s,
        "peak_time_s": time_s,
        "measured_value": measured,
        "limit_value": limit,
        "sample_count": 1,
        "duration_s": 0.0,
        "peak_excursion": abs(measured - limit),
        "unit": "V",
        "signals": [signal],
    }


def _evaluation(
    *,
    time_s: float,
    measured: float,
    raw_peak: float,
    signal: str,
) -> RuleEvaluation:
    return RuleEvaluation(
        code="CELL_IMBALANCE_HIGH",
        mask=pd.Series([True]),
        events=[
            _event(
                code="CELL_IMBALANCE_HIGH",
                time_s=time_s,
                measured=measured,
                signal=signal,
            )
        ],
        peak_values=pd.Series([raw_peak]),
    )


def test_accumulator_uses_unrounded_peak_across_chunk_boundary() -> None:
    accumulator = StreamingEventAccumulator.for_rules(
        ["CELL_IMBALANCE_HIGH"],
        ValidationLimits(imbalance_max_v=0.1),
    )
    public_value = 0.100000000001

    accumulator.consume(
        _evaluation(
            time_s=0.0,
            measured=public_value,
            raw_peak=0.1000000000011,
            signal="cell_1_v",
        ),
        timestamps=pd.Series([0.0]),
        max_gap_s=None,
    )
    accumulator.consume(
        _evaluation(
            time_s=1.0,
            measured=public_value,
            raw_peak=0.1000000000012,
            signal="cell_2_v",
        ),
        timestamps=pd.Series([1.0]),
        max_gap_s=None,
    )

    violations = accumulator.finish()

    assert len(violations) == 1
    event = violations[0]
    assert event["start_time_s"] == 0.0
    assert event["end_time_s"] == 1.0
    assert event["sample_count"] == 2
    assert event["duration_s"] == 1.0
    assert event["peak_time_s"] == 1.0
    assert event["signals"] == ["cell_2_v"]


def test_accumulator_splits_cross_chunk_event_when_gap_exceeds_limit() -> None:
    accumulator = StreamingEventAccumulator.for_rules(
        ["CELL_IMBALANCE_HIGH"],
        ValidationLimits(imbalance_max_v=0.1),
    )

    accumulator.consume(
        _evaluation(
            time_s=0.0,
            measured=0.2,
            raw_peak=0.2,
            signal="cell_1_v",
        ),
        timestamps=pd.Series([0.0]),
        max_gap_s=5.0,
    )
    accumulator.consume(
        _evaluation(
            time_s=10.0,
            measured=0.3,
            raw_peak=0.3,
            signal="cell_2_v",
        ),
        timestamps=pd.Series([10.0]),
        max_gap_s=5.0,
    )

    violations = accumulator.finish()

    assert len(violations) == 2
    assert [event["start_time_s"] for event in violations] == [0.0, 10.0]


def test_accumulator_finish_flushes_pending_event_once() -> None:
    accumulator = StreamingEventAccumulator.for_rules(
        ["CELL_IMBALANCE_HIGH"],
        ValidationLimits(imbalance_max_v=0.1),
    )
    accumulator.consume(
        _evaluation(
            time_s=3.0,
            measured=0.2,
            raw_peak=0.2,
            signal="cell_1_v",
        ),
        timestamps=pd.Series([3.0]),
        max_gap_s=None,
    )

    first = accumulator.finish()
    second = accumulator.finish()

    assert len(first) == 1
    assert second == first


def test_accumulator_fails_closed_when_cross_chunk_duration_overflows() -> None:
    accumulator = StreamingEventAccumulator.for_rules(
        ["CELL_IMBALANCE_HIGH"],
        ValidationLimits(imbalance_max_v=0.1),
    )

    accumulator.consume(
        _evaluation(
            time_s=-1e308,
            measured=0.2,
            raw_peak=0.2,
            signal="cell_1_v",
        ),
        timestamps=pd.Series([-1e308]),
        max_gap_s=None,
    )

    with pytest.raises(ValueError, match="Violation event evidence calculation overflowed"):
        accumulator.consume(
            _evaluation(
                time_s=1e308,
                measured=0.3,
                raw_peak=0.3,
                signal="cell_2_v",
            ),
            timestamps=pd.Series([1e308]),
            max_gap_s=None,
        )
