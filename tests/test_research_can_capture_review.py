"""Transport evidence and partial-decoder rejection, independent of real fixtures."""

import csv
import io
import json

import pytest

cantools = pytest.importorskip("cantools")
canmatrix = pytest.importorskip("canmatrix.formats")

from batterylog_research.can_capture_review import (
    LAYOUTS,
    CaptureFrame,
    CaptureIssue,
    read_capture,
    review_paths,
    review_stream,
)

DBC = """VERSION ""
NS_ :
BS_:
BU_: BMS
BO_ 274 Battery: 8 BMS
 SG_ Current : 0|16@1+ (0.1,-819.2) [0|819.2] "Amps" BMS
 SG_ Voltage : 16|16@1+ (0.1,0) [0|819] "Volts" BMS
BO_ 322 Multiplex: 8 BMS
 SG_ selector M : 0|8@1+ (1,0) [0|255] "" BMS
 SG_ Voltage m0 : 31|16@0+ (1,0) [0|6000] "V+1" BMS
 SG_ Cell m3 : 31|16@0+ (1,0) [0|6000] "mV" BMS
 SG_ Number m3 : 23|8@0+ (1,0) [0|255] "number" BMS
BO_ 576 WideMessage: 8 BMS
 SG_ Wide : 0|56@1+ (1,0) [0|0] "" BMS
"""


@pytest.fixture
def decoders(tmp_path):
    dbc = tmp_path / "review.dbc"
    dbc.write_text(DBC)
    return (
        cantools.database.load_file(dbc, strict=True),
        canmatrix.loadp_flat(str(dbc)),
        dbc,
    )


def indexed(*, tick="1", identifier="112", extended="0", dlc="8", data=None):
    data = ["00"] * 8 if data is None else data
    return ",".join([tick, identifier, extended, "0", dlc, *data]) + "\n"


def capture(rows, layout="indexed_csv"):
    return io.StringIO(",".join(LAYOUTS[layout]) + "\n" + rows)


def review(rows, decoders, *, layout="indexed_csv", ids=(0x112,)):
    database, matrix, _ = decoders
    return review_stream(capture(rows, layout), database, matrix, layout=layout, selected_ids=ids)


def test_legal_hex_e_is_not_scientific_notation():
    records = list(
        read_capture(
            capture(indexed(identifier="2e2") + indexed(identifier="2.00E+02")), "indexed_csv"
        )
    )
    assert isinstance(records[0], CaptureFrame)
    assert records[0].frame_id == 0x2E2
    assert isinstance(records[1], CaptureIssue)
    assert records[1].line == 3


@pytest.mark.parametrize("text", ["", "ID,Data Bytes\n", "Time Stamp,ID\n"])
def test_wrong_or_empty_header_rejected(text):
    with pytest.raises(ValueError, match="header"):
        list(read_capture(io.StringIO(text), "indexed_csv"))


@pytest.mark.parametrize(
    "row",
    [
        indexed(identifier="800"),
        indexed(identifier="20000000", extended="1"),
        indexed(extended="2"),
        indexed(dlc="9"),
        indexed(dlc="2", data=["00", "", *["0"] * 6]),
        indexed(dlc="1", data=["00", "01", *["0"] * 6]),
        indexed(tick="1.5"),
        indexed(data=["GG", *["0"] * 7]),
        "1,112,0\n",
    ],
)
def test_malformed_record_is_counted_issue(row):
    records = list(read_capture(capture(row), "indexed_csv"))
    assert len(records) == 1 and isinstance(records[0], CaptureIssue)


def test_padding_is_not_payload():
    frame = next(
        read_capture(capture(indexed(dlc="1", data=["A", "", *["00"] * 6])), "indexed_csv")
    )
    assert frame.data == b"\x0a"


def test_bad_id_cannot_hide_clock_regression():
    records = list(
        read_capture(
            capture(
                indexed(tick="10") + indexed(tick="20", identifier="2.00E+02") + indexed(tick="15")
            ),
            "indexed_csv",
        )
    )
    assert isinstance(records[1], CaptureIssue)
    assert records[2].reason == "CAPTURE_CLOCK_DECREASES"


def test_clock_regression_on_unselected_id(decoders):
    result = review(indexed(tick="2") + indexed(tick="1", identifier="200"), decoders)
    assert result["counts"]["records_input"] == 2
    assert result["malformed_by_reason"] == {"CAPTURE_CLOCK_DECREASES": 1}


def test_multiline_record_keeps_physical_start_line():
    records = list(
        read_capture(
            capture('142,"00\n00 00 01 02 00 00 00"\n142,00 00 00 01 02 00 00 00\n', "id_payload"),
            "id_payload",
        )
    )
    assert [r.line for r in records] == [2, 4]


def test_csv_syntax_error_is_fatal():
    with pytest.raises(csv.Error, match="unexpected end"):
        list(read_capture(capture('142,"00\n', "id_payload"), "id_payload"))


def test_untimed_capture_does_not_invent_metadata(decoders):
    frame = next(
        read_capture(capture("00000142,00 00 00 01 02 00 00 00\n", "id_payload"), "id_payload")
    )
    assert frame.extended is frame.bus is frame.clock_ticks is None
    result = review(
        "00000142,00 00 00 01 02 00 00 00\n", decoders, layout="id_payload", ids=(0x142,)
    )
    assert result["recorded_clock_tick_range"] is None
    assert not result["analysis_preparation_eligible"]
    assert result["decoded_extrema_as_declared"]["0x142.Voltage"]["unit_as_declared"] == "V+1"


def test_unknown_selector_partial_is_not_success(decoders):
    result = review("142,62 00 00 01 02 00 00 00\n", decoders, layout="id_payload", ids=(0x142,))
    assert result["counts"]["strict_dbc_decode_rejections"] == 1
    assert result["counts"]["canmatrix_returned_fields_after_strict_rejection"] == 1
    assert result["counts"]["selected_frames_decoded_by_both"] == 0
    assert result["strict_decode_rejection_examples"][0]["other_decoder_field_names"] == [
        "selector"
    ]
    assert result["selectors_observed"] == {"0x142": {"98": 1}}
    assert not result["decoded_extrema_as_declared"]


def test_all_ones_is_retained_as_observation(decoders):
    result = review(indexed(data=["FF"] * 8), decoders)
    assert result["decoded_extrema_as_declared"]["0x112.Voltage"]["max"] == 6553.5
    assert result["unsigned_all_ones_raw_observations"]["0x112.Voltage"] == 1
    assert result["outside_dbc_declared_range_observations"]["0x112.Voltage"] == 1
    assert result["diagnostic_claim"] is False


def test_negative_current_not_clipped_by_inconsistent_dbc_range(decoders):
    result = review(indexed(data=["00", "20", *["00"] * 6]), decoders)
    assert result["decoded_extrema_as_declared"]["0x112.Current"]["min"] == 0
    result = review(indexed(data=["F6", "1F", *["00"] * 6]), decoders)
    assert result["decoded_extrema_as_declared"]["0x112.Current"]["min"] == -1
    assert result["outside_dbc_declared_range_observations"]["0x112.Current"] == 1


def test_explicit_extended_type_mismatch_not_decoded(decoders):
    result = review(indexed(extended="1"), decoders)
    assert result["counts"]["selected_frame_type_mismatches"] == 1
    assert result["counts"]["selected_frames_decoded_by_both"] == 0
    assert any("frame type" in b for b in result["analysis_blockers"])


def test_missing_selected_message_is_explicit(decoders):
    result = review(indexed(identifier="200"), decoders)
    assert result["selected_identifiers_not_observed"] == ["0x112"]
    assert any("absent" in b for b in result["analysis_blockers"])


def test_issue_examples_are_bounded_but_accounting_complete(decoders):
    result = review(indexed(identifier="2.00E+02") * 40, decoders)
    assert result["counts"]["malformed_records"] == 40
    assert len(result["malformed_examples"]) == 10


def test_duplicate_frames_preserved(decoders):
    result = review(indexed() * 2, decoders)
    assert result["counts"]["selected_frames_decoded_by_both"] == 2
    assert result["counts"]["independent_signal_values_compared"] == 4


def test_truncated_payload_not_a_measurement(decoders):
    result = review(indexed(dlc="1"), decoders)
    assert result["counts"]["strict_dbc_decode_rejections"] == 1
    assert result["counts"]["selected_frames_decoded_by_both"] == 0


def test_decoder_disagreement_stops_review(decoders, monkeypatch):
    _, matrix, _ = decoders
    frame = matrix.frame_by_id(__import__("canmatrix").ArbitrationId(0x112, extended=False))
    original = frame.decode

    def altered(data):
        result = original(data)
        result.pop("Voltage")
        return result

    monkeypatch.setattr(frame, "decode", altered)
    with pytest.raises(AssertionError, match="signal-set"):
        review(indexed(), decoders)


@pytest.mark.parametrize("corrupt", [False, True])
def test_large_raw_integer_keeps_bit_exact_comparison(decoders, monkeypatch, corrupt):
    _, matrix, _ = decoders
    frame = matrix.frame_by_id(__import__("canmatrix").ArbitrationId(0x240, extended=False))
    original = frame.decode

    def changed(data):
        result = original(data)
        if corrupt:
            result["Wide"].raw_value -= 1
        return result

    monkeypatch.setattr(frame, "decode", changed)
    row = indexed(identifier="240", data=["FF"] * 7 + ["00"])
    if corrupt:
        with pytest.raises(AssertionError, match="integer disagreement"):
            review(row, decoders, ids=(0x240,))
    else:
        result = review(row, decoders, ids=(0x240,))
        assert result["decoded_extrema_as_declared"]["0x240.Wide"]["max"] == 2**56 - 1


def test_staged_review_and_no_overwrite(tmp_path, decoders):
    source, output = tmp_path / "capture.csv", tmp_path / "review.json"
    source.write_text(",".join(LAYOUTS["indexed_csv"]) + "\n" + indexed())
    result = review_paths(source, decoders[2], output, layout="indexed_csv", selected_ids=[0x112])
    assert json.loads(output.read_text()) == result
    assert output.read_bytes() == (json.dumps(result, indent=2, allow_nan=False) + "\n").encode()
    assert len(result["source_sha256"]) == 64
    with pytest.raises(ValueError, match="already exists"):
        review_paths(source, decoders[2], output, layout="indexed_csv", selected_ids=[0x112])
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "capture.csv",
        "review.dbc",
        "review.json",
    ]


def test_bad_header_leaves_no_output(tmp_path, decoders):
    source, output = tmp_path / "bad.csv", tmp_path / "review.json"
    source.write_text("ID,Data Bytes\n")
    with pytest.raises(ValueError, match="header"):
        review_paths(source, decoders[2], output, layout="indexed_csv", selected_ids=[0x112])
    assert not output.exists()


def test_concurrent_report_creation_is_not_overwritten(tmp_path, decoders, monkeypatch):
    from batterylog_research import can_capture_review

    source, output = tmp_path / "capture.csv", tmp_path / "review.json"
    source.write_text(",".join(LAYOUTS["indexed_csv"]) + "\n" + indexed())
    original = can_capture_review.sha256
    calls = 0

    def concurrent_creation(path):
        nonlocal calls
        calls += 1
        digest = original(path)
        if calls == 4:
            output.write_text("concurrent report must survive")
        return digest

    monkeypatch.setattr(can_capture_review, "sha256", concurrent_creation)
    with pytest.raises(FileExistsError):
        review_paths(source, decoders[2], output, layout="indexed_csv", selected_ids=[0x112])
    assert output.read_text() == "concurrent report must survive"
    assert not list(tmp_path.glob(".capture-review-*"))
