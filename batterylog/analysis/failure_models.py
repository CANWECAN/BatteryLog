"""Small bounded-state evaluators; the same collector handles any chunk size."""

from dataclasses import asdict, dataclass
from math import isclose, isfinite

import numpy as np
import pandas as pd

from batterylog.failure_config import FailureModelConfig
from batterylog.failure_models import (
    FailureCode,
    FailureEvaluation,
    FailureEvent,
    FailureModelReport,
)

from .comparison import BINARY64_REL_TOL
from .evaluation import RuleInputs
from .input_validation import parse_balancing_status

_BALANCING_CODES: tuple[FailureCode, ...] = (
    "BALANCING_INEFFECTIVE",
    "BALANCING_ACTIVE_TOO_LONG",
)


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


@dataclass
class _Run:
    start: float
    end: float
    peak: float
    measured: float
    signals: list[str]
    evidence: dict[str, float]
    count: int = 1

    def add(self, t: float, value: float, signals: list[str], evidence: dict[str, float]) -> None:
        self.end = t
        self.count += 1
        if value > self.measured:
            self.peak, self.measured, self.signals, self.evidence = t, value, signals, evidence

    def event(self, code: FailureCode, limit: float, unit: str) -> FailureEvent:
        return _event(
            code,
            self.start,
            self.end,
            self.peak,
            self.measured,
            limit,
            self.count,
            unit,
            self.signals,
            self.evidence,
        )


class FailureModelCollector:
    def __init__(self, config: FailureModelConfig | None) -> None:
        if config is not None and not isinstance(config, FailureModelConfig):
            raise TypeError("failure_models must be a FailureModelConfig instance or null")
        self.config = config
        self.evaluations: dict[FailureCode, FailureEvaluation] = {}
        if config is not None:
            models: list[tuple[object, FailureCode]] = [
                (config.sustained_imbalance, "CELL_IMBALANCE_SUSTAINED"),
                (config.temperature_rise, "TEMPERATURE_RISE_HIGH"),
                (config.cell_sag, "CELL_SAG_UNDER_LOAD"),
                (config.balancing, "BALANCING_INEFFECTIVE"),
                (config.balancing, "BALANCING_ACTIVE_TOO_LONG"),
            ]
            for enabled, code in models:
                if enabled is not None:
                    self.evaluations[code] = {
                        "code": code,
                        "status": "NOT_EVALUATED",
                        "evaluated_samples": 0,
                        "incomplete_intervals": 0,
                        "reason": None,
                        "events": [],
                    }
        self.previous_t: float | None = None
        self.span_start: float | None = None
        self.previous_temperatures: np.ndarray | None = None
        self.runs: dict[FailureCode, _Run] = {}
        self.baseline: tuple[float, float, np.ndarray] | None = None
        self.load_start: float | None = None
        self.load_baseline: tuple[float, float, np.ndarray] | None = None
        self.load_evaluated = False
        self.balance_previous: bool | None = None
        self.balance_start: float | None = None
        self.balance_last: float | None = None
        self.balance_initial = 0.0
        self.balance_count = 0
        self.balance_checked = False
        self.balance_timeout_emitted = False
        self.balance_invalid_censor = False
        self.balance_presence: bool | None = None

    def _flush(self, code: FailureCode) -> None:
        run = self.runs.pop(code, None)
        if run is None:
            return
        assert self.config is not None
        if code == "CELL_IMBALANCE_SUSTAINED":
            cfg = self.config.sustained_imbalance
            assert cfg is not None
            if not _at_least(_finite(run.end - run.start), cfg.duration_s):
                return
            limit, unit = cfg.max_delta_v, "V"
            run.evidence["required_duration_s"] = cfg.duration_s
        elif code == "TEMPERATURE_RISE_HIGH":
            cfg_rise = self.config.temperature_rise
            assert cfg_rise is not None
            limit, unit = cfg_rise.max_c_per_min, "degC/min"
        else:
            cfg_sag = self.config.cell_sag
            assert cfg_sag is not None
            limit, unit = cfg_sag.excess_sag_max_v, "V"
        self.evaluations[code]["events"].append(run.event(code, limit, unit))

    def _threshold(
        self,
        code: FailureCode,
        t: float,
        value: float,
        limit: float,
        signals: list[str],
        evidence: dict[str, float],
    ) -> None:
        if not _above(value, limit):
            self._flush(code)
        elif code in self.runs:
            self.runs[code].add(t, value, signals, evidence)
        else:
            self.runs[code] = _Run(t, t, t, value, signals, evidence)

    def _end_load(self) -> None:
        self._flush("CELL_SAG_UNDER_LOAD")
        if self.load_start is not None and not self.load_evaluated:
            self.evaluations["CELL_SAG_UNDER_LOAD"]["incomplete_intervals"] += 1
        self.load_start = None
        self.load_baseline = None
        self.load_evaluated = False

    def _end_balance(self, *, complete: bool, count_incomplete: bool = True) -> None:
        if self.balance_start is not None:
            assert self.config is not None and self.config.balancing is not None
            cfg = self.config.balancing
            if (
                count_incomplete
                and _at_least(self.balance_initial, cfg.min_start_delta_v)
                and not self.balance_checked
            ):
                self.evaluations["BALANCING_INEFFECTIVE"]["incomplete_intervals"] += 1
            timeout = self.evaluations["BALANCING_ACTIVE_TOO_LONG"]
            if complete:
                timeout["evaluated_samples"] += 1
            elif count_incomplete and not self.balance_timeout_emitted:
                timeout["incomplete_intervals"] += 1
        self.balance_start = None
        self.balance_last = None
        self.balance_count = 0
        self.balance_checked = False
        self.balance_timeout_emitted = False

    def _break(self) -> None:
        for code in list(self.runs):
            self._flush(code)
        if self.config and self.config.cell_sag:
            self._end_load()
        if self.config and self.config.balancing:
            self._end_balance(complete=False)
        self.previous_t = self.span_start = None
        self.previous_temperatures = None
        self.baseline = None
        self.balance_previous = None
        self.balance_invalid_censor = False

    def _sustained(self, t: float, cells: np.ndarray, names: list[str]) -> None:
        assert self.config is not None
        cfg = self.config.sustained_imbalance
        if cfg is None:
            return
        assert self.span_start is not None
        evaluation = self.evaluations["CELL_IMBALANCE_SUSTAINED"]
        if _at_least(_finite(t - self.span_start), cfg.duration_s):
            evaluation["evaluated_samples"] += 1
        highest, lowest = float(np.max(cells)), float(np.min(cells))
        delta = _finite(highest - lowest)
        signals = [n for n, v in zip(names, cells) if v == highest]
        signals += [n for n, v in zip(names, cells) if v == lowest and n not in signals]
        self._threshold(
            "CELL_IMBALANCE_SUSTAINED",
            t,
            delta,
            cfg.max_delta_v,
            signals,
            {"cell_min_v": lowest, "cell_max_v": highest},
        )

    def _temperature(self, t: float, temperatures: np.ndarray, names: list[str]) -> None:
        assert self.config is not None
        cfg = self.config.temperature_rise
        if cfg is None or self.previous_t is None or self.previous_temperatures is None:
            return
        dt = _finite(t - self.previous_t)
        if not _at_least(dt, cfg.min_interval_s):
            self._flush("TEMPERATURE_RISE_HIGH")
            return
        with np.errstate(over="ignore", invalid="ignore"):
            rates = (temperatures - self.previous_temperatures) / dt * 60.0
        if not np.isfinite(rates).all():
            raise ValueError("Temperature rate-of-rise calculation overflowed")
        peak = int(np.argmax(rates))
        rate = float(rates[peak])
        self.evaluations["TEMPERATURE_RISE_HIGH"]["evaluated_samples"] += 1
        self._threshold(
            "TEMPERATURE_RISE_HIGH",
            t,
            rate,
            cfg.max_c_per_min,
            [n for n, v in zip(names, rates) if v == rate],
            {
                "previous_time_s": self.previous_t,
                "interval_s": dt,
                "previous_temperature_c": float(self.previous_temperatures[peak]),
                "temperature_c": float(temperatures[peak]),
            },
        )

    def _sag(self, t: float, cells: np.ndarray, names: list[str], current: float | None) -> None:
        assert self.config is not None
        cfg = self.config.cell_sag
        if cfg is None:
            return
        evaluation = self.evaluations["CELL_SAG_UNDER_LOAD"]
        if current is None or len(cells) < 3:
            evaluation["reason"] = "Requires pack current and at least three cell-voltage signals"
            return
        discharge = current if cfg.positive_direction == "discharge" else -current
        loaded = _at_least(discharge, cfg.load_min_discharge_a)
        if not loaded:
            self._end_load()
            if not _above(abs(current), cfg.baseline_max_abs_current_a):
                self.baseline = (t, current, cells.copy())
            return
        if self.load_start is None:
            self.load_start = t
            if (
                self.baseline is not None
                and t > self.baseline[0]
                and not _above(_finite(t - self.baseline[0]), cfg.baseline_max_age_s)
            ):
                self.load_baseline = self.baseline
            self.baseline = None
        if self.load_baseline is None or not _at_least(
            _finite(t - self.load_start), cfg.settling_s
        ):
            return
        baseline_t, baseline_i, baseline_cells = self.load_baseline
        with np.errstate(over="ignore", invalid="ignore"):
            sags = baseline_cells - cells
            # A cell change relative to its peers; not an internal resistance measurement.
            reference = float(np.median(sags))
            excess = sags - reference
        if not np.isfinite(sags).all() or not np.isfinite(excess).all():
            raise ValueError("Cell-sag calculation overflowed")
        peak = int(np.argmax(excess))
        value = float(excess[peak])
        self.load_evaluated = True
        evaluation["evaluated_samples"] += 1
        self._threshold(
            "CELL_SAG_UNDER_LOAD",
            t,
            value,
            cfg.excess_sag_max_v,
            [n for n, v in zip(names, excess) if v == value],
            {
                "baseline_time_s": baseline_t,
                "load_start_time_s": self.load_start,
                "baseline_current_a": baseline_i,
                "current_a": current,
                "baseline_cell_v": float(baseline_cells[peak]),
                "cell_v": float(cells[peak]),
                "cell_sag_v": float(sags[peak]),
                "median_sag_v": reference,
            },
        )

    def _balancing(
        self, t: float, delta: float, active: bool | None, cell_names: list[str]
    ) -> None:
        assert self.config is not None
        cfg = self.config.balancing
        if cfg is None:
            return
        if active is None:
            self._end_balance(complete=False, count_incomplete=False)
            self.balance_previous = None
            return
        if not active:
            self._end_balance(complete=True)
            self.balance_invalid_censor = False
        elif self.balance_previous is False:
            self.balance_start = self.balance_last = t
            self.balance_initial = delta
        elif self.balance_start is None:
            # Left-censored active sessions have no observed activation edge.
            for code in _BALANCING_CODES:
                evaluation = self.evaluations[code]
                if evaluation["reason"] is None:
                    evaluation["reason"] = "No observed inactive-to-active balancing edge"
                if self.balance_previous is None and not self.balance_invalid_censor:
                    evaluation["incomplete_intervals"] += 1
        if active and self.balance_start is not None:
            self.balance_count += 1
            self.balance_last = t
            elapsed = _finite(t - self.balance_start)
            improvement = _finite(self.balance_initial - delta)
            evidence = {
                "initial_delta_v": self.balance_initial,
                "final_delta_v": delta,
                "improvement_v": improvement,
                "active_duration_s": elapsed,
            }
            if not self.balance_checked and _at_least(elapsed, cfg.evaluation_s):
                self.balance_checked = True
                if _at_least(self.balance_initial, cfg.min_start_delta_v):
                    evaluation = self.evaluations["BALANCING_INEFFECTIVE"]
                    evaluation["evaluated_samples"] += 1
                    if not _at_least(improvement, cfg.min_improvement_v):
                        evaluation["events"].append(
                            _event(
                                "BALANCING_INEFFECTIVE",
                                self.balance_start,
                                t,
                                t,
                                improvement,
                                cfg.min_improvement_v,
                                self.balance_count,
                                "V",
                                [cfg.active_source, *cell_names],
                                evidence,
                            )
                        )
            if not self.balance_timeout_emitted and _above(elapsed, cfg.timeout_s):
                self.balance_timeout_emitted = True
                evaluation = self.evaluations["BALANCING_ACTIVE_TOO_LONG"]
                evaluation["evaluated_samples"] += 1
                evaluation["events"].append(
                    _event(
                        "BALANCING_ACTIVE_TOO_LONG",
                        self.balance_start,
                        t,
                        t,
                        elapsed,
                        cfg.timeout_s,
                        self.balance_count,
                        "s",
                        [cfg.active_source, *cell_names],
                        evidence,
                    )
                )
        self.balance_previous = active

    def consume(
        self,
        inputs: RuleInputs,
        valid_rows: pd.Series,
        balance_values: pd.Series | None,
        *,
        exclude_invalid: bool,
        row_offset: int = 0,
    ) -> None:
        if self.config is None:
            return
        present = balance_values is not None
        if self.balance_presence is None:
            self.balance_presence = present
        elif self.balance_presence != present:
            raise ValueError("Balancing signal presence changed between measurement chunks")
        if self.config.balancing and not present:
            for code in _BALANCING_CODES:
                self.evaluations[code]["reason"] = (
                    f"Missing balancing status source {self.config.balancing.active_source!r}"
                )
        cells = inputs.numeric[inputs.cell_cols].to_numpy(dtype=float)
        temperatures = inputs.numeric[inputs.temp_cols].to_numpy(dtype=float)
        times = inputs.timestamps.to_numpy(dtype=float)
        current = (
            inputs.numeric[inputs.pack_current_col].to_numpy(dtype=float)
            if inputs.pack_current_col is not None
            else None
        )
        raw_balance = balance_values.to_numpy(dtype=object) if balance_values is not None else None
        for row, valid in enumerate(valid_rows.to_numpy(dtype=bool)):
            if not valid:
                self._break()
                continue
            t = float(times[row])
            if self.previous_t is not None and _above(
                _finite(t - self.previous_t), self.config.max_gap_s
            ):
                self._break()
            if self.span_start is None:
                self.span_start = t
            active: bool | None = None
            if self.config.balancing is not None and raw_balance is not None:
                active = parse_balancing_status(raw_balance[row])
                if active is None and not exclude_invalid:
                    raise ValueError(
                        f"Balancing status must be 0/1 or boolean at data row {row_offset + row + 1}"
                    )
                elif active is None:
                    if not self.balance_invalid_censor:
                        for code in _BALANCING_CODES:
                            self.evaluations[code]["incomplete_intervals"] += 1
                    self.balance_invalid_censor = True
                    for code in _BALANCING_CODES:
                        self.evaluations[code]["reason"] = (
                            "Invalid balancing status samples were excluded"
                        )
            self._sustained(t, cells[row], inputs.cell_cols)
            self._temperature(t, temperatures[row], inputs.temp_cols)
            self._sag(
                t,
                cells[row],
                inputs.cell_cols,
                float(current[row]) if current is not None else None,
            )
            self._balancing(
                t,
                _finite(float(np.max(cells[row])) - float(np.min(cells[row]))),
                active,
                inputs.cell_cols,
            )
            self.previous_t = t
            self.previous_temperatures = temperatures[row].copy()

    def finish(self) -> FailureModelReport | None:
        if self.config is None:
            return None
        self._break()
        for evaluation in self.evaluations.values():
            if evaluation["events"]:
                evaluation["status"] = "FAIL"
                evaluation["reason"] = None
            elif evaluation["evaluated_samples"] and not evaluation["incomplete_intervals"]:
                evaluation["status"] = "PASS"
                evaluation["reason"] = None
            else:
                evaluation["status"] = "NOT_EVALUATED"
                evaluation["reason"] = (
                    evaluation["reason"] or "Insufficient eligible contiguous observations"
                )
        return {"config": asdict(self.config), "evaluations": list(self.evaluations.values())}
