"""CSV evidence references physical file lines, not logical CSV record numbers."""

import csv
import io
import random

import pytest

from batterylog_research.voltage_step_audit import audit_voltage_csv


def run(text: str) -> dict[str, object]:
    return audit_voltage_csv(io.StringIO(text), peer_step_threshold_v=0.05, max_gap_s=2)


def test_event_after_quoted_multiline_note_reports_true_physical_line():
    source = (
        "timestamp_s,cell_1_v,cell_2_v,cell_3_v,notes\n"
        '0,3.5,3.5,3.5,"first line\nsecond line"\n'
        "1,3.5,3.3,3.5,third\n"
    )
    event = run(source)["examples"][0]
    assert event["csv_row"] == 4
    assert event["signal"] == "cell_2_v"


def test_multiline_note_in_flagged_record_uses_record_start_line():
    source = (
        "timestamp_s,cell_1_v,cell_2_v,cell_3_v,notes\n"
        "0,3.5,3.5,3.5,ok\n"
        '1,3.5,3.3,3.5,"event starts here\nand continues here"\n'
    )
    assert run(source)["examples"][0]["csv_row"] == 3


def test_multiple_multiline_records_accumulate_physical_offsets():
    source = (
        "timestamp_s,cell_1_v,cell_2_v,cell_3_v,notes\n"
        '0,3.5,3.5,3.5,"a\nb\nc"\n'
        '1,3.5,3.3,3.5,"d\ne"\n'
        "2,3.5,3.5,3.5,last\n"
    )
    result = run(source)
    assert [event["csv_row"] for event in result["examples"]] == [5, 7]


def test_error_after_multiline_record_points_to_real_physical_line():
    source = (
        "timestamp_s,cell_1_v,cell_2_v,cell_3_v,notes\n"
        '0,3.5,3.5,3.5,"a\nb"\n'
        "1,3.5,not_a_number,3.5,no\n"
    )
    with pytest.raises(ValueError, match=r"CSV row 4"):
        run(source)


def test_normal_single_line_csv_keeps_previous_line_contract():
    source = "timestamp_s,cell_1_v,cell_2_v,cell_3_v\n0,3.5,3.5,3.5\n1,3.5,3.3,3.5\n"
    assert run(source)["examples"][0]["csv_row"] == 3


def test_one_csv_record_per_line_with_crlf():
    source = (
        "timestamp_s,cell_1_v,cell_2_v,cell_3_v,notes\r\n"
        '0,3.5,3.5,3.5,"line one\r\nline two"\r\n'
        "1,3.5,3.3,3.5,ok\r\n"
    )
    assert run(source)["examples"][0]["csv_row"] == 4


def test_seeded_metamorphic_physical_line_invariance():
    """Multiline unused metadata must not change the detected voltage event."""
    rng = random.Random(20261012)
    for _ in range(1000):
        cell_count = rng.choice([3, 4, 5, 8, 16, 48, 96])
        extra_lines_before = rng.randrange(0, 9)
        extra_lines_on_event = rng.randrange(0, 9)
        header = [
            "timestamp_s",
            *(f"cell_{i}_v" for i in range(1, cell_count + 1)),
            "notes",
        ]
        initial = [3.5] * cell_count
        anomalous = [3.5] * cell_count
        anomalous[rng.randrange(cell_count)] = 3.3

        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(header)
        writer.writerow([0, *initial, "\n".join(["note"] * (extra_lines_before + 1))])
        writer.writerow([1, *anomalous, "\n".join(["event"] * (extra_lines_on_event + 1))])
        result = run(output.getvalue())
        assert result["cell_step_observations_flagged"] == 1
        assert result["examples"][0]["csv_row"] == 3 + extra_lines_before
        assert result["examples"][0]["signal"] == f"cell_{anomalous.index(3.3) + 1}_v"
        assert result["examples"][0]["peer_relative_step_v"] == pytest.approx(-0.2)
