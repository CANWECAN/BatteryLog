import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

from .config import SignalMapping, SignalPattern

_CANONICAL_CELL_RE = re.compile(r"^cell_(\d+)_v$")
_CANONICAL_TEMP_RE = re.compile(r"^temp_(\d+)_c$")


@dataclass(frozen=True)
class ResolvedSignalMapping:
    timestamp_source: str
    cell_columns: tuple[tuple[int, str], ...]
    temperature_columns: tuple[tuple[int, str], ...]

    @property
    def source_columns(self) -> tuple[str, ...]:
        return (
            self.timestamp_source,
            *(column for _, column in self.cell_columns),
            *(column for _, column in self.temperature_columns),
        )

    @property
    def canonical_columns(self) -> tuple[str, ...]:
        return (
            "timestamp_s",
            *(f"cell_{index}_v" for index, _ in self.cell_columns),
            *(f"temp_{index}_c" for index, _ in self.temperature_columns),
        )


def _indexed_canonical_columns(
    columns: Iterable[object],
    pattern: re.Pattern[str],
    kind: str,
) -> list[str]:
    indexed: list[tuple[int, str]] = []
    seen_indexes: dict[int, str] = {}

    for raw_column in columns:
        column = str(raw_column)
        match = pattern.fullmatch(column)
        if match is None:
            continue

        index = int(match.group(1))
        if index in seen_indexes:
            previous = seen_indexes[index]
            raise ValueError(f"Duplicate {kind} signal index {index}: {previous!r} and {column!r}")
        seen_indexes[index] = column
        indexed.append((index, column))

    indexed.sort(key=lambda item: (item[0], item[1]))
    return [column for _, column in indexed]


def find_canonical_signal_columns(columns: Iterable[object]) -> tuple[list[str], list[str]]:
    raw_columns = list(columns)
    cell_columns = _indexed_canonical_columns(raw_columns, _CANONICAL_CELL_RE, "cell")
    indexed_temperature_columns = _indexed_canonical_columns(
        raw_columns,
        _CANONICAL_TEMP_RE,
        "temperature",
    )

    has_legacy_temperature = "temp_c" in raw_columns
    if has_legacy_temperature and indexed_temperature_columns:
        raise ValueError("Legacy temp_c cannot be combined with indexed temp_<n>_c signals")

    temperature_columns = ["temp_c"] if has_legacy_temperature else indexed_temperature_columns
    return cell_columns, temperature_columns


def _matched_indexed_columns(
    columns: Iterable[str],
    mapping: SignalPattern,
    kind: str,
) -> list[tuple[int, str]]:
    compiled = re.compile(mapping.pattern)
    indexed: dict[int, str] = {}

    for column in columns:
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


def resolve_signal_mapping(
    columns: Iterable[object],
    mapping: SignalMapping,
) -> ResolvedSignalMapping:
    raw_columns = list(columns)
    non_string = [column for column in raw_columns if not isinstance(column, str)]
    if non_string:
        joined = ", ".join(repr(column) for column in non_string)
        raise TypeError(f"Source signal names must be strings: {joined}")

    string_columns = [str(column) for column in raw_columns]
    duplicated = sorted(column for column, count in Counter(string_columns).items() if count > 1)
    if duplicated:
        joined = ", ".join(repr(column) for column in duplicated)
        raise ValueError(f"Duplicate source signal name(s): {joined}")

    if mapping.timestamp not in string_columns:
        raise ValueError(f"Mapped timestamp column {mapping.timestamp!r} is missing")

    cell_columns = _matched_indexed_columns(
        string_columns,
        mapping.cell_voltage,
        "cell-voltage",
    )
    temperature_columns = _matched_indexed_columns(
        string_columns,
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

    return ResolvedSignalMapping(
        timestamp_source=mapping.timestamp,
        cell_columns=tuple(cell_columns),
        temperature_columns=tuple(temperature_columns),
    )


def canonicalize_battery_signals(
    frame: pd.DataFrame,
    mapping: SignalMapping | None,
) -> pd.DataFrame:
    if mapping is None:
        return frame

    resolved = resolve_signal_mapping(frame.columns, mapping)
    canonical = frame.loc[:, list(resolved.source_columns)].copy()
    canonical.columns = list(resolved.canonical_columns)
    return canonical
