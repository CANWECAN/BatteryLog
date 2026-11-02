import csv
import io
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from batterylog.config import SignalMapping

DEFAULT_CSV_CHUNK_ROWS = 50_000


def _validate_header(header: list[str]) -> list[str]:
    if not header or all(not column for column in header):
        raise ValueError("Battery log has no CSV header")
    if any(not column for column in header):
        raise ValueError("CSV header contains an empty column name")

    duplicates = sorted(column for column, count in Counter(header).items() if count > 1)
    if duplicates:
        joined = ", ".join(repr(column) for column in duplicates)
        raise ValueError(f"Duplicate CSV column name(s): {joined}")

    return header


def _validate_data_row_widths(handle: BinaryIO) -> None:
    handle.seek(0)
    reader = None
    try:
        reader = pd.read_csv(
            handle,
            encoding="utf-8-sig",
            header=None,
            dtype=str,
            keep_default_na=False,
            na_filter=False,
            chunksize=DEFAULT_CSV_CHUNK_ROWS,
        )
        for _ in reader:
            pass
    except pd.errors.ParserError as exc:
        raise ValueError(f"Invalid CSV structure: {exc}") from exc
    finally:
        if reader is not None:
            reader.close()
        handle.seek(0)


def _read_header_from_bytes(data: bytes) -> list[str]:
    with io.BytesIO(data) as handle:
        return _read_header_from_binary_file(handle)


def _read_header_from_binary_file(handle: BinaryIO) -> list[str]:
    header = _validate_header(_read_csv_header(handle))
    _validate_data_row_widths(handle)
    return header


def _read_csv_header(handle: BinaryIO) -> list[str]:
    """Read only the first CSV record; leave validation to the caller."""
    handle.seek(0)
    text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
    try:
        reader = csv.reader(text)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("Battery log is empty") from exc
    finally:
        text.detach()
        handle.seek(0)

    return header


def _validate_chunk_rows(chunk_rows: int) -> None:
    if isinstance(chunk_rows, bool) or not isinstance(chunk_rows, int) or chunk_rows <= 0:
        raise ValueError("chunk_rows must be a positive integer")


def load_battery_csv_bytes(
    data: bytes, *, signal_mapping: SignalMapping | None = None
) -> pd.DataFrame:
    _read_header_from_bytes(data)
    timestamp = (
        signal_mapping.timestamp if isinstance(signal_mapping, SignalMapping) else "timestamp_s"
    )
    return pd.read_csv(
        io.BytesIO(data),
        encoding="utf-8-sig",
        skip_blank_lines=False,
        dtype={timestamp: str},
    )


def load_battery_csv(
    path: str | Path, *, signal_mapping: SignalMapping | None = None
) -> pd.DataFrame:
    return load_battery_csv_bytes(Path(path).read_bytes(), signal_mapping=signal_mapping)


def iter_battery_csv(
    path: str | Path,
    *,
    chunk_rows: int,
    signal_mapping: SignalMapping | None = None,
) -> Iterator[pd.DataFrame]:
    source = Path(path)
    with source.open("rb") as handle:
        yield from iter_battery_csv_file(
            handle, chunk_rows=chunk_rows, signal_mapping=signal_mapping
        )


def iter_battery_csv_file(
    handle: BinaryIO,
    *,
    chunk_rows: int,
    signal_mapping: SignalMapping | None = None,
) -> Iterator[pd.DataFrame]:
    _validate_chunk_rows(chunk_rows)
    _read_header_from_binary_file(handle)
    timestamp = (
        signal_mapping.timestamp if isinstance(signal_mapping, SignalMapping) else "timestamp_s"
    )

    reader = pd.read_csv(
        handle,
        encoding="utf-8-sig",
        chunksize=chunk_rows,
        skip_blank_lines=False,
        dtype={timestamp: str},
    )
    try:
        yield from reader
    finally:
        reader.close()


@dataclass(frozen=True)
class CsvPathLoader:
    path: Path
    chunk_rows: int = DEFAULT_CSV_CHUNK_ROWS
    source_format: str = "csv"

    def iter_chunks(
        self,
        *,
        signal_mapping: SignalMapping | None,
    ) -> Iterator[pd.DataFrame]:
        yield from iter_battery_csv(
            self.path, chunk_rows=self.chunk_rows, signal_mapping=signal_mapping
        )


@dataclass(frozen=True)
class CsvFileLoader:
    handle: BinaryIO
    chunk_rows: int = DEFAULT_CSV_CHUNK_ROWS
    source_format: str = "csv"

    def iter_chunks(
        self,
        *,
        signal_mapping: SignalMapping | None,
    ) -> Iterator[pd.DataFrame]:
        yield from iter_battery_csv_file(
            self.handle, chunk_rows=self.chunk_rows, signal_mapping=signal_mapping
        )
