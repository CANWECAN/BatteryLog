"""Explicit opt-in parameters for log-derived failure models.

No chemistry-specific limits or timing assumptions are supplied by default.
"""

from dataclasses import MISSING, dataclass, fields
from math import isfinite
from typing import Any

from .models import CurrentDirection


def _number(name: str, value: float, *, positive: bool = True) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    try:
        finite = isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0 or (positive and value == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be finite and {qualifier}")


@dataclass(frozen=True)
class SustainedImbalanceConfig:
    max_delta_v: float
    duration_s: float

    def __post_init__(self) -> None:
        _number("max_delta_v", self.max_delta_v, positive=False)
        _number("duration_s", self.duration_s)


@dataclass(frozen=True)
class TemperatureRiseConfig:
    max_c_per_min: float
    min_interval_s: float

    def __post_init__(self) -> None:
        _number("max_c_per_min", self.max_c_per_min, positive=False)
        _number("min_interval_s", self.min_interval_s)


@dataclass(frozen=True)
class CellSagConfig:
    positive_direction: CurrentDirection
    baseline_max_abs_current_a: float
    load_min_discharge_a: float
    baseline_max_age_s: float
    settling_s: float
    excess_sag_max_v: float

    def __post_init__(self) -> None:
        if self.positive_direction not in {"charge", "discharge"}:
            raise ValueError("positive_direction must be 'charge' or 'discharge'")
        for name in ("baseline_max_abs_current_a", "settling_s", "excess_sag_max_v"):
            _number(name, getattr(self, name), positive=False)
        for name in ("load_min_discharge_a", "baseline_max_age_s"):
            _number(name, getattr(self, name))
        if self.load_min_discharge_a <= self.baseline_max_abs_current_a:
            raise ValueError("load_min_discharge_a must exceed baseline_max_abs_current_a")


@dataclass(frozen=True)
class BalancingConfig:
    active_source: str
    evaluation_s: float
    min_improvement_v: float
    min_start_delta_v: float
    timeout_s: float

    def __post_init__(self) -> None:
        if not isinstance(self.active_source, str):
            raise TypeError("active_source must be a string")
        if not self.active_source:
            raise ValueError("active_source must not be empty")
        for name in ("evaluation_s", "min_improvement_v", "min_start_delta_v", "timeout_s"):
            _number(name, getattr(self, name))
        if self.min_improvement_v > self.min_start_delta_v:
            raise ValueError("min_improvement_v must not exceed min_start_delta_v")


@dataclass(frozen=True)
class UnloadedCurrentConfig:
    unloaded_source: str
    max_abs_current_a: float
    duration_s: float

    def __post_init__(self) -> None:
        if not isinstance(self.unloaded_source, str):
            raise TypeError("unloaded_source must be a string")
        if not self.unloaded_source.strip():
            raise ValueError("unloaded_source must not be empty")
        _number("max_abs_current_a", self.max_abs_current_a, positive=False)
        _number("duration_s", self.duration_s)


@dataclass(frozen=True)
class FailureModelConfig:
    max_gap_s: float
    sustained_imbalance: SustainedImbalanceConfig | None = None
    temperature_rise: TemperatureRiseConfig | None = None
    cell_sag: CellSagConfig | None = None
    balancing: BalancingConfig | None = None
    unloaded_current: UnloadedCurrentConfig | None = None

    def __post_init__(self) -> None:
        _number("failure_models.max_gap_s", self.max_gap_s)
        enabled = False
        for name, kind in (
            ("sustained_imbalance", SustainedImbalanceConfig),
            ("temperature_rise", TemperatureRiseConfig),
            ("cell_sag", CellSagConfig),
            ("balancing", BalancingConfig),
            ("unloaded_current", UnloadedCurrentConfig),
        ):
            value = getattr(self, name)
            if value is not None:
                enabled = True
                if not isinstance(value, kind):
                    raise TypeError(f"{name} must be a {kind.__name__} instance or null")
        if not enabled:
            raise ValueError("failure_models must enable at least one model")
        if self.temperature_rise and self.temperature_rise.min_interval_s > self.max_gap_s:
            raise ValueError("min_interval_s must not exceed failure_models.max_gap_s")


def parse_failure_models(raw: Any) -> FailureModelConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("failure_models must be a mapping or null")
    allowed = {item.name for item in fields(FailureModelConfig)}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown failure_models key(s): {', '.join(sorted(unknown))}")
    if "max_gap_s" not in raw:
        raise ValueError("failure_models.max_gap_s is required")
    parsed = dict(raw)
    for name, kind in (
        ("sustained_imbalance", SustainedImbalanceConfig),
        ("temperature_rise", TemperatureRiseConfig),
        ("cell_sag", CellSagConfig),
        ("balancing", BalancingConfig),
        ("unloaded_current", UnloadedCurrentConfig),
    ):
        group = raw.get(name)
        if group is None:
            continue
        if not isinstance(group, dict):
            raise TypeError(f"failure_models.{name} must be a mapping or null")
        names = {item.name for item in fields(kind)}
        unknown = set(group) - names
        if unknown:
            raise ValueError(f"Unknown failure_models.{name} key(s): {', '.join(sorted(unknown))}")
        required = {item.name for item in fields(kind) if item.default is MISSING}
        missing = required - set(group)
        if missing:
            raise ValueError(f"Missing failure_models.{name} key(s): {', '.join(sorted(missing))}")
        parsed[name] = kind(**group)
    return FailureModelConfig(**parsed)
