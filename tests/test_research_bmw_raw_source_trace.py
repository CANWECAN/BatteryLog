# Copyright 2026 Berk Ozfiliz
"""Authored byte records exercise trace preservation, not physical acceptance."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from batterylog_research import bmw_clock_provenance_audit as clock
from batterylog_research import bmw_raw_source_trace as trace


def electrical(current: int, pack: int, link: int) -> bytes:
    return current.to_bytes(2, "little") + pack.to_bytes(2, "little") + b"\0" * 3 + bytes([link])


def representations(records: list[tuple[int, int, bytes]], *, malformed: bool = False):
    csv_out, log_out = io.StringIO(newline=""), io.StringIO(newline="")
    cw, lw = csv.writer(csv_out), csv.writer(log_out, delimiter="\t")
    cw.writerow(clock.CSV_HEADER.split(","))
    lw.writerow(clock.LOG_HEADER.split("\t"))
    for index, (tick, frame_id, payload) in enumerate(records):
        token = "1.12E+2" if malformed else f"{frame_id:X}"
        cw.writerow(
            [
                tick,
                token,
                0,
                1,
                len(payload),
                *[f"{b:02X}" for b in payload],
                *["" for _ in range(8 - len(payload))],
            ]
        )
        lw.writerow(
            [
                "",
                0,
                f"{index}",
                "R",
                tick,
                "E",
                f"{frame_id:X}",
                len(payload),
                f"0x{payload.hex()}",
                "DefaultParser",
                "opaque\nextra",
            ]
        )
    return csv_out.getvalue().encode(), log_out.getvalue().encode()


@pytest.mark.parametrize(
    "current,pack,link",
    [
        (8191, 3905, 97),
        (65535, 65535, 255),
        (0, 0, 0),
        (8192, 8190, 205),
        (8193, 8191, 206),
        (16384, 65534, 254),
    ],
)
def test_raw_codes_signed_candidates_and_range_annotations(current, pack, link):
    raw = representations([(100, 0x112, electrical(current, pack, link))])
    row = trace._trace_records(*raw)["frames"][0]
    c = row["candidates"]
    assert c["Battery_Current"]["raw_code"] == current
    assert c["Battery_Volts"]["raw_code"] == pack
    assert c["DC_link"]["raw_code"] == link
    from decimal import Decimal

    assert c["Battery_Current"]["candidate_value_decimal"] == str(
        Decimal(current) / 10 - Decimal("819.2")
    )
    assert c["Battery_Volts"]["candidate_value_decimal"] == str(Decimal(pack) * Decimal("0.1"))
    assert c["DC_link"]["candidate_value_decimal"] == str(link * 4)
    assert c["Battery_Current"]["outside_dbc_declared_range"] == (current < 8192 or current > 16384)
    assert c["Battery_Volts"]["outside_dbc_declared_range"] == (pack > 8190)
    assert c["DC_link"]["outside_dbc_declared_range"] == (link > 205)
    assert [c[n]["all_ones_code"] for n in ("Battery_Current", "Battery_Volts", "DC_link")] == [
        current == 65535,
        pack == 65535,
        link == 255,
    ]
    assert all(v["physical_validity"] == "unknown" for v in c.values())
    assert row["acquisition_time_s"] is None and row["sensor_age_s"] is None


@pytest.mark.parametrize("code,label", [(0, "OPEN"), (1, "PRECHRG"), (2, "CLOSED"), (3, "SNA")])
def test_state_is_a_separate_report_never_assigned_to_analog(code, label):
    raw = representations(
        [
            (10, 0x1FA, (code << 12).to_bytes(8, "little")),
            (10, 0x112, electrical(8191, 3905, 97)),
            (11, 0x112, electrical(8192, 3905, 97)),
        ]
    )
    result = trace._trace_records(*raw)
    state, first, last = result["frames"]
    assert state["candidates"]["ST_DCSW_HVSTO"]["candidate_label"] == label
    assert "ST_DCSW_HVSTO" not in first["candidates"]
    assert "ST_DCSW_HVSTO" not in last["candidates"]
    assert first["delta_from_previous_same_frame_ticks"] is None
    assert last["delta_from_previous_same_frame_ticks"] == 1
    assert "precharge_active" not in json.dumps(result)


def test_ordinal_indices_physical_multiline_records_and_opaque_metadata():
    raw = representations([(9, 0x222, bytes(8)), (9, 0x112, electrical(8192, 3905, 0))])
    result = trace._trace_records(*raw)
    row = result["frames"][0]
    assert row["source_record_index"] == 1
    assert row["csv_physical_lines"] == [3, 3]
    assert row["log_physical_lines"] == [4, 5]
    assert row["original_metadata"]["Counter"] == "1"
    assert row["original_metadata"]["Flags"] == "E"
    assert row["original_metadata"]["default"] == "opaque\nextra"
    assert row["csv_metadata"]["Bus"] == "1" and row["original_metadata"]["Ch"] == "0"
    assert result["records_inspected"] == 2


def test_malformed_csv_id_is_retained_without_repair_original_identifies_candidate():
    raw = representations([(7, 0x112, electrical(8192, 3905, 0))], malformed=True)
    result = trace._trace_records(*raw)
    row = result["frames"][0]
    assert row["csv_metadata"]["ID"] == "1.12E+2"
    assert row["original_id_token"] == "112"
    assert row["csv_id_parseable"] is False
    assert result["malformed_csv_id_tokens_not_repaired"] == 1


def test_duplicate_backward_large_and_integer_exact_timestamps_remain_in_source_order():
    ticks = [2**60, 2**60, 2**60 - 1, 2**60 + 42949671]
    raw = representations([(tick, 0x112, electrical(8192, 3905, 0)) for tick in ticks])
    result = trace._trace_records(*raw)
    assert [r["raw_ticks"] for r in result["frames"]] == ticks
    assert [r["delta_from_previous_same_frame_ticks"] for r in result["frames"]] == [
        None,
        0,
        -1,
        42949672,
    ]
    assert result["clock_observations"]["duplicate_adjacent_raw_ticks"] == 1
    assert result["clock_observations"]["backward_steps"] == 1
    assert result["clock_observations"]["largest_adjacent_delta"]["delta_ticks"] == 42949672


def mutate_record(raw: bytes, delimiter: str, column: int, value: str) -> bytes:
    rows = list(csv.reader(io.StringIO(raw.decode(), newline=""), delimiter=delimiter))
    rows[-1][column] = value
    stream = io.StringIO(newline="")
    csv.writer(stream, delimiter=delimiter).writerows(rows)
    return stream.getvalue().encode()


@pytest.mark.parametrize(
    "column,value", [(0, "11"), (1, "113"), (2, "1"), (3, "2"), (4, "7"), (5, "FF")]
)
def test_representation_mismatch_or_selected_metadata_rejects(column, value):
    c, o = representations([(10, 0x112, electrical(8192, 3905, 0))])
    with pytest.raises(ValueError):
        trace._trace_records(mutate_record(c, ",", column, value), o)


@pytest.mark.parametrize(
    "change", ["csv_header", "log_header", "csv_extra", "log_extra", "missing_record"]
)
def test_malformed_structure_rejects(change):
    c, o = representations([(10, 0x112, electrical(8192, 3905, 0))])
    if change == "csv_header":
        c = c.replace(b"Time Stamp", b"Time", 1)
    elif change == "log_header":
        o = o.replace(b"ParserFlags", b"Flags", 1)
    elif change == "csv_extra":
        c = c.replace(b"\r\n", b",extra\r\n", 2)
    elif change == "log_extra":
        o = o.replace(b"\tDefaultParser\t", b"\tDefaultParser\textra\t", 1)
    else:
        c = c.split(b"\r\n", 1)[0] + b"\r\n"
    with pytest.raises(ValueError):
        trace._trace_records(c, o)


def authored_pins(monkeypatch, tmp_path):
    c, o = representations(
        [(10, 0x1FA, (3 << 12).to_bytes(8, "little")), (10, 0x112, electrical(65535, 65535, 255))]
    )
    paths = {}
    pins = {}
    for kind, data in (("csv", c), ("log", o)):
        paths[kind] = tmp_path / kind
        paths[kind].write_bytes(data)
        pins[kind] = (
            len(data),
            hashlib.sha256(data).hexdigest(),
            hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        )
    dbc = b" " * 64000
    paths["dbc"] = tmp_path / "fixture.dbc"
    paths["dbc"].write_bytes(dbc)
    monkeypatch.setattr(clock, "PINS", pins)
    monkeypatch.setattr(trace, "DBC_SHA256", hashlib.sha256(dbc).hexdigest())
    return paths


def test_public_trace_strict_json_and_no_acceptance_override(monkeypatch, tmp_path):
    paths = authored_pins(monkeypatch, tmp_path)
    before = {k: p.read_bytes() for k, p in paths.items()}
    r = trace.build_raw_source_trace(paths["csv"], paths["log"], paths["dbc"])
    assert r["format"] == "batterylog-bmw-raw-source-trace-v1"
    assert r["curve_review_eligible"] is False and r["aligned_rows_created"] is False
    assert r["tick_unit"] is None and r["seconds_per_tick"] is None
    assert len(r["physical_preparation_blockers"]) == 7
    text = json.dumps(r, allow_nan=False)
    assert "timestamp_s" not in text and "precharge_active" not in text
    assert json.loads(text) == r
    assert {k: p.read_bytes() for k, p in paths.items()} == before


@pytest.mark.parametrize("kind", ["csv", "log", "dbc"])
@pytest.mark.parametrize("change", ["same_size", "append"])
def test_every_mutated_input_rejected_before_parsing(monkeypatch, tmp_path, kind, change):
    paths = authored_pins(monkeypatch, tmp_path)
    raw = paths[kind].read_bytes()
    paths[kind].write_bytes((b"X" + raw[1:]) if change == "same_size" else raw + b"X")
    monkeypatch.setattr(trace, "_trace_records", lambda *_: pytest.fail("Unpinned bytes parsed"))
    with pytest.raises(ValueError, match="pinned"):
        trace.build_raw_source_trace(paths["csv"], paths["log"], paths["dbc"])


def test_pinned_reader_caps_wrong_input_before_hashing(monkeypatch, tmp_path):
    paths = authored_pins(monkeypatch, tmp_path)
    size = clock.PINS["csv"][0]
    paths["csv"].write_bytes(b"X" * (size * 20))
    original_open = Path.open
    reads = []

    class LimitedRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, n=-1):
            reads.append(n)
            assert n == size + 1, "Unbounded source read"
            return self.stream.read(n)

    def checked_open(path, *args, **kwargs):
        opened = original_open(path, *args, **kwargs)
        return LimitedRead(opened) if path == paths["csv"] else opened

    monkeypatch.setattr(Path, "open", checked_open)
    with pytest.raises(ValueError, match="pinned"):
        clock.pinned_bytes(paths["csv"], "csv")
    assert reads == [size + 1]


def test_decimal_candidates_do_not_depend_on_caller_precision():
    from decimal import localcontext

    raw = representations([(10, 0x112, electrical(8191, 3905, 97))])
    with localcontext() as context:
        context.prec = 2
        row = trace._trace_records(*raw)["frames"][0]
    assert row["candidates"]["Battery_Current"]["candidate_value_decimal"] == "-0.1"
    assert row["candidates"]["Battery_Volts"]["candidate_value_decimal"] == "390.5"


@pytest.mark.parametrize("token", ["0x00000112", "00000112", "112"])
def test_original_hex_token_with_optional_prefix_is_preserved(token):
    c, o = representations([(10, 0x112, electrical(8192, 3905, 0))])
    o = mutate_record(o, "\t", 6, token)
    row = trace._trace_records(c, o)["frames"][0]
    assert row["original_id_token"] == token
    assert row["candidate_frame_id"] == 0x112
