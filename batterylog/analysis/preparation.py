from dataclasses import dataclass

import numpy as np
import pandas as pd

from .evaluation import RuleInputs


@dataclass(frozen=True)
class PreparedMeasurements:
    valid_rows: pd.Series
    valid_numeric: pd.DataFrame
    rule_inputs: RuleInputs


def _ensure_finite_derived_metric(
    values: pd.Series,
    valid_rows: pd.Series,
    *,
    metric_name: str,
    row_offset: int = 0,
) -> None:
    valid_mask = valid_rows.to_numpy(dtype=bool)
    selected = values.to_numpy(dtype=float)[valid_mask]
    non_finite = ~np.isfinite(selected)
    if not non_finite.any():
        return

    valid_position = int(np.flatnonzero(non_finite)[0])
    row_pos = int(np.flatnonzero(valid_mask)[valid_position])
    row_index = values.index[row_pos]
    raise ValueError(
        f"{metric_name} calculation overflowed at "
        f"data row {row_offset + row_pos + 1} (index {row_index!r})"
    )


def _pack_cell_sum_and_delta(
    numeric: pd.DataFrame,
    cell_cols: list[str],
    pack_voltage_col: str | None,
    valid_rows: pd.Series,
) -> tuple[pd.Series | None, pd.Series | None]:
    if pack_voltage_col is None:
        return None, None

    cell_values = np.ascontiguousarray(
        numeric[cell_cols].to_numpy(dtype=float, copy=False),
        dtype=float,
    )
    cell_sum = pd.Series(
        np.sum(cell_values, axis=1, dtype=np.float64),
        index=numeric.index,
    )
    delta = (numeric[pack_voltage_col] - cell_sum).abs()
    if (
        not np.isfinite(cell_sum.loc[valid_rows].to_numpy(dtype=float)).all()
        or not np.isfinite(delta.loc[valid_rows].to_numpy(dtype=float)).all()
    ):
        raise ValueError("Pack-voltage cell-sum calculation overflowed on an analyzed row")
    return cell_sum, delta


def prepare_measurements(
    numeric: pd.DataFrame,
    invalid_rows: pd.Series,
    *,
    pack_cols: list[str],
    cell_cols: list[str],
    temp_cols: list[str],
    pack_current_col: str | None,
    pack_voltage_col: str | None,
    row_offset: int = 0,
) -> PreparedMeasurements:
    valid_rows = ~invalid_rows
    valid_numeric = numeric.loc[valid_rows]

    rule_numeric = pd.DataFrame(
        numeric.to_numpy(dtype=float, na_value=np.nan),
        index=numeric.index,
        columns=numeric.columns,
    )
    if invalid_rows.any():
        rule_numeric.loc[
            invalid_rows,
            [*pack_cols, *cell_cols, *temp_cols],
        ] = float("nan")

    timestamps = rule_numeric["timestamp_s"]
    cell_max = rule_numeric[cell_cols].max(axis=1)
    cell_min = rule_numeric[cell_cols].min(axis=1)
    temperature_max = rule_numeric[temp_cols].max(axis=1)
    temperature_min = rule_numeric[temp_cols].min(axis=1)
    with np.errstate(over="ignore", invalid="ignore"):
        delta_v = cell_max - cell_min
        temperature_spread = temperature_max - temperature_min

    _ensure_finite_derived_metric(
        delta_v,
        valid_rows,
        metric_name="Cell-voltage delta",
        row_offset=row_offset,
    )
    _ensure_finite_derived_metric(
        temperature_spread,
        valid_rows,
        metric_name="Temperature spread",
        row_offset=row_offset,
    )
    cell_sum, pack_cell_delta = _pack_cell_sum_and_delta(
        rule_numeric,
        cell_cols,
        pack_voltage_col,
        valid_rows,
    )

    return PreparedMeasurements(
        valid_rows=valid_rows,
        valid_numeric=valid_numeric,
        rule_inputs=RuleInputs(
            numeric=rule_numeric,
            timestamps=timestamps,
            cell_cols=cell_cols,
            temp_cols=temp_cols,
            pack_current_col=pack_current_col,
            pack_voltage_col=pack_voltage_col,
            cell_max=cell_max,
            cell_min=cell_min,
            delta_v=delta_v,
            temperature_max=temperature_max,
            temperature_min=temperature_min,
            temperature_spread=temperature_spread,
            cell_sum=cell_sum,
            pack_cell_delta=pack_cell_delta,
        ),
    )
