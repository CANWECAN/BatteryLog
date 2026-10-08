"""Finite, unrounded event evidence shared by bounded-state failure models."""

from math import isclose, isfinite

from batterylog.failure_models import FailureCode, FailureEvent

from .comparison import BINARY64_REL_TOL


def _finite(value: float) -> float:
    if not isfinite(value):
        raise ValueError("Failure-model evidence calculation overflowed")
    return value


def _above(value: float, limit: float) -> bool:
    return value > limit and not isclose(value, limit, rel_tol=BINARY64_REL_TOL, abs_tol=0)


def _at_least(value: float, limit: float) -> bool:
    return value >= limit or isclose(value, limit, rel_tol=BINARY64_REL_TOL, abs_tol=0)


def _event(
    code: FailureCode,
    start: float,
    end: float,
    peak: float,
    measured: float,
    limit: float,
    count: int,
    unit: str,
    signals: list[str],
    evidence: dict[str, float],
) -> FailureEvent:
    return {
        "code": code,
        "start_time_s": start,
        "end_time_s": end,
        "peak_time_s": peak,
        "measured_value": _finite(measured),
        "limit_value": limit,
        "sample_count": count,
        "duration_s": _finite(end - start),
        "peak_excursion": _finite(abs(measured - limit)),
        "unit": unit,
        "signals": signals,
        "evidence": {name: _finite(value) for name, value in evidence.items()},
    }
