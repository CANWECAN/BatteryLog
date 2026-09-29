import pandas as pd

from batterylog import ValidationLimits
from batterylog.analysis.evaluation import RuleInputs, active_rule_codes, evaluate_rules


def _all_rule_limits() -> ValidationLimits:
    return ValidationLimits(
        cell_min_v=3.0,
        cell_max_v=4.2,
        imbalance_max_v=0.2,
        temperature_min_c=-20.0,
        temperature_max_c=55.0,
        pack_charge_max_a=10.0,
        pack_discharge_max_a=10.0,
        pack_current_positive_direction="charge",
        temperature_spread_max_c=10.0,
        pack_voltage_cell_sum_max_delta_v=0.1,
    )


def _rule_inputs() -> RuleInputs:
    numeric = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0],
            "pack_current_a": [12.0, -20.0],
            "pack_voltage_v": [8.0, 6.0],
            "cell_1_v": [4.3, 2.8],
            "cell_2_v": [4.0, 3.5],
            "temp_1_c": [60.0, -30.0],
            "temp_2_c": [20.0, 0.0],
        }
    )
    cell_cols = ["cell_1_v", "cell_2_v"]
    temp_cols = ["temp_1_c", "temp_2_c"]
    cell_max = numeric[cell_cols].max(axis=1)
    cell_min = numeric[cell_cols].min(axis=1)
    temperature_max = numeric[temp_cols].max(axis=1)
    temperature_min = numeric[temp_cols].min(axis=1)
    cell_sum = numeric[cell_cols].sum(axis=1)
    return RuleInputs(
        numeric=numeric,
        timestamps=numeric["timestamp_s"],
        cell_cols=cell_cols,
        temp_cols=temp_cols,
        pack_current_col="pack_current_a",
        pack_voltage_col="pack_voltage_v",
        cell_max=cell_max,
        cell_min=cell_min,
        delta_v=cell_max - cell_min,
        temperature_max=temperature_max,
        temperature_min=temperature_min,
        temperature_spread=temperature_max - temperature_min,
        cell_sum=cell_sum,
        pack_cell_delta=(numeric["pack_voltage_v"] - cell_sum).abs(),
    )


def test_active_rule_codes_have_stable_contract_order() -> None:
    assert active_rule_codes(_all_rule_limits()) == [
        "CELL_IMBALANCE_HIGH",
        "CELL_OVERVOLTAGE",
        "CELL_UNDERVOLTAGE",
        "TEMPERATURE_HIGH",
        "TEMPERATURE_LOW",
        "TEMPERATURE_SPREAD_HIGH",
        "PACK_CHARGE_OVERCURRENT",
        "PACK_DISCHARGE_OVERCURRENT",
        "PACK_VOLTAGE_CELL_SUM_MISMATCH",
    ]


def test_shared_rule_kernel_evaluates_every_active_rule() -> None:
    inputs = _rule_inputs()
    evaluations = evaluate_rules(inputs, _all_rule_limits(), max_gap_s=None)

    assert [evaluation.code for evaluation in evaluations] == active_rule_codes(_all_rule_limits())
    assert all(evaluation.mask.any() for evaluation in evaluations)
    assert all(evaluation.events for evaluation in evaluations)

    by_code = {evaluation.code: evaluation for evaluation in evaluations}
    assert by_code["PACK_CHARGE_OVERCURRENT"].events[0]["measured_value"] == 12.0
    assert by_code["PACK_DISCHARGE_OVERCURRENT"].events[0]["measured_value"] == -20.0


def test_only_rounded_derived_rules_expose_raw_streaming_peak_values() -> None:
    inputs = _rule_inputs()
    evaluations = evaluate_rules(inputs, _all_rule_limits(), max_gap_s=None)
    peak_codes = {
        evaluation.code for evaluation in evaluations if evaluation.peak_values is not None
    }

    assert peak_codes == {"CELL_IMBALANCE_HIGH", "TEMPERATURE_SPREAD_HIGH"}
