from pathlib import Path
from typing import BinaryIO

from .base import MeasurementLoader
from .csv import CsvFileLoader, CsvPathLoader
from .mf4 import MdfFileLoader, MdfPathLoader, is_mdf_path


def measurement_loader_for_path(path: str | Path) -> MeasurementLoader:
    source = Path(path)
    if is_mdf_path(source):
        return MdfPathLoader(source)
    return CsvPathLoader(source)


def measurement_loader_for_file(
    handle: BinaryIO,
    *,
    source_name: str | Path | None = None,
) -> MeasurementLoader:
    if source_name is not None and is_mdf_path(source_name):
        return MdfFileLoader(handle)
    return CsvFileLoader(handle)
