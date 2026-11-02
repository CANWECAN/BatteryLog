"""One sampled current-decay checkpoint per observed precharge activation."""

from dataclasses import dataclass

from batterylog.failure_config import PrechargeCurrentConfig
from batterylog.failure_models import FailureEvaluation

from .failure_evidence import _at_least, _event, _finite


@dataclass
class _Window:
    start: float
    previous_time: float
    initial_current: float
    count: int = 0
    checked: bool = False


class PrechargeCurrentCollector:
    def __init__(self, config: PrechargeCurrentConfig, evaluation: FailureEvaluation) -> None:
        self.config = config
        self.evaluation = evaluation
        self.previous: tuple[float, bool] | None = None
        self.window: _Window | None = None
        self.invalid_censor = False

    def break_continuity(self, *, count_incomplete: bool = True) -> None:
        if count_incomplete and self.window is not None and not self.window.checked:
            self.evaluation["incomplete_intervals"] += 1
        self.window = None
        self.previous = None

    def censor(self, reason: str) -> None:
        if not self.invalid_censor:
            self.evaluation["incomplete_intervals"] += 1
        self.invalid_censor = True
        self.evaluation["reason"] = reason
        self.break_continuity(count_incomplete=False)

    def consume(self, t: float, current: float, active: bool) -> None:
        previous = self.previous
        if not active:
            self.break_continuity()
        elif previous is None:
            if not self.invalid_censor:
                self.evaluation["incomplete_intervals"] += 1
                self.evaluation["reason"] = "No observed inactive-to-active precharge edge"
        elif not previous[1]:
            if _at_least(abs(current), self.config.min_start_abs_current_a):
                self.window = _Window(t, previous[0], current)
            else:
                self.evaluation["incomplete_intervals"] += 1
                self.evaluation["reason"] = "Initial precharge current below the observation bound"
        self.invalid_censor = False
        self.previous = (t, active)
        window = self.window
        if window is None or window.checked:
            return
        window.count += 1
        elapsed = _finite(t - window.start)
        if not _at_least(elapsed, self.config.evaluation_s):
            return
        window.checked = True
        self.evaluation["evaluated_samples"] += 1
        drop = _finite(abs(window.initial_current) - abs(current))
        if not _at_least(drop, self.config.min_drop_a):
            self.evaluation["events"].append(
                _event(
                    "PRECHARGE_CURRENT_DECAY_LOW",
                    window.start,
                    t,
                    t,
                    drop,
                    self.config.min_drop_a,
                    window.count,
                    "A",
                    ["pack_current_a", self.config.active_source],
                    {
                        "previous_time_s": window.previous_time,
                        "previous_precharge_active": 0.0,
                        "precharge_active": 1.0,
                        "initial_current_a": window.initial_current,
                        "current_a": current,
                        "current_drop_a": drop,
                        "required_evaluation_s": self.config.evaluation_s,
                    },
                )
            )
