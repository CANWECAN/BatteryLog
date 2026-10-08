"""Cross-field evidence checks after strict JSON and result-v9 schema validation."""

from math import isclose, isfinite

from .analysis.comparison import BINARY64_REL_TOL
from .analysis.failure_models import _above, _at_least
from .failure_config import parse_failure_models
from .failure_models import FailureCode, FailureEvent, FailureModelReport


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Failure-model evidence: {message}")


def _same(a: float, b: float) -> bool:
    return isfinite(a) and isfinite(b) and isclose(a, b, rel_tol=BINARY64_REL_TOL, abs_tol=0)


def validate_failure_report(report: FailureModelReport) -> None:
    config = parse_failure_models(report["config"])
    assert config is not None
    expected: list[FailureCode] = []
    if config.sustained_imbalance:
        expected.append("CELL_IMBALANCE_SUSTAINED")
    if config.temperature_rise:
        expected.append("TEMPERATURE_RISE_HIGH")
    if config.cell_sag:
        expected.append("CELL_SAG_UNDER_LOAD")
    if config.balancing:
        expected.extend(["BALANCING_INEFFECTIVE", "BALANCING_ACTIVE_TOO_LONG"])
    if config.unloaded_current:
        expected.append("CURRENT_WHILE_UNLOADED")
    if config.contactor_response:
        expected.append("CONTACTOR_FEEDBACK_TIMEOUT")
    _require(
        [item["code"] for item in report["evaluations"]] == expected,
        "enabled model codes/order differ",
    )
    for evaluation in report["evaluations"]:
        code = evaluation["code"]
        expected_status = (
            "FAIL"
            if evaluation["events"]
            else "NOT_EVALUATED"
            if evaluation["incomplete_intervals"] or not evaluation["evaluated_samples"]
            else "PASS"
        )
        _require(
            evaluation["status"] == expected_status, "status disagrees with observations/events"
        )
        _require(
            len(evaluation["events"]) <= evaluation["evaluated_samples"],
            "events exceed eligible observations",
        )
        for event in evaluation["events"]:
            _require(event["code"] == code, "event code differs from its evaluation")
            _validate_event(event, config.max_gap_s)
            evidence = event["evidence"]
            measured, limit = event["measured_value"], event["limit_value"]
            if code == "CELL_IMBALANCE_SUSTAINED":
                cfg = config.sustained_imbalance
                assert cfg is not None
                _require(_same(limit, cfg.max_delta_v), "imbalance limit differs from config")
                _require(_above(measured, limit), "imbalance does not exceed its limit")
                _require(
                    _at_least(event["duration_s"], cfg.duration_s),
                    "imbalance duration is too short",
                )
                _require(
                    _same(evidence["required_duration_s"], cfg.duration_s), "duration limit differs"
                )
                _require(
                    _same(measured, evidence["cell_max_v"] - evidence["cell_min_v"]),
                    "cell spread differs",
                )
            elif code == "TEMPERATURE_RISE_HIGH":
                rise = config.temperature_rise
                assert rise is not None
                dt = evidence["interval_s"]
                _require(_same(limit, rise.max_c_per_min), "temperature-rise limit differs")
                _require(_above(measured, limit), "temperature rate does not exceed limit")
                _require(
                    _at_least(dt, rise.min_interval_s) and not _above(dt, config.max_gap_s),
                    "temperature interval is ineligible",
                )
                _require(
                    _same(event["peak_time_s"] - evidence["previous_time_s"], dt),
                    "temperature times differ",
                )
                rate = (evidence["temperature_c"] - evidence["previous_temperature_c"]) / dt * 60
                _require(_same(measured, rate), "temperature rate differs from its samples")
            elif code == "CELL_SAG_UNDER_LOAD":
                sag = config.cell_sag
                assert sag is not None
                _require(_same(limit, sag.excess_sag_max_v), "cell-sag limit differs")
                _require(_above(measured, limit), "excess cell sag does not exceed limit")
                _require(
                    _same(evidence["baseline_cell_v"] - evidence["cell_v"], evidence["cell_sag_v"]),
                    "cell voltage drop differs",
                )
                _require(
                    _same(evidence["cell_sag_v"] - evidence["median_sag_v"], measured),
                    "relative cell sag differs",
                )
                age = evidence["load_start_time_s"] - evidence["baseline_time_s"]
                _require(
                    age > 0 and not _above(age, sag.baseline_max_age_s),
                    "cell-sag baseline is ineligible",
                )
                _require(
                    not _above(abs(evidence["baseline_current_a"]), sag.baseline_max_abs_current_a),
                    "baseline current is too high",
                )
                discharge = evidence["current_a"] * (
                    1 if sag.positive_direction == "discharge" else -1
                )
                _require(_at_least(discharge, sag.load_min_discharge_a), "load current is too low")
                _require(
                    _at_least(event["peak_time_s"] - evidence["load_start_time_s"], sag.settling_s),
                    "load has not settled",
                )
            elif code == "CURRENT_WHILE_UNLOADED":
                unloaded = config.unloaded_current
                assert unloaded is not None
                _require(_same(limit, unloaded.max_abs_current_a), "unloaded-current limit differs")
                _require(_above(measured, limit), "unloaded current does not exceed limit")
                _require(_same(measured, abs(evidence["current_a"])), "current magnitude differs")
                _require(evidence["unloaded_status"] == 1, "state is not unloaded")
                _require(
                    "pack_current_a" in event["signals"]
                    and unloaded.unloaded_source in event["signals"],
                    "unloaded-current sources are missing",
                )
                _require(
                    _at_least(event["duration_s"], unloaded.duration_s),
                    "unloaded-current duration is too short",
                )
                _require(
                    _same(evidence["required_duration_s"], unloaded.duration_s),
                    "duration limit differs",
                )
            elif code == "CONTACTOR_FEEDBACK_TIMEOUT":
                contactor = config.contactor_response
                assert contactor is not None
                _require(
                    _same(limit, contactor.response_timeout_s), "contactor response limit differs"
                )
                _require(
                    _same(evidence["required_response_s"], limit), "contactor deadline differs"
                )
                _require(
                    _same(measured, event["duration_s"]) and _above(measured, limit),
                    "contactor response deadline has not been exceeded",
                )
                _require(
                    _same(evidence["command_time_s"], event["start_time_s"]),
                    "contactor command time differs",
                )
                _require(
                    event["peak_time_s"] == event["end_time_s"],
                    "contactor timeout observation differs",
                )
                _require(
                    evidence["previous_command_closed"] != evidence["command_closed"],
                    "no command transition",
                )
                _require(
                    evidence["feedback_closed"] != evidence["command_closed"],
                    "feedback matches command",
                )
                age = evidence["command_time_s"] - evidence["previous_command_time_s"]
                _require(
                    age >= 0 and not _above(age, config.max_gap_s),
                    "command transition crosses an ineligible gap",
                )
                _require(
                    event["signals"] == [contactor.command_source, contactor.feedback_source],
                    "contactor sources differ",
                )
            else:
                balance = config.balancing
                assert balance is not None
                _require(balance.active_source in event["signals"], "balancing source is missing")
                improvement = evidence["initial_delta_v"] - evidence["final_delta_v"]
                _require(
                    _same(improvement, evidence["improvement_v"]), "balancing improvement differs"
                )
                _require(
                    _same(event["duration_s"], evidence["active_duration_s"]),
                    "balancing duration differs",
                )
                if code == "BALANCING_INEFFECTIVE":
                    _require(
                        _same(limit, balance.min_improvement_v) and _same(measured, improvement),
                        "balancing limit/value differs",
                    )
                    _require(
                        not _at_least(improvement, limit), "balancing improvement meets the target"
                    )
                    _require(
                        _at_least(event["duration_s"], balance.evaluation_s),
                        "balancing observation is too short",
                    )
                    _require(
                        _at_least(evidence["initial_delta_v"], balance.min_start_delta_v),
                        "initial spread is ineligible",
                    )
                else:
                    _require(
                        _same(limit, balance.timeout_s) and _same(measured, event["duration_s"]),
                        "balancing timeout value differs",
                    )
                    _require(_above(measured, limit), "balancing timeout has not been exceeded")


def _validate_event(event: FailureEvent, max_gap_s: float) -> None:
    start, end, peak = event["start_time_s"], event["end_time_s"], event["peak_time_s"]
    _require(start <= peak <= end, "event times are out of order")
    _require(_same(event["duration_s"], end - start), "event duration differs from timestamps")
    count = event["sample_count"]
    if count == 1:
        _require(start == end, "a single observation cannot span positive duration")
    else:
        _require(
            not _above(event["duration_s"] / (count - 1), max_gap_s),
            "event duration cannot be supported by its observation count and maximum gap",
        )
    _require(
        _same(event["peak_excursion"], abs(event["measured_value"] - event["limit_value"])),
        "peak excursion differs",
    )
    _require(
        all(isfinite(value) for value in event["evidence"].values()), "non-finite measurement chain"
    )
