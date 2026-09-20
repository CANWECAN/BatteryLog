import csv
import io
from collections import Counter
from pathlib import Path

import pandas as pd


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

    if not header or all(not column for column in header):
        raise ValueError("Battery log has no CSV header")
    if any(not column for column in header):
        raise ValueError("CSV header contains an empty column name")

    duplicates = sorted(column for column, count in Counter(header).items() if count > 1)
    if duplicates:
        joined = ", ".join(repr(column) for column in duplicates)
        raise ValueError(f"Duplicate CSV column name(s): {joined}")

    return header


def load_battery_csv_bytes(data: bytes) -> pd.DataFrame:
    _read_header_from_bytes(data)
    return pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")


def load_battery_csv(path: str | Path) -> pd.DataFrame:
    return load_battery_csv_bytes(Path(path).read_bytes())
