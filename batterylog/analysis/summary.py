from dataclasses import dataclass

import numpy as np

from batterylog.models import PackVoltageCellSumPeak

from .preparation import PreparedMeasurements


@dataclass(frozen=True)
class MeasurementSummary:
    max_cell_voltage_v: float | None = None
    min_cell_voltage_v: float | None = None
    max_delta_v: float | None = None
    max_temperature_c: float | None = None
    min_temperature_c: float | None = None
    max_temperature_spread_c: float | None = None
    max_pack_current_a: float | None = None
    min_pack_current_a: float | None = None
    max_pack_voltage_v: float | None = None
    min_pack_voltage_v: float | None = None
    pack_voltage_cell_sum_peak: PackVoltageCellSumPeak | None = None


@dataclass(frozen=True)
class AnalysisMetrics:
    max_cell_voltage_v: float | None
    min_cell_voltage_v: float | None
    max_delta_v: float | None
    max_temperature_c: float | None
    min_temperature_c: float | None
    max_temperature_spread_c: float | None
    max_pack_current_a: float | None
    min_pack_current_a: float | None
    max_pack_voltage_v: float | None
    min_pack_voltage_v: float | None
    pack_voltage_cell_sum_peak: PackVoltageCellSumPeak | None


def summarize_prepared_measurements(
    prepared: PreparedMeasurements,
) -> MeasurementSummary:
    if prepared.valid_numeric.empty:
        return MeasurementSummary()

    valid_rows = prepared.valid_rows
    valid_numeric = prepared.valid_numeric
    inputs = prepared.rule_inputs

    pack_peak: PackVoltageCellSumPeak | None = None
    if inputs.pack_cell_delta is not None:
        assert inputs.pack_voltage_col is not None
        assert inputs.cell_sum is not None
        valid_delta = inputs.pack_cell_delta.loc[valid_rows]
        peak_position = int(np.argmax(valid_delta.to_numpy(dtype=float)))
        peak_row = valid_numeric.iloc[peak_position]
        pack = float(peak_row[inputs.pack_voltage_col])
        summed = float(inputs.cell_sum.loc[valid_rows].iloc[peak_position])
        pack_peak = {
            "timestamp_s": float(peak_row["timestamp_s"]),
            "pack_voltage_v": pack,
            "cell_voltage_sum_v": summed,
            "signed_error_v": pack - summed,
            "absolute_delta_v": float(valid_delta.iloc[peak_position]),
        }

    pack_current = (
        valid_numeric[inputs.pack_current_col] if inputs.pack_current_col is not None else None
    )
    pack_voltage = (
        valid_numeric[inputs.pack_voltage_col] if inputs.pack_voltage_col is not None else None
    )

    return MeasurementSummary(
        max_cell_voltage_v=float(inputs.cell_max.loc[valid_rows].max()),
        min_cell_voltage_v=float(inputs.cell_min.loc[valid_rows].min()),
        max_delta_v=float(inputs.delta_v.loc[valid_rows].max()),
        max_temperature_c=float(inputs.temperature_max.loc[valid_rows].max()),
        min_temperature_c=float(inputs.temperature_min.loc[valid_rows].min()),
        max_temperature_spread_c=float(inputs.temperature_spread.loc[valid_rows].max()),
        max_pack_current_a=float(pack_current.max()) if pack_current is not None else None,
        min_pack_current_a=float(pack_current.min()) if pack_current is not None else None,
        max_pack_voltage_v=float(pack_voltage.max()) if pack_voltage is not None else None,
        min_pack_voltage_v=float(pack_voltage.min()) if pack_voltage is not None else None,
        pack_voltage_cell_sum_peak=pack_peak,
    )


def _max_optional(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _min_optional(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _merge_pack_peak(
    previous: PackVoltageCellSumPeak | None,
    current: PackVoltageCellSumPeak | None,
) -> PackVoltageCellSumPeak | None:
    if previous is None:
        return current
    if current is None:
        return previous
    if current["absolute_delta_v"] > previous["absolute_delta_v"]:
        return current
    return previous


def merge_measurement_summaries(
    previous: MeasurementSummary,
    current: MeasurementSummary,
) -> MeasurementSummary:
    return MeasurementSummary(
        max_cell_voltage_v=_max_optional(
            previous.max_cell_voltage_v,
            current.max_cell_voltage_v,
        ),
        min_cell_voltage_v=_min_optional(
            previous.min_cell_voltage_v,
            current.min_cell_voltage_v,
        ),
        max_delta_v=_max_optional(previous.max_delta_v, current.max_delta_v),
        max_temperature_c=_max_optional(
            previous.max_temperature_c,
            current.max_temperature_c,
        ),
        min_temperature_c=_min_optional(
            previous.min_temperature_c,
            current.min_temperature_c,
        ),
        max_temperature_spread_c=_max_optional(
            previous.max_temperature_spread_c,
            current.max_temperature_spread_c,
        ),
        max_pack_current_a=_max_optional(
            previous.max_pack_current_a,
            current.max_pack_current_a,
        ),
        min_pack_current_a=_min_optional(
            previous.min_pack_current_a,
            current.min_pack_current_a,
        ),
        max_pack_voltage_v=_max_optional(
            previous.max_pack_voltage_v,
            current.max_pack_voltage_v,
        ),
        min_pack_voltage_v=_min_optional(
            previous.min_pack_voltage_v,
            current.min_pack_voltage_v,
        ),
        pack_voltage_cell_sum_peak=_merge_pack_peak(
            previous.pack_voltage_cell_sum_peak,
            current.pack_voltage_cell_sum_peak,
        ),
    )


def analysis_metrics_from_summary(summary: MeasurementSummary) -> AnalysisMetrics:
    return AnalysisMetrics(
        max_cell_voltage_v=summary.max_cell_voltage_v,
        min_cell_voltage_v=summary.min_cell_voltage_v,
        max_delta_v=(round(summary.max_delta_v, 12) if summary.max_delta_v is not None else None),
        max_temperature_c=summary.max_temperature_c,
        min_temperature_c=summary.min_temperature_c,
        max_temperature_spread_c=(
            round(summary.max_temperature_spread_c, 12)
            if summary.max_temperature_spread_c is not None
            else None
        ),
        max_pack_current_a=summary.max_pack_current_a,
        min_pack_current_a=summary.min_pack_current_a,
        max_pack_voltage_v=summary.max_pack_voltage_v,
        min_pack_voltage_v=summary.min_pack_voltage_v,
        pack_voltage_cell_sum_peak=summary.pack_voltage_cell_sum_peak,
    )
