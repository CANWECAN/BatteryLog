"""Evidence types shared by the temporal analyzer and result-v9 contract."""

from typing import Literal, TypedDict

from .models import ValidationStatus

FailureCode = Literal[
    "CELL_IMBALANCE_SUSTAINED",
    "TEMPERATURE_RISE_HIGH",
    "CELL_SAG_UNDER_LOAD",
    "BALANCING_INEFFECTIVE",
    "BALANCING_ACTIVE_TOO_LONG",
]


class FailureEvent(TypedDict):
    code: FailureCode
    start_time_s: float
    end_time_s: float
    peak_time_s: float
    measured_value: float
    limit_value: float
    sample_count: int
    duration_s: float
    peak_excursion: float
    unit: str
    signals: list[str]
    evidence: dict[str, float]


class FailureEvaluation(TypedDict):
    code: FailureCode
    status: ValidationStatus
    evaluated_samples: int
    incomplete_intervals: int
    reason: str | None
    events: list[FailureEvent]


class FailureModelReport(TypedDict):
    config: dict
    evaluations: list[FailureEvaluation]
