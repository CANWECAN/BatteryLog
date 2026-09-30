from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from batterylog.config import ValidationLimits
from batterylog.models import RuleCode, ViolationEvent

from .comparison import exceeds_limit_scalar
from .evaluation import RuleEvaluation, rule_prefers_lower
from .rules import contiguous_true_ranges


def _merge_streaming_events(
    previous: ViolationEvent,
    current: ViolationEvent,
    *,
    prefer_lower: bool,
    previous_peak_value: float | None = None,
    current_peak_value: float | None = None,
) -> tuple[ViolationEvent, float]:
    previous_comparison_value = (
        previous["measured_value"] if previous_peak_value is None else previous_peak_value
    )
    current_comparison_value = (
        current["measured_value"] if current_peak_value is None else current_peak_value
    )
    current_is_more_severe = (
        current_comparison_value < previous_comparison_value
        if prefer_lower
        else current_comparison_value > previous_comparison_value
    )

    duration_s = current["end_time_s"] - previous["start_time_s"]
    if not np.isfinite(duration_s):
        raise ValueError("Violation event evidence calculation overflowed")

    merged: ViolationEvent = {
        **previous,
        "end_time_s": current["end_time_s"],
        "sample_count": previous["sample_count"] + current["sample_count"],
        "duration_s": round(duration_s, 12),
    }
    if current_is_more_severe:
        merged["peak_time_s"] = current["peak_time_s"]
        merged["measured_value"] = current["measured_value"]
        merged["peak_excursion"] = current["peak_excursion"]
        merged["signals"] = current["signals"]
        if current["code"] == "PACK_VOLTAGE_CELL_SUM_MISMATCH":
            merged["pack_voltage_v"] = current["pack_voltage_v"]
            merged["cell_voltage_sum_v"] = current["cell_voltage_sum_v"]
            merged["signed_error_v"] = current["signed_error_v"]

    merged_peak_value = (
        current_comparison_value if current_is_more_severe else previous_comparison_value
    )
    return merged, merged_peak_value


@dataclass
class _StreamingRuleState:
    prefer_lower: bool
    completed: list[ViolationEvent] = field(default_factory=list)
    pending: ViolationEvent | None = None
    pending_peak_value: float | None = None
    last_active_time_s: float | None = None

    def consume(
        self,
        *,
        ranges: list[tuple[int, int]],
        events: list[ViolationEvent],
        timestamps: pd.Series,
        max_gap_s: float | None,
        peak_values: pd.Series | None = None,
    ) -> None:
        if len(ranges) != len(events):
            raise RuntimeError("Streaming event/range count mismatch")
        if peak_values is not None and len(peak_values) != len(timestamps):
            raise RuntimeError("Streaming peak/timestamp count mismatch")
        if len(timestamps) == 0:
            return

        timestamp_values = timestamps.to_numpy(dtype=float, copy=False)
        chunk_events = list(events)
        if peak_values is None:
            chunk_peak_values = [event["measured_value"] for event in events]
        else:
            raw_peak_values = peak_values.to_numpy(dtype=float, copy=False)
            chunk_peak_values = [
                float(
                    np.min(raw_peak_values[start : end + 1])
                    if self.prefer_lower
                    else np.max(raw_peak_values[start : end + 1])
                )
                for start, end in ranges
            ]

        if self.pending is not None:
            joins_previous = bool(ranges and ranges[0][0] == 0)
            if joins_previous and max_gap_s is not None and self.last_active_time_s is not None:
                gap_s = float(timestamp_values[0] - self.last_active_time_s)
                joins_previous = not exceeds_limit_scalar(gap_s, max_gap_s)

            if joins_previous:
                previous_peak_value = (
                    self.pending["measured_value"]
                    if self.pending_peak_value is None
                    else self.pending_peak_value
                )
                chunk_events[0], chunk_peak_values[0] = _merge_streaming_events(
                    self.pending,
                    chunk_events[0],
                    prefer_lower=self.prefer_lower,
                    previous_peak_value=previous_peak_value,
                    current_peak_value=chunk_peak_values[0],
                )
            else:
                self.completed.append(self.pending)

            self.pending = None
            self.pending_peak_value = None
            self.last_active_time_s = None

        last_position = len(timestamps) - 1
        for (_, end), event, peak_value in zip(
            ranges,
            chunk_events,
            chunk_peak_values,
            strict=True,
        ):
            if end == last_position:
                self.pending = event
                self.pending_peak_value = peak_value
                self.last_active_time_s = float(timestamp_values[end])
            else:
                self.completed.append(event)

    def finish(self) -> list[ViolationEvent]:
        if self.pending is not None:
            self.completed.append(self.pending)
            self.pending = None
            self.pending_peak_value = None
            self.last_active_time_s = None
        return self.completed


@dataclass
class StreamingEventAccumulator:
    states: dict[RuleCode, _StreamingRuleState]

    @classmethod
    def for_rules(
        cls,
        rules: list[RuleCode],
        limits: ValidationLimits,
    ) -> "StreamingEventAccumulator":
        return cls(
            states={
                code: _StreamingRuleState(
                    prefer_lower=rule_prefers_lower(code, limits),
                )
                for code in rules
            }
        )

    def consume(
        self,
        evaluation: RuleEvaluation,
        *,
        timestamps: pd.Series,
        max_gap_s: float | None,
    ) -> None:
        ranges = contiguous_true_ranges(
            evaluation.mask,
            timestamps=timestamps,
            max_gap_s=max_gap_s,
        )
        self.states[evaluation.code].consume(
            ranges=ranges,
            events=evaluation.events,
            timestamps=timestamps,
            max_gap_s=max_gap_s,
            peak_values=evaluation.peak_values,
        )

    def finish(self) -> list[ViolationEvent]:
        violations = [event for state in self.states.values() for event in state.finish()]
        violations.sort(key=lambda event: (event["start_time_s"], event["code"]))
        return violations
