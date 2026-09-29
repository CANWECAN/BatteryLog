from io import BytesIO

import pytest

from batterylog.analysis.core import analyze_battery_bytes
from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.config import DataQualityConfig
from batterylog.loaders import CsvFileLoader

TOKENS = (
    "",
    '""',
    "NA",
    "N/A",
    "NaN",
    "nan",
    "null",
    "None",
    "inf",
    "-inf",
    "+inf",
    "Infinity",
    "-Infinity",
    "True",
    "False",
    "TRUE",
    "FALSE",
    "3.8",
    "+3.8",
    " 3.8 ",
    "3.8e0",
    "1e309",
    "-1e309",
    "1e400",
    "-1e400",
    '"3.8"',
    '"True"',
    '"nan"',
    '"1e400"',
    "0x10",
    "1_000",
    ".5",
    "5.",
    "-0",
    "-0.0",
    "bad",
)


def _csv_with_temp_token(token: str, position: int) -> bytes:
    values = ["21.0", "22.0", "23.0"]
    values[position] = token
    rows = [f"{index},3.8,{value}" for index, value in enumerate(values)]
    return ("timestamp_s,cell_1_v,temp_c\n" + "\n".join(rows) + "\n").encode()


@pytest.mark.parametrize("chunk_rows", [1, 2, 3, 4])
@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("token", TOKENS)
def test_csv_dtype_inference_is_chunk_boundary_independent(
    token: str,
    position: int,
    chunk_rows: int,
) -> None:
    data = _csv_with_temp_token(token, position)
    config = DataQualityConfig(mode="exclude_invalid_rows")

    whole = analyze_battery_bytes(data, data_quality=config)
    streaming = analyze_measurement_loader(
        CsvFileLoader(BytesIO(data), chunk_rows=chunk_rows),
        data_quality=config,
    )

    assert streaming == whole
