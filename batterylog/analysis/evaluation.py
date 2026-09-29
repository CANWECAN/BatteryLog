from dataclasses import dataclass

import pandas as pd

from batterylog.config import ValidationLimits
from batterylog.models import CurrentDirection, RuleCode, ViolationEvent

from .comparison import below_limit, exceeds_limit
from .rules import (
    build_high_events,
    build_imbalance_events,
    build_low_events,
    build_pack_voltage_cell_sum_events,
    build_temperature_spread_events,
)


@dataclass(frozen=True)
class RuleInputs:
    numeric: pd.DataFrame
    timestamps: pd.Series
    cell_cols: list[str]
    temp_cols: list[str]
    pack_current_col: str | None
    pack_voltage_col: str | None
    cell_max: pd.Series
    cell_min: pd.Series
    delta_v: pd.Series
    temperature_max: pd.Series
    temperature_min: pd.Series
    temperature_spread: pd.Series
    cell_sum: pd.Series | None
    pack_cell_delta: pd.Series | None


@dataclass(frozen=True)
class RuleEvaluation:
    code: RuleCode
    mask: pd.Series
    events: list[ViolationEvent]
    peak_values: pd.Series | None = None


_PACK_CURRENT_RULES: tuple[tuple[CurrentDirection, RuleCode], ...] = (
    ("charge", "PACK_CHARGE_OVERCURRENT"),
    ("discharge", "PACK_DISCHARGE_OVERCURRENT"),
)


def pack_current_rule_parameters(
    limits: ValidationLimits,
    direction: CurrentDirection,
) -> tuple[float, bool] | None:
    magnitude = limits.pack_charge_max_a if direction == "charge" else limits.pack_discharge_max_a
    if magnitude is None:
        return None
    assert limits.pack_current_positive_direction is not None
    prefer_lower = limits.pack_current_positive_direction != direction
    signed_limit = -magnitude if prefer_lower else magnitude
    return signed_limit, prefer_lower


def rule_prefers_lower(code: RuleCode, limits: ValidationLimits) -> bool:
    if code in {"CELL_UNDERVOLTAGE", "TEMPERATURE_LOW"}:
        return True
    for direction, current_code in _PACK_CURRENT_RULES:
        if code == current_code:
            parameters = pack_current_rule_parameters(limits, direction)
            assert parameters is not None
            return parameters[1]
    return False


def active_rule_codes(limits: ValidationLimits) -> list[RuleCode]:
    codes: list[RuleCode] = []
    if limits.imbalance_max_v is not None:
        codes.append("CELL_IMBALANCE_HIGH")
    if limits.cell_max_v is not None:
        codes.append("CELL_OVERVOLTAGE")
    if limits.cell_min_v is not None:
        codes.append("CELL_UNDERVOLTAGE")
    if limits.temperature_max_c is not None:
        codes.append("TEMPERATURE_HIGH")
    if limits.temperature_min_c is not None:
        codes.append("TEMPERATURE_LOW")
    if limits.temperature_spread_max_c is not None:
        codes.append("TEMPERATURE_SPREAD_HIGH")
    if limits.pack_charge_max_a is not None:
        codes.append("PACK_CHARGE_OVERCURRENT")
    if limits.pack_discharge_max_a is not None:
        codes.append("PACK_DISCHARGE_OVERCURRENT")
    if limits.pack_voltage_cell_sum_max_delta_v is not None:
        codes.append("PACK_VOLTAGE_CELL_SUM_MISMATCH")
    return codes


def _high_evaluation(
    *,
    code: RuleCode,
    inputs: RuleInputs,
    row_max: pd.Series,
    signal_cols: list[str],
    limit: float,
    unit: str,
    max_gap_s: float | None,
) -> RuleEvaluation:
    return RuleEvaluation(
        code=code,
        mask=exceeds_limit(row_max, limit),
        events=build_high_events(
            numeric=inputs.numeric,
            timestamps=inputs.timestamps,
            signal_cols=signal_cols,
            row_max=row_max,
            limit=limit,
            code=code,
            unit=unit,
            max_gap_s=max_gap_s,
        ),
    )


def _low_evaluation(
    *,
    code: RuleCode,
    inputs: RuleInputs,
    row_min: pd.Series,
    signal_cols: list[str],
    limit: float,
    unit: str,
    max_gap_s: float | None,
) -> RuleEvaluation:
    return RuleEvaluation(
        code=code,
        mask=below_limit(row_min, limit),
        events=build_low_events(
            numeric=inputs.numeric,
            timestamps=inputs.timestamps,
            signal_cols=signal_cols,
            row_min=row_min,
            limit=limit,
            code=code,
            unit=unit,
            max_gap_s=max_gap_s,
        ),
    )


def evaluate_rule(
    code: RuleCode,
    inputs: RuleInputs,
    limits: ValidationLimits,
    *,
    max_gap_s: float | None,
) -> RuleEvaluation:
    if code == "CELL_IMBALANCE_HIGH":
        assert limits.imbalance_max_v is not None
        return RuleEvaluation(
            code=code,
            mask=exceeds_limit(inputs.delta_v, limits.imbalance_max_v),
            events=build_imbalance_events(
                inputs.numeric,
                inputs.timestamps,
                inputs.cell_cols,
                inputs.delta_v,
                limits.imbalance_max_v,
                max_gap_s=max_gap_s,
            ),
            peak_values=inputs.delta_v,
        )
    if code == "CELL_OVERVOLTAGE":
        assert limits.cell_max_v is not None
        return _high_evaluation(
            code=code,
            inputs=inputs,
            row_max=inputs.cell_max,
            signal_cols=inputs.cell_cols,
            limit=limits.cell_max_v,
            unit="V",
            max_gap_s=max_gap_s,
        )
    if code == "CELL_UNDERVOLTAGE":
        assert limits.cell_min_v is not None
        return _low_evaluation(
            code=code,
            inputs=inputs,
            row_min=inputs.cell_min,
            signal_cols=inputs.cell_cols,
            limit=limits.cell_min_v,
            unit="V",
            max_gap_s=max_gap_s,
        )
    if code == "TEMPERATURE_HIGH":
        assert limits.temperature_max_c is not None
        return _high_evaluation(
            code=code,
            inputs=inputs,
            row_max=inputs.temperature_max,
            signal_cols=inputs.temp_cols,
            limit=limits.temperature_max_c,
            unit="degC",
            max_gap_s=max_gap_s,
        )
    if code == "TEMPERATURE_LOW":
        assert limits.temperature_min_c is not None
        return _low_evaluation(
            code=code,
            inputs=inputs,
            row_min=inputs.temperature_min,
            signal_cols=inputs.temp_cols,
            limit=limits.temperature_min_c,
            unit="degC",
            max_gap_s=max_gap_s,
        )
    if code == "TEMPERATURE_SPREAD_HIGH":
        assert limits.temperature_spread_max_c is not None
        return RuleEvaluation(
            code=code,
            mask=exceeds_limit(inputs.temperature_spread, limits.temperature_spread_max_c),
            events=build_temperature_spread_events(
                inputs.numeric,
                inputs.timestamps,
                inputs.temp_cols,
                inputs.temperature_spread,
                limits.temperature_spread_max_c,
                max_gap_s=max_gap_s,
            ),
            peak_values=inputs.temperature_spread,
        )
    if code in {"PACK_CHARGE_OVERCURRENT", "PACK_DISCHARGE_OVERCURRENT"}:
        assert inputs.pack_current_col is not None
        direction: CurrentDirection = "charge" if code == "PACK_CHARGE_OVERCURRENT" else "discharge"
        parameters = pack_current_rule_parameters(limits, direction)
        assert parameters is not None
        signed_limit, prefer_lower = parameters
        pack_current = inputs.numeric[inputs.pack_current_col]
        if prefer_lower:
            return _low_evaluation(
                code=code,
                inputs=inputs,
                row_min=pack_current,
                signal_cols=[inputs.pack_current_col],
                limit=signed_limit,
                unit="A",
                max_gap_s=max_gap_s,
            )
        return _high_evaluation(
            code=code,
            inputs=inputs,
            row_max=pack_current,
            signal_cols=[inputs.pack_current_col],
            limit=signed_limit,
            unit="A",
            max_gap_s=max_gap_s,
        )
    assert code == "PACK_VOLTAGE_CELL_SUM_MISMATCH"
    assert limits.pack_voltage_cell_sum_max_delta_v is not None
    assert inputs.pack_voltage_col is not None
    assert inputs.cell_sum is not None
    assert inputs.pack_cell_delta is not None
    return RuleEvaluation(
        code=code,
        mask=exceeds_limit(
            inputs.pack_cell_delta,
            limits.pack_voltage_cell_sum_max_delta_v,
        ),
        events=build_pack_voltage_cell_sum_events(
            inputs.timestamps,
            inputs.numeric[inputs.pack_voltage_col],
            inputs.cell_sum,
            inputs.pack_cell_delta,
            inputs.cell_cols,
            limits.pack_voltage_cell_sum_max_delta_v,
            max_gap_s=max_gap_s,
        ),
    )


def evaluate_rules(
    inputs: RuleInputs,
    limits: ValidationLimits,
    *,
    max_gap_s: float | None,
) -> list[RuleEvaluation]:
    return [
        evaluate_rule(code, inputs, limits, max_gap_s=max_gap_s)
        for code in active_rule_codes(limits)
    ]
