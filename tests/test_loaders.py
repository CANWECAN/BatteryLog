from pathlib import Path

import pytest

from batterylog import ValidationLimits
from batterylog.analysis.core import analyze_battery_bytes
from batterylog.loaders import iter_battery_csv_file, load_battery_csv, load_battery_csv_bytes


def test_empty_csv_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="Battery log is empty"):
        load_battery_csv(path)


def test_blank_header_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "blank.csv"
    path.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="has no CSV header"):
        load_battery_csv(path)


def test_empty_column_name_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty_column.csv"
    path.write_text(
        "timestamp_s,,cell_1_v\n0,25,3.8\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="empty column name"):
        load_battery_csv(path)


def test_csv_row_with_extra_field_is_rejected_instead_of_shifting_columns() -> None:
    data = b"timestamp_s,temp_c,cell_1_v\n0,25,3.8,999\n1,26,3.9,999\n"

    with pytest.raises(ValueError):
        analyze_battery_bytes(
            data,
            limits=ValidationLimits(
                cell_max_v=30.0,
                temperature_max_c=1000.0,
            ),
        )


def test_utf8_bom_header_is_supported(tmp_path: Path) -> None:
    path = tmp_path / "bom.csv"
    path.write_text(
        "\ufefftimestamp_s,temp_c,cell_1_v\n0,25,3.8\n",
        encoding="utf-8",
    )

    frame = load_battery_csv(path)

    assert list(frame.columns) == ["timestamp_s", "temp_c", "cell_1_v"]


def test_byte_loader_matches_path_loader(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v\n0,25,3.8\n1,26,3.9\n",
        encoding="utf-8",
    )

    from_path = load_battery_csv(path)
    from_bytes = load_battery_csv_bytes(path.read_bytes())

    assert from_bytes.equals(from_path)


def test_binary_file_chunk_loader_matches_path_loader(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text(
        "timestamp_s,temp_c,cell_1_v\n0,25,3.8\n1,26,3.9\n2,27,4.0\n",
        encoding="utf-8",
    )

    expected = load_battery_csv(path)
    with path.open("rb") as handle:
        chunks = list(iter_battery_csv_file(handle, chunk_rows=2))
        assert not handle.closed

    assert len(chunks) == 2
    assert chunks[0].equals(expected.iloc[:2])
    assert chunks[1].equals(expected.iloc[2:])
