# Copyright (c) 2026 Berk Ozfiliz.
"""Independent source evidence and no-alignment boundaries for the pinned study."""

import io

import pytest

cantools = pytest.importorskip("cantools")

from batterylog_research.precharge_can_source_audit import audit_stream, run

HEADER = "Time Stamp,ID,Extended,Bus,DLC,D1,D2,D3,D4,D5,D6,D7,D8\n"
DBC = """
VERSION ""
NS_ :
BS_:
BU_: BMS
BO_ 274 Measurements: 8 BMS
 SG_ Battery_Current : 0|16@1+ (0.1,-819.2) [0|0] "Amps" BMS
 SG_ Battery_Volts : 16|16@1+ (0.1,0) [0|0] "Volts" BMS
 SG_ DC_link : 56|8@1+ (4,0) [0|0] "Volts" BMS
BO_ 506 State: 8 BMS
 SG_ ST_DCSW_HVSTO : 12|2@1+ (1,0) [0|3] "status" BMS
VAL_ 506 ST_DCSW_HVSTO 0 "OPEN" 1 "PRECHRG" 2 "CLOSED" 3 "SNA";
"""


def database():
    return cantools.database.load_string(DBC, database_format="dbc")


def row(tick, cid, data, bus=0, extended=0):
    return f"{tick},{cid:x},{extended},{bus},8," + ",".join(f"{b:02x}" for b in data) + "\n"


def measurement(tick, bus=0):
    # Independent intended values: raw current 8200 -> 0.8 A,
    # pack raw 3500 -> 350 V and DC-link raw 75 -> 300 V.
    data = bytes([0x08, 0x20, 0xAC, 0x0D, 0, 0, 0, 75])
    return row(tick, 0x112, data, bus)


def state(tick, code, bus=0):
    return row(tick, 0x1FA, bytes([0, code << 4, 0, 0, 0, 0, 0, 0]), bus)


def review(text):
    return audit_stream(io.StringIO(HEADER + text), database(), vehicle="bmw")


@pytest.mark.parametrize("code", [0, 1, 2, 3])
def test_all_raw_states_retained_with_declared_labels(code):
    result = review(state(1, code))
    signal = result["signals"]["0/0x1FA/ST_DCSW_HVSTO"]
    assert signal["raw_code_counts"] == {str(code): 1}
    assert signal["all_ones_bit_patterns"] == (code == 3)
    assert result["counts"]["precharge_label_observations"] == (code == 1)
    assert result["curve_review_eligible"] is False
    assert result["clock_basis"] == "unverified_integer_ticks"
    assert "active_spans" not in result


def test_neighbours_keep_large_ticks_original_order_and_distinct_frames():
    tick = 2**53 + 1
    result = review(measurement(tick) + state(tick + 1, 1) + measurement(tick + 2))
    example = result["precharge_label_examples"][0]
    assert example["source_line"] == 3
    assert example["recorded_clock"] == tick + 1
    before, after = example["preceding_measurement_frame"], example["following_measurement_frame"]
    assert (before["source_line"], before["recorded_clock"]) == (2, tick)
    assert (after["source_line"], after["recorded_clock"]) == (4, tick + 2)
    assert before["measurements"]["Battery_Volts"]["value_as_declared"] == 350
    assert before["measurements"]["DC_link"]["value_as_declared"] == 300
    assert before["measurements"]["Battery_Current"]["value_as_declared"] == pytest.approx(0.8)
    assert result["neighbours_are_aligned_measurements"] is False


def test_other_bus_cannot_supply_phase_neighbours_or_transitions():
    result = review(measurement(1, 0) + state(2, 1, 1) + measurement(3, 0) + state(4, 0, 0))
    example = result["precharge_label_examples"][0]
    assert example["preceding_measurement_frame"] is None
    assert example["following_measurement_frame"] is None
    assert result["counts"]["reported_code_transitions"] == 0


def test_duplicate_ticks_retain_source_order_without_joining():
    result = review(measurement(1) + state(1, 1) + measurement(1))
    example = result["precharge_label_examples"][0]
    assert example["preceding_measurement_frame"]["source_line"] == 2
    assert example["following_measurement_frame"]["source_line"] == 4
    assert example["preceding_measurement_frame"]["recorded_clock"] == 1
    assert example["following_measurement_frame"]["recorded_clock"] == 1
    assert result["curve_review_eligible"] is False


def test_invalid_identifier_is_counted_not_repaired_or_hidden():
    bad = "2,2.00E+02,0,0,8,00,00,00,00,00,00,00,00\n"
    result = review(state(1, 0) + bad + state(3, 1))
    assert result["counts"]["records_input"] == 3
    assert result["counts"]["malformed_records"] == 1
    assert result["malformed_examples"] == [{"source_line": 3, "reason": "INVALID_CAPTURE_RECORD"}]
    assert result["curve_review_eligible"] is False


def test_decreasing_tick_is_retained_as_issue_without_seconds_conversion():
    result = review(state(3, 0) + state(2, 1))
    assert result["counts"]["precharge_label_observations"] == 0
    assert result["malformed_examples"][0]["reason"] == "CAPTURE_CLOCK_DECREASES"


def test_signal_setpoint_roles_do_not_create_aligned_curve_or_status():
    result = review(state(1, 0) + measurement(2) + state(3, 1) + state(4, 2))
    assert result["counts"]["reported_code_transitions"] == 2
    assert result["reported_code_transition_examples"][0]["previous"]["raw_code"] == 0
    assert result["reported_code_transition_examples"][1]["current"]["raw_code"] == 2
    assert "PASS" not in str(result)
    assert "declared_interval_covered" not in result


@pytest.mark.parametrize("text", ["", HEADER])
def test_empty_capture_rejected(text):
    with pytest.raises(ValueError):
        audit_stream(io.StringIO(text), database(), vehicle="bmw")


def test_selected_extended_frame_rejected():
    with pytest.raises(ValueError, match="frame type mismatch"):
        review(row(1, 0x1FA, bytes(8), extended=1))


def test_reference_layout_change_rejected():
    db = cantools.database.load_string(DBC.replace("(4,0)", "(5,0)"), database_format="dbc")
    with pytest.raises(ValueError, match="layout differs"):
        audit_stream(io.StringIO(HEADER + measurement(1)), db, vehicle="bmw")


def test_existing_output_preserved_before_reading_inputs(tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        run(tmp_path / "missing", output)
    assert output.read_text(encoding="utf-8") == "keep"


def test_wrong_source_identity_prevents_publication(tmp_path):
    (tmp_path / "ex30-battery.csv").write_text("wrong", encoding="utf-8")
    output = tmp_path / "new.json"
    with pytest.raises(ValueError, match="identity mismatch"):
        run(tmp_path, output)
    assert not output.exists()
