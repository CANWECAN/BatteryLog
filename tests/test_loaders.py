from pathlib import Path

import pytest

from batterylog.loaders import load_battery_csv, load_battery_csv_bytes


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
