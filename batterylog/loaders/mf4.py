from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from batterylog.config import SignalMapping
from batterylog.signals import find_canonical_signal_columns, resolve_signal_mapping

DEFAULT_MDF_CHUNK_RAM_BYTES = 64 * 1024 * 1024
_MDF_SUFFIXES = frozenset({".mf4", ".mdf"})
_CANONICAL_TIMESTAMP = "timestamp_s"


def is_mdf_path(path: str | Path) -> bool:
    return Path(path).suffix.casefold() in _MDF_SUFFIXES


def _load_asammdf() -> tuple[type[Any], type[Exception]]:
    if find_spec("asammdf") is None:
        raise ImportError(
            "MF4/MDF support requires the optional 'mf4' dependency; "
            "install with 'pip install batterylog[mf4]'"
        )

    try:
        from asammdf import MDF
        from asammdf.blocks.utils import MdfException
    except (ImportError, OSError) as exc:
        raise ImportError(
            "The optional MF4/MDF backend is installed but could not be imported; "
            "verify the batterylog[mf4] installation and platform/native-library policy"
        ) from exc

    return MDF, MdfException


def _normalize_unit(unit: object) -> str:
    if not isinstance(unit, str):
        return ""
    return unit.strip().replace(" ", "").casefold()


def _validate_engineering_unit(*, name: str, unit: object, kind: str) -> None:
    normalized = _normalize_unit(unit)
    if kind == "cell-voltage":
        accepted = {"v", "volt", "volts"}
        expected = "V"
    elif kind == "temperature":
        accepted = {"degc", "°c", "celsius"}
        expected = "degC/°C"
    else:  # pragma: no cover - internal contract
        raise RuntimeError(f"Unsupported MDF signal kind: {kind}")

    if normalized not in accepted:
        shown = unit if isinstance(unit, str) and unit else "<missing>"
        raise ValueError(
            f"MDF channel {name!r} has unit {shown!r}; expected {expected}. "
            "Automatic unit conversion is not supported."
        )


def _unique_occurrence(mdf: Any, name: str) -> tuple[int, int]:
    occurrences = tuple(mdf.whereis(name))
    if not occurrences:
        raise ValueError(f"Mapped MDF channel {name!r} is missing")
    if len(occurrences) != 1:
        locations = ", ".join(f"group {group}/channel {index}" for group, index in occurrences)
        raise ValueError(f"MDF channel {name!r} is ambiguous; found at {locations}")
    return occurrences[0]


def _resolve_mdf_selection(
    mdf: Any,
    signal_mapping: SignalMapping | None,
) -> tuple[str, list[str], list[tuple[str, int, int]]]:
    channel_names = [str(name) for name in mdf.channels_db if str(name)]

    if signal_mapping is None:
        cell_columns, temperature_columns = find_canonical_signal_columns(channel_names)
        if not cell_columns:
            raise ValueError("No cell voltage columns found")
        if not temperature_columns:
            raise ValueError("No temperature columns found")
        timestamp_source = _CANONICAL_TIMESTAMP
        source_names = [*cell_columns, *temperature_columns]
    else:
        channel_names = [name for name in channel_names if name != signal_mapping.timestamp]
        resolved = resolve_signal_mapping(
            [signal_mapping.timestamp, *channel_names], signal_mapping
        )
        timestamp_source = resolved.timestamp_source
        cell_columns = [name for _, name in resolved.cell_columns]
        temperature_columns = [name for _, name in resolved.temperature_columns]
        source_names = [*cell_columns, *temperature_columns]

    cell_sources = set(cell_columns)
    channel_specs: list[tuple[str, int, int]] = []
    for name in source_names:
        group, index = _unique_occurrence(mdf, name)
        unit = mdf.get_channel_unit(name=name, group=group, index=index)
        kind = "cell-voltage" if name in cell_sources else "temperature"
        _validate_engineering_unit(name=name, unit=unit, kind=kind)
        channel_specs.append((name, group, index))

    return timestamp_source, source_names, channel_specs


def _iter_mdf_chunks(
    source: str | Path | BinaryIO,
    *,
    signal_mapping: SignalMapping | None,
    chunk_ram_bytes: int,
) -> Iterator[pd.DataFrame]:
    if (
        isinstance(chunk_ram_bytes, bool)
        or not isinstance(chunk_ram_bytes, int)
        or chunk_ram_bytes <= 0
    ):
        raise ValueError("chunk_ram_bytes must be a positive integer")

    MDF, MdfException = _load_asammdf()
    try:
        with MDF(
            source,
            use_display_names=False,
            process_bus_logging=False,
        ) as mdf:
            timestamp_source, source_names, channel_specs = _resolve_mdf_selection(
                mdf,
                signal_mapping,
            )

            for frame in mdf.iter_to_dataframe(
                channels=channel_specs,
                time_from_zero=False,
                empty_channels="skip",
                use_display_names=False,
                time_as_date=False,
                reduce_memory_usage=False,
                raw=False,
                ignore_value2text_conversions=False,
                use_interpolation=False,
                only_basenames=False,
                chunk_ram_size=chunk_ram_bytes,
                interpolate_outwards_with_nan=True,
                numeric_1D_only=True,
            ):
                missing = sorted(set(source_names) - set(frame.columns))
                if missing:
                    joined = ", ".join(repr(name) for name in missing)
                    raise ValueError(f"MDF extraction omitted required channel(s): {joined}")

                chunk = frame.loc[:, source_names].copy()
                timestamps = frame.index.to_numpy(dtype=float, copy=True)
                chunk.insert(0, timestamp_source, timestamps)
                chunk.reset_index(drop=True, inplace=True)
                yield chunk
    except MdfException as exc:
        raise ValueError(f"Failed to read MDF measurement: {exc}") from exc


@dataclass(frozen=True)
class MdfPathLoader:
    path: Path
    chunk_ram_bytes: int = DEFAULT_MDF_CHUNK_RAM_BYTES
    source_format: str = "mf4"

    def iter_chunks(
        self,
        *,
        signal_mapping: SignalMapping | None,
    ) -> Iterator[pd.DataFrame]:
        yield from _iter_mdf_chunks(
            self.path,
            signal_mapping=signal_mapping,
            chunk_ram_bytes=self.chunk_ram_bytes,
        )


@dataclass(frozen=True)
class MdfFileLoader:
    handle: BinaryIO
    chunk_ram_bytes: int = DEFAULT_MDF_CHUNK_RAM_BYTES
    source_format: str = "mf4"

    def iter_chunks(
        self,
        *,
        signal_mapping: SignalMapping | None,
    ) -> Iterator[pd.DataFrame]:
        self.handle.seek(0)
        yield from _iter_mdf_chunks(
            self.handle,
            signal_mapping=signal_mapping,
            chunk_ram_bytes=self.chunk_ram_bytes,
        )
