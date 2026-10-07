from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from pandas.api.types import is_object_dtype

from batterylog.config import SignalMapping, ValidationLimits
from batterylog.failure_config import FailureModelConfig
from batterylog.loaders import MeasurementLoader
from batterylog.loaders.mf4 import MdfFileLoader, MdfPathLoader
from batterylog.signals import (
    canonicalize_battery_signals,
    find_canonical_pack_signal_columns,
    find_canonical_signal_columns,
    resolve_signal_mapping,
)

from .data_quality import _required_boolean_mask


def parse_balancing_status(value: object) -> bool | None:
    if isinstance(value, str):
        value = {"0": 0, "1": 1, "true": True, "false": False}.get(value.strip().lower())
    if isinstance(value, (bool, int, float, np.bool_, np.integer, np.floating)) and value in (0, 1):
        return bool(value)
    return None


def failure_model_loader(
    loader: MeasurementLoader,
    config: FailureModelConfig | None,
) -> MeasurementLoader:
    if config is not None and not isinstance(config, FailureModelConfig):
        raise TypeError("failure_models must be a FailureModelConfig instance or null")
    if config and config.balancing and isinstance(loader, (MdfFileLoader, MdfPathLoader)):
        return replace(loader, balance_active_source=config.balancing.active_source)
    return loader


def balance_values_for_frame(
    frame: pd.DataFrame,
    mapping: SignalMapping | None,
    config: FailureModelConfig | None,
) -> pd.Series | None:
    if config is None or config.balancing is None:
        return None
    source = config.balancing.active_source
    count = sum(name == source for name in frame.columns)
    if count == 0:
        return None
    if count > 1:
        raise ValueError(f"Duplicate balancing source {source!r}")
    if mapping is not None:
        resolved = resolve_signal_mapping(frame.columns, mapping)
        required = [*resolved.source_columns, *resolved.canonical_columns]
    else:
        cells, temperatures = find_canonical_signal_columns(frame.columns)
        required = ["timestamp_s", "pack_current_a", "pack_voltage_v", *cells, *temperatures]
    if source in required:
        raise ValueError(f"Balancing source {source!r} is also assigned to a measurement role")
    return frame[source]


@dataclass(frozen=True)
class SignalLayout:
    cell_cols: list[str]
    temp_cols: list[str]
    pack_current_col: str | None
    pack_voltage_col: str | None

    @property
    def pack_cols(self) -> list[str]:
        return [
            column
            for column in (self.pack_current_col, self.pack_voltage_col)
            if column is not None
        ]

    @property
    def numeric_cols(self) -> list[str]:
        return ["timestamp_s", *self.pack_cols, *self.cell_cols, *self.temp_cols]


def canonicalize_analysis_frame(
    frame: pd.DataFrame,
    signal_mapping: SignalMapping | None,
    limits: ValidationLimits,
) -> tuple[pd.DataFrame, SignalLayout]:
    canonical = canonicalize_battery_signals(frame, signal_mapping)
    for column in ("timestamp_s", "temp_c"):
        if sum(isinstance(name, str) and name == column for name in canonical.columns) > 1:
            raise ValueError(f"Duplicate canonical signal name {column!r}")
    if "timestamp_s" not in canonical.columns:
        raise ValueError("Required column 'timestamp_s' is missing")

    cell_cols, temp_cols = find_canonical_signal_columns(canonical.columns)
    if not cell_cols:
        raise ValueError("No cell voltage columns found")
    if not temp_cols:
        raise ValueError("No temperature columns found")

    pack_current_col, pack_voltage_col = find_canonical_pack_signal_columns(canonical.columns)
    if limits.pack_voltage_cell_sum_max_delta_v is not None and pack_voltage_col is None:
        raise ValueError("Pack-voltage cell-sum validation requires column 'pack_voltage_v'")
    if (
        limits.pack_charge_max_a is not None or limits.pack_discharge_max_a is not None
    ) and pack_current_col is None:
        raise ValueError("Pack-current validation requires column 'pack_current_a'")

    return canonical, SignalLayout(
        cell_cols=cell_cols,
        temp_cols=temp_cols,
        pack_current_col=pack_current_col,
        pack_voltage_col=pack_voltage_col,
    )


def coerce_required_numeric(frame: pd.DataFrame) -> pd.DataFrame:
    """Parse real measurements without coercing complex or temporal values."""
    numeric: dict[str, pd.Series] = {}
    for name in frame.columns:
        values = frame[name]
        if values.dtype.kind in "cMm":
            numeric[name] = pd.Series(np.nan, index=frame.index, dtype=float)
            continue
        if is_object_dtype(values.dtype) or isinstance(values.dtype, pd.CategoricalDtype):
            values = values.astype(object)
            unsupported_values = values.map(
                lambda value: isinstance(value, (complex, np.complexfloating, np.ndarray))
            )
            if unsupported_values.any():
                values = values.mask(unsupported_values, np.nan)
        numeric[name] = pd.to_numeric(values, errors="coerce")
    return pd.DataFrame(numeric, index=frame.index)


def _first_true_position(mask: np.ndarray) -> tuple[int, int] | None:
    if not mask.any():
        return None

    flat_position = int(np.argmax(mask))
    row_pos, column_pos = divmod(flat_position, mask.shape[1])
    return row_pos, column_pos


def _invalid_numeric_error(
    frame: pd.DataFrame,
    numeric: pd.DataFrame,
    *,
    row_offset: int = 0,
) -> tuple[int, ValueError] | None:
    columns = list(numeric.columns)
    numeric_missing = numeric.isna().to_numpy(dtype=bool)
    invalid_numeric = numeric_missing | _required_boolean_mask(frame, columns)
    values = numeric.to_numpy(dtype=float, na_value=np.nan)
    non_finite = ~np.isfinite(values) & ~numeric_missing

    invalid_position = _first_true_position(invalid_numeric | non_finite)
    if invalid_position is None:
        return None

    row_pos, column_pos = invalid_position
    column = numeric.columns[column_pos]
    row_index = frame.index[row_pos]
    if invalid_numeric[row_pos, column_pos]:
        raw_value = frame.iloc[row_pos][column]
        return row_pos, ValueError(
            "Required numeric value is missing or non-numeric at "
            f"data row {row_offset + row_pos + 1} (index {row_index!r}), "
            f"column {column!r}: {raw_value!r}"
        )

    value = values[row_pos, column_pos]
    return row_pos, ValueError(
        "Required numeric value is non-finite at "
        f"data row {row_offset + row_pos + 1} (index {row_index!r}), "
        f"column {column!r}: {value!r}"
    )


def raise_invalid_numeric_value(
    frame: pd.DataFrame,
    numeric: pd.DataFrame,
    *,
    row_offset: int = 0,
) -> None:
    error = _invalid_numeric_error(frame, numeric, row_offset=row_offset)
    if error is not None:
        raise error[1]


def _valid_timestamp_positions_and_values(
    frame: pd.DataFrame,
    numeric: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    timestamp = numeric["timestamp_s"]
    invalid = timestamp.isna().to_numpy(dtype=bool).copy()
    invalid |= _required_boolean_mask(frame, ["timestamp_s"])[:, 0]
    values = timestamp.to_numpy(dtype=float, na_value=np.nan)
    invalid |= ~np.isfinite(values)
    positions = np.flatnonzero(~invalid)
    return positions, values[positions]


def valid_timestamp_values(
    frame: pd.DataFrame,
    numeric: pd.DataFrame,
) -> pd.Series:
    _, values = _valid_timestamp_positions_and_values(frame, numeric)
    return pd.Series(values, dtype=float)


def _timestamp_regression_error(
    frame: pd.DataFrame,
    numeric: pd.DataFrame,
    *,
    previous_timestamp: float | None,
) -> tuple[int, ValueError] | None:
    positions, values = _valid_timestamp_positions_and_values(frame, numeric)
    if not len(values):
        return None
    if previous_timestamp is not None and float(values[0]) < previous_timestamp:
        return int(positions[0]), ValueError("timestamp_s must be non-decreasing")
    decreases = np.flatnonzero(np.diff(values) < 0)
    if not len(decreases):
        return None
    row_pos = int(positions[int(decreases[0]) + 1])
    return row_pos, ValueError("timestamp_s must be non-decreasing")


def _invalid_balancing_error(
    balance_values: pd.Series | None,
    *,
    row_offset: int,
) -> tuple[int, ValueError] | None:
    if balance_values is None:
        return None
    invalid = np.fromiter(
        (parse_balancing_status(value) is None for value in balance_values.to_numpy(dtype=object)),
        dtype=bool,
        count=len(balance_values),
    )
    positions = np.flatnonzero(invalid)
    if not len(positions):
        return None
    row_pos = int(positions[0])
    return row_pos, ValueError(
        f"Balancing status must be 0/1 or boolean at data row {row_offset + row_pos + 1}"
    )


def raise_first_strict_input_error(
    frame: pd.DataFrame,
    numeric: pd.DataFrame,
    balance_values: pd.Series | None,
    *,
    row_offset: int = 0,
    previous_timestamp: float | None = None,
) -> None:
    """Raise the earliest strict input defect independent of measurement chunking."""
    candidates: list[tuple[int, int, ValueError]] = []
    numeric_error = _invalid_numeric_error(frame, numeric, row_offset=row_offset)
    if numeric_error is not None:
        candidates.append((numeric_error[0], 0, numeric_error[1]))
    timestamp_error = _timestamp_regression_error(
        frame,
        numeric,
        previous_timestamp=previous_timestamp,
    )
    if timestamp_error is not None:
        candidates.append((timestamp_error[0], 1, timestamp_error[1]))
    balancing_error = _invalid_balancing_error(balance_values, row_offset=row_offset)
    if balancing_error is not None:
        candidates.append((balancing_error[0], 2, balancing_error[1]))
    if candidates:
        raise min(candidates, key=lambda item: (item[0], item[1]))[2]
