import re

import pandas as pd

from .config import SignalMapping, SignalPattern


def _matched_indexed_columns(
    columns: pd.Index,
    mapping: SignalPattern,
    kind: str,
) -> list[tuple[int, str]]:
    compiled = re.compile(mapping.pattern)
    indexed: dict[int, str] = {}

    for raw_column in columns:
        column = str(raw_column)
        match = compiled.fullmatch(column)
        if match is None:
            continue

        raw_index = match.group("index")
        if raw_index is None or re.fullmatch(r"[0-9]+", raw_index) is None:
            raise ValueError(
                f"{kind} mapping matched {column!r} with a non-numeric index {raw_index!r}"
            )

        index = int(raw_index)
        if index in indexed:
            previous = indexed[index]
            raise ValueError(f"Duplicate logical {kind} index {index}: {previous!r} and {column!r}")
        indexed[index] = column

    if not indexed:
        raise ValueError(f"Signal mapping matched no {kind} columns")

    return sorted(indexed.items(), key=lambda item: (item[0], item[1]))


def canonicalize_battery_signals(
    frame: pd.DataFrame,
    mapping: SignalMapping | None,
) -> pd.DataFrame:
    if mapping is None:
        return frame

    non_string = [column for column in frame.columns if not isinstance(column, str)]
    if non_string:
        joined = ", ".join(repr(column) for column in non_string)
        raise TypeError(f"Source signal names must be strings: {joined}")

    duplicated = frame.columns[frame.columns.duplicated()].tolist()
    if duplicated:
        joined = ", ".join(repr(str(column)) for column in duplicated)
        raise ValueError(f"Duplicate source signal name(s): {joined}")

    if mapping.timestamp not in frame.columns:
        raise ValueError(f"Mapped timestamp column {mapping.timestamp!r} is missing")

    cell_columns = _matched_indexed_columns(
        frame.columns,
        mapping.cell_voltage,
        "cell-voltage",
    )
    temperature_columns = _matched_indexed_columns(
        frame.columns,
        mapping.temperature,
        "temperature",
    )

    cell_sources = {column for _, column in cell_columns}
    temperature_sources = {column for _, column in temperature_columns}
    overlap = sorted(cell_sources & temperature_sources)
    if overlap:
        joined = ", ".join(repr(column) for column in overlap)
        raise ValueError(
            f"Signal mapping is ambiguous; column(s) match both cell-voltage "
            f"and temperature patterns: {joined}"
        )

    if mapping.timestamp in cell_sources or mapping.timestamp in temperature_sources:
        raise ValueError(
            f"Mapped timestamp column {mapping.timestamp!r} also matches a sensor pattern"
        )

    source_columns = [
        mapping.timestamp,
        *(column for _, column in cell_columns),
        *(column for _, column in temperature_columns),
    ]
    canonical_columns = [
        "timestamp_s",
        *(f"cell_{index}_v" for index, _ in cell_columns),
        *(f"temp_{index}_c" for index, _ in temperature_columns),
    ]

    canonical = frame.loc[:, source_columns].copy()
    canonical.columns = canonical_columns
    return canonical
