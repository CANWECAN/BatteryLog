import csv
import io
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

import pandas as pd


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


def _read_header_from_bytes(data: bytes) -> list[str]:
    with io.TextIOWrapper(
        io.BytesIO(data),
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("Battery log is empty") from exc

    return _validate_header(header)


def _read_header_from_path(path: str | Path) -> list[str]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("Battery log is empty") from exc

    return _validate_header(header)


def _read_header_from_binary_file(handle: BinaryIO) -> list[str]:
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

    return _validate_header(header)


def _validate_chunk_rows(chunk_rows: int) -> None:
    if isinstance(chunk_rows, bool) or not isinstance(chunk_rows, int) or chunk_rows <= 0:
        raise ValueError("chunk_rows must be a positive integer")


def load_battery_csv_bytes(data: bytes) -> pd.DataFrame:
    _read_header_from_bytes(data)
    return pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")


def load_battery_csv(path: str | Path) -> pd.DataFrame:
    return load_battery_csv_bytes(Path(path).read_bytes())


def iter_battery_csv(
    path: str | Path,
    *,
    chunk_rows: int,
) -> Iterator[pd.DataFrame]:
    _validate_chunk_rows(chunk_rows)

    source = Path(path)
    _read_header_from_path(source)
    yield from pd.read_csv(
        source,
        encoding="utf-8-sig",
        chunksize=chunk_rows,
    )


def iter_battery_csv_file(
    handle: BinaryIO,
    *,
    chunk_rows: int,
) -> Iterator[pd.DataFrame]:
    _validate_chunk_rows(chunk_rows)
    _read_header_from_binary_file(handle)

    reader = pd.read_csv(
        handle,
        encoding="utf-8-sig",
        chunksize=chunk_rows,
    )
    try:
        yield from reader
    finally:
        reader.close()
