"""CAN preparation contracts on authored synthetic frames, not physical fault labels."""

import copy
import csv
import io
import json
import random
from decimal import Decimal, localcontext

import pandas as pd
import pytest

cantools = pytest.importorskip("cantools")

from batterylog_research.can_prepare import (
    compile_profile,
    prepare_paths,
    prepare_stream,
    read_frames,
    sha256,
)

DBC = """VERSION ""
NS_ :
BS_:
BU_: Test
BO_ 256 Brick: 8 Test
 SG_ Mux M : 0|8@1+ (1,0) [0|1] "" Test
 SG_ V0 m0 : 8|16@1+ (0.001,0) [0|65.535] "V" Test
 SG_ V1 m0 : 24|16@1+ (0.001,0) [0|65.535] "V" Test
 SG_ Other m1 : 8|16@1+ (0.001,0) [0|65.535] "V" Test
BO_ 512 Context: 4 Test
 SG_ T : 0|8@1+ (1,-40) [-40|215] "C" Test
 SG_ I : 8|16@1- (0.1,0) [-3276.8|3276.7] "A" Test
"""


@pytest.fixture
def setup():
    database = cantools.database.load_string(DBC, database_format="dbc", strict=True)
    profile = {
        "bus": "can0",
        "dbc_sha256": "a" * 64,
        "anchor": {
            "frame_id": 0x100,
            "extended": False,
            "multiplexer_signal": "Mux",
            "multiplexer_value": 0,
        },
        "signals": [
            {
                "column": "cell_1_v",
                "frame_id": 0x100,
                "extended": False,
                "signal": "V0",
                "max_age_s": 0,
            },
            {
                "column": "cell_2_v",
                "frame_id": 0x100,
                "extended": False,
                "signal": "V1",
                "max_age_s": 0,
            },
            {
                "column": "temp_1_c",
                "frame_id": 0x200,
                "extended": False,
                "signal": "T",
                "max_age_s": 1,
            },
            {
                "column": "pack_current_a",
                "frame_id": 0x200,
                "extended": False,
                "signal": "I",
                "max_age_s": 1,
            },
        ],
    }
    return database, profile


def anchor(t="1", payload="00AC0DDE0D000000", identifier="100", bus="can0"):
    # 0x0DAC=3500 mV; 0x0DDE=3550 mV, authored without an encoder oracle.
    return f"({t}) {bus} {identifier}#{payload}\n"


def context(t="0", payload="3CF6FF00"):
    # T:60-40=20 C; I:signed(-10)*0.1=-1 A.
    return f"({t}) can0 200#{payload}\n"


def run(setup, source):
    csv, evidence = io.StringIO(), io.StringIO()
    report = prepare_stream(io.StringIO(source), *setup, csv, evidence)
    return (
        pd.read_csv(io.StringIO(csv.getvalue())),
        [json.loads(s) for s in evidence.getvalue().splitlines()],
        report,
    )


def test_signed_scaling_exact_age_boundary_and_expiry(setup):
    frame, trace, report = run(
        setup,
        context("1000000000.000000001")
        + anchor("1000000001.000000001")
        + anchor("1000000001.000000002"),
    )
    assert frame["cell_1_v"].tolist() == [3.5, 3.5]
    assert frame["cell_2_v"].tolist() == pytest.approx([3.55, 3.55], rel=0, abs=1e-12)
    assert frame.loc[0, "temp_1_c"] == 20
    assert frame.loc[0, "pack_current_a"] == -1
    assert frame.loc[1, ["temp_1_c", "pack_current_a"]].isna().all()
    assert trace[0]["measurements"]["temp_1_c"]["age_s"] == 1
    assert trace[1]["measurements"]["temp_1_c"]["age_s"] == 1.000000001
    assert report["missing_or_expired_values_by_column"] == {"temp_1_c": 1, "pack_current_a": 1}


def test_no_future_filling_and_duplicate_anchor_order_retained(setup):
    frame, trace, _ = run(setup, anchor("1") + context("1") + anchor("1"))
    assert frame["timestamp_s"].tolist() == [0, 0]
    assert pd.isna(frame.loc[0, "temp_1_c"])
    assert frame.loc[1, "temp_1_c"] == 20
    assert trace[0]["measurements"]["temp_1_c"]["source_line"] is None
    assert trace[1]["measurements"]["temp_1_c"]["source_line"] == 2


def test_unknown_ids_and_other_buses_do_not_update_selected_cache(setup):
    source = context() + "(0.5) can0 201#3CFFFF00\n" + anchor("0.8", bus="can1") + anchor("1")
    frame, _, report = run(setup, source)
    assert len(frame) == 1
    assert frame.loc[0, "pack_current_a"] == -1
    assert report["counts"]["frames_input"] == 4
    assert report["counts"]["other_bus_frames"] == 1
    assert report["counts"]["unselected_identifier_frames"] == 1


def test_standard_extended_id_collision_does_not_decode_wrong_frame(setup):
    frame, _, report = run(setup, context() + anchor("0.5", identifier="00000100") + anchor("1"))
    assert len(frame) == 1
    assert report["counts"]["unselected_identifier_frames"] == 1
    assert report["frames_by_identifier"]["extended:0x100"] == 1


def test_other_multiplex_group_cannot_replace_selected_bricks(setup):
    frame, trace, report = run(
        setup, context() + anchor("0.1", payload="01A00F0000000000") + anchor("1")
    )
    assert len(frame) == 1
    assert frame.loc[0, "cell_1_v"] == 3.5
    assert trace[0]["measurements"]["cell_1_v"]["source_line"] == 3
    assert report["counts"]["unselected_anchor_multiplex_frames"] == 1


@pytest.mark.parametrize(
    "record",
    [
        "(1) can0 100##100\n",  # CAN FD intentionally outside this prototype.
        "(1) can0 100#R8\n",  # Remote-request frames are not measurements.
        "(1) can0 100#ABC\n",
        "(nan) can0 100#00\n",
        "(-1) can0 100#00\n",
        "(1) can0 800#00\n",
        "(1) can0 20000000#00\n",
        "(1) can0 0100#00\n",
        "\n",
        "(1) can0 100#000000000000000000\n",
    ],
)
def test_unsupported_or_malformed_frames_are_rejected(record):
    with pytest.raises(ValueError, match="source line 1"):
        list(read_frames(io.StringIO(record)))


def test_decreasing_time_rejected_even_on_an_unselected_id(setup):
    with pytest.raises(ValueError, match="timestamp decreases at source line 2"):
        run(setup, anchor("2") + "(1) can0 777#00\n")


@pytest.mark.parametrize("payload", ["00", "FFAC0DDE0D000000"])
def test_truncated_payload_and_unknown_mux_fail_with_line_evidence(setup, payload):
    with pytest.raises(ValueError, match="DBC decode failed at source line 2"):
        run(setup, context() + anchor("1", payload=payload))


@pytest.mark.parametrize(
    "change",
    [
        "unit",
        "missing_signal",
        "wrong_mux",
        "cell_age",
        "duplicate_column",
        "duplicate_source",
        "negative_age",
        "bool_age",
        "unknown_key",
        "missing_temperature",
        "extended_mismatch",
    ],
)
def test_profile_incompatibilities_rejected(setup, change):
    db, p = setup
    p = copy.deepcopy(p)
    if change == "unit":
        db.get_message_by_frame_id(0x100).get_signal_by_name("V0").unit = "mV"
    elif change == "missing_signal":
        p["signals"][0]["signal"] = "Absent"
    elif change == "wrong_mux":
        p["anchor"]["multiplexer_value"] = 1
    elif change == "cell_age":
        p["signals"][0]["max_age_s"] = 1
    elif change == "duplicate_column":
        p["signals"][1]["column"] = "cell_1_v"
    elif change == "duplicate_source":
        p["signals"][1]["signal"] = "V0"
    elif change == "negative_age":
        p["signals"][2]["max_age_s"] = -1
    elif change == "bool_age":
        p["signals"][2]["max_age_s"] = True
    elif change == "unknown_key":
        p["guessed_setting"] = True
    elif change == "missing_temperature":
        p["signals"].pop(2)
    elif change == "extended_mismatch":
        p["signals"][0]["extended"] = True
    with pytest.raises((ValueError, KeyError)):
        compile_profile(db, p)


def test_absolute_timestamp_decimal_precision_preserved():
    frames = list(
        read_frames(io.StringIO(anchor("1674587734.000000001") + anchor("1674587734.000000002")))
    )
    assert frames[1].timestamp - frames[0].timestamp == Decimal("0.000000001")


def test_path_failure_does_not_publish_partial_preparation(tmp_path, setup):
    _, p = setup
    log, dbc, profile = (tmp_path / n for n in ["input.log", "input.dbc", "profile.json"])
    log.write_text(context() + anchor("1", payload="00"))
    dbc.write_text(DBC)
    p["dbc_sha256"] = sha256(dbc)
    profile.write_text(json.dumps(p))
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="DBC decode failed"):
        prepare_paths(log, dbc, profile, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".can-prepare-*"))


def test_wrong_dbc_hash_rejected_before_decode(tmp_path, setup):
    _, p = setup
    log, dbc, profile = (tmp_path / n for n in ["input.log", "input.dbc", "profile.json"])
    log.write_text(context() + anchor())
    dbc.write_text(DBC)
    profile.write_text(json.dumps(p))
    with pytest.raises(ValueError, match="DBC SHA-256"):
        prepare_paths(log, dbc, profile, tmp_path / "out")


@pytest.mark.parametrize("conversion", ["(1,1)", "(2,0)", "(0.5,0)"])
def test_scaled_selector_cannot_select_a_different_raw_brick_group(setup, conversion):
    _, profile = setup
    profile = copy.deepcopy(profile)
    profile["anchor"]["multiplexer_value"] = 1
    profile["signals"][0]["signal"] = "Other"
    profile["signals"].pop(1)
    db = cantools.database.load_string(
        DBC.replace("Mux M : 0|8@1+ (1,0)", f"Mux M : 0|8@1+ {conversion}"),
        database_format="dbc",
        strict=True,
    )
    with pytest.raises(ValueError, match="raw unsigned integer multiplexer"):
        run((db, profile), context() + anchor())


def test_signed_selector_is_outside_preparation_contract(setup):
    _, profile = setup
    db = cantools.database.load_string(
        DBC.replace("Mux M : 0|8@1+", "Mux M : 0|8@1-"),
        database_format="dbc",
        strict=True,
    )
    with pytest.raises(ValueError, match="raw unsigned integer multiplexer"):
        compile_profile(db, profile)


def test_distinct_anchor_times_cannot_collapse_to_one_float_csv_timestamp(setup):
    with pytest.raises(ValueError, match="timestamp precision.*source line 3"):
        run(
            setup,
            context("0")
            + anchor("999999999999999999.000000001")
            + anchor("999999999999999999.000000002"),
        )


@pytest.mark.parametrize("nested", [False, True])
def test_conflicting_duplicate_profile_keys_rejected_without_output(tmp_path, setup, nested):
    _, profile = setup
    log, dbc, p = [tmp_path / name for name in ("a.log", "a.dbc", "p.json")]
    log.write_text(context() + anchor())
    dbc.write_text(DBC)
    profile["dbc_sha256"] = sha256(dbc)
    text = json.dumps(profile)
    if nested:
        text = text.replace('"max_age_s": 1', '"max_age_s": 0, "max_age_s": 1')
    else:
        text = text.replace('"bus": "can0"', '"bus": "can1", "bus": "can0"')
    p.write_text(text)
    with pytest.raises(ValueError, match="Duplicate CAN profile key"):
        prepare_paths(log, dbc, p, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_profile_numbers_rejected_before_decode(tmp_path, setup, value):
    _, profile = setup
    log, dbc, p = [tmp_path / name for name in ("a.log", "a.dbc", "p.json")]
    log.write_text(context() + anchor())
    dbc.write_text(DBC)
    profile["dbc_sha256"] = sha256(dbc)
    p.write_text(json.dumps(profile).replace('"max_age_s": 1', f'"max_age_s": {value}'))
    with pytest.raises(ValueError, match="Nonstandard CAN profile number"):
        prepare_paths(log, dbc, p, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("seed", range(24))
@pytest.mark.parametrize("raw_policy", [False, True])
def test_generated_alignment_matches_offline_byte_and_source_order_oracle(setup, seed, raw_policy):
    """Brute-force earlier-record search, independent of the implementation cache."""
    rng = random.Random(seed)
    db, profile = setup
    age = rng.choice([0, 0.000000001, 0.1, 1, 2])
    for signal in profile["signals"][2:]:
        signal["max_age_s"] = age
    if raw_policy:
        profile["signals"][2]["invalid_raw_values"] = [0, 60, 255]
        profile["signals"][3]["invalid_raw_values"] = [-32768, 0, 32767]
    timestamp = Decimal("1674587734.000000001")
    records = []
    for _ in range(160):
        timestamp += Decimal(rng.choice(["0", "0.000000001", "0.1", "0.9", "2"]))
        kind = rng.choice(["context", "anchor", "other_mux", "other_bus", "extended"])
        if kind == "context":
            payload = bytes([rng.randrange(256)]) + rng.randrange(65536).to_bytes(2, "little")
            payload += b"\x00"
            bus, identifier = "can0", "200"
        else:
            payload = bytes([int(kind == "other_mux")])
            payload += rng.randrange(65536).to_bytes(2, "little")
            payload += rng.randrange(65536).to_bytes(2, "little") + b"\x00" * 3
            bus = "can1" if kind == "other_bus" else "can0"
            identifier = "00000100" if kind == "extended" else "100"
        records.append(
            (timestamp, kind, payload, f"({timestamp}) {bus} {identifier}#{payload.hex()}\n")
        )
    output, trace = io.StringIO(), io.StringIO()
    report = prepare_stream(io.StringIO("".join(r[3] for r in records)), db, profile, output, trace)
    actual = list(csv.reader(io.StringIO(output.getvalue())))[1:]
    evidence = [json.loads(row) for row in trace.getvalue().splitlines()]
    expected = []
    for index, (time, kind, payload, _) in enumerate(records):
        if kind != "anchor":
            continue
        earlier = [i for i in range(index) if records[i][1] == "context"]
        context_index = earlier[-1] if earlier else None
        usable = context_index is not None and time - records[context_index][0] <= Decimal(str(age))
        row = [
            float(time - records[0][0]),
            int.from_bytes(payload[1:3], "little") / 1000,
            int.from_bytes(payload[3:5], "little") / 1000,
        ]
        if usable:
            raw = records[context_index][2]
            current = int.from_bytes(raw[1:3], "little", signed=True)
            row += [
                None if raw_policy and raw[0] in (0, 60, 255) else raw[0] - 40,
                None if raw_policy and current in (-32768, 0, 32767) else current / 10,
            ]
        else:
            row += [None, None]
        expected.append((index, context_index, row))
    assert len(actual) == len(expected) == report["counts"]["anchor_rows"]
    assert report["counts"]["frames_input"] == len(records)
    for result, proof, (index, context_index, reference) in zip(
        actual, evidence, expected, strict=True
    ):
        assert proof["anchor_source_line"] == index + 1
        assert proof["measurements"]["cell_1_v"]["source_line"] == index + 1
        assert proof["measurements"]["temp_1_c"]["source_line"] == (
            context_index + 1 if context_index is not None else None
        )
        for value, want in zip(result, reference, strict=True):
            if want is None:
                assert value == ""
            else:
                assert float(value) == pytest.approx(want, rel=0, abs=1e-12)


def test_age_integer_overflow_is_a_profile_error(setup):
    db, profile = setup
    profile["signals"][2]["max_age_s"] = 10**400
    with pytest.raises(ValueError, match="finite non-negative"):
        compile_profile(db, profile)


def test_caller_decimal_context_cannot_round_an_expired_sample_into_usable(setup):
    with localcontext() as caller:
        caller.prec = 8
        caller.Emax = 1
        _, evidence, _ = run(
            setup,
            context("1674587734.000000001") + anchor("1674587735.000000002"),
        )
        assert caller.prec == 8 and caller.Emax == 1
    entry = evidence[0]["measurements"]["temp_1_c"]
    assert entry["age_s"] == 1.000000001
    assert not entry["usable"]


def test_two_dbc_messages_with_the_same_numeric_id_keep_explicit_frame_identity(setup):
    _, profile = setup
    extended = (
        DBC[DBC.index("BO_ 512") :]
        .replace("BO_ 512 Context:", "BO_ 2147484160 ExtendedContext:")
        .replace(" SG_ T ", " SG_ ET ")
        .replace(" SG_ I ", " SG_ EI ")
    )
    db = cantools.database.load_string(DBC + extended, database_format="dbc", strict=True)
    for signal, name in zip(profile["signals"][2:], ("ET", "EI"), strict=True):
        signal["extended"], signal["signal"] = True, name
    frame, evidence, _ = run(
        (db, profile),
        "(0) can0 00000200#3CF6FF00\n" + context("0.5", payload="46E80300") + anchor(),
    )
    assert frame.loc[0, "temp_1_c"] == 20
    assert frame.loc[0, "pack_current_a"] == -1
    assert evidence[0]["measurements"]["temp_1_c"]["source_line"] == 1


def test_raw_all_ones_is_not_automatically_treated_as_invalid(setup):
    frame, evidence, report = run(setup, context(payload="FFF6FF00") + anchor())
    assert frame.loc[0, "temp_1_c"] == 215
    assert "raw_value" not in evidence[0]["measurements"]["temp_1_c"]
    assert "declared_invalid_raw_values_observed_by_column" not in report


def test_declared_invalid_context_replaces_old_valid_value_and_keeps_source_identity(setup):
    db, profile = setup
    profile["signals"][2]["invalid_raw_values"] = [255]
    profile["signals"][3]["invalid_raw_values"] = [-32768]
    frame, evidence, report = run(
        (db, profile),
        context("0")
        + anchor("0.1")
        + context("0.2", payload="FF008000")
        + anchor("0.3")
        + context("0.4", payload="28000000")
        + anchor("0.5"),
    )
    assert frame["temp_1_c"].tolist()[::2] == [20, 0]
    assert frame["pack_current_a"].tolist()[::2] == [-1, 0]
    assert frame.loc[1, ["temp_1_c", "pack_current_a"]].isna().all()
    rejected = evidence[1]["measurements"]["temp_1_c"]
    assert rejected["source_line"] == 3
    assert rejected["source_timestamp"] == "0.2"
    assert rejected["raw_value"] == 255
    assert rejected["raw_value_rejected"] is True
    assert rejected["usable"] is False
    assert evidence[2]["measurements"]["temp_1_c"]["raw_value_rejected"] is False
    assert report["declared_invalid_raw_values_observed_by_column"] == {
        "temp_1_c": 1,
        "pack_current_a": 1,
    }


def test_declared_invalid_brick_cannot_be_replaced_from_a_previous_anchor(setup):
    db, profile = setup
    profile["signals"][0]["invalid_raw_values"] = [65535]
    frame, evidence, report = run(
        (db, profile),
        context() + anchor("0.1") + anchor("0.2", payload="00FFFFDE0D000000"),
    )
    assert frame.loc[0, "cell_1_v"] == 3.5
    assert pd.isna(frame.loc[1, "cell_1_v"])
    assert frame.loc[1, "cell_2_v"] == pytest.approx(3.55, rel=0, abs=1e-12)
    assert evidence[1]["measurements"]["cell_1_v"]["source_line"] == 3
    assert evidence[1]["measurements"]["cell_1_v"]["raw_value"] == 65535
    assert report["missing_or_expired_values_by_column"] == {"cell_1_v": 1}


def test_wrong_bus_invalid_context_cannot_clear_the_selected_valid_context(setup):
    db, profile = setup
    profile["signals"][2]["invalid_raw_values"] = [255]
    frame, evidence, report = run(
        (db, profile),
        context() + context("0.5", payload="FFF6FF00").replace("can0", "can1") + anchor(),
    )
    assert frame.loc[0, "temp_1_c"] == 20
    assert evidence[0]["measurements"]["temp_1_c"]["source_line"] == 1
    assert report["declared_invalid_raw_values_observed_by_column"] == {}


@pytest.mark.parametrize("codes", [None, [], [True], [255.0], [256], [-1], [255, 255], "255"])
def test_invalid_raw_exclusion_policy_is_not_coerced(setup, codes):
    db, profile = setup
    profile["signals"][2]["invalid_raw_values"] = codes
    with pytest.raises((ValueError, TypeError), match="invalid_raw_values"):
        compile_profile(db, profile)


def test_signed_raw_exclusion_uses_signed_dbc_values_not_unsigned_bit_patterns(setup):
    db, profile = setup
    profile["signals"][3]["invalid_raw_values"] = [65535]
    with pytest.raises(ValueError, match="invalid_raw_values"):
        compile_profile(db, profile)


def test_raw_exclusion_is_not_supported_for_float_signals(setup):
    db, profile = setup
    db.get_message_by_frame_id(0x200).get_signal_by_name("T").is_float = True
    profile["signals"][2]["invalid_raw_values"] = [255]
    with pytest.raises(ValueError, match="invalid_raw_values"):
        compile_profile(db, profile)


@pytest.mark.parametrize("raw", [None, True, 255.0])
def test_raw_policy_does_not_accept_a_missing_or_wrong_type_decoder_value(setup, monkeypatch, raw):
    db, profile = setup
    profile["signals"][2]["invalid_raw_values"] = [255]
    message = db.get_message_by_frame_id(0x200)
    original = message.decode

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("scaling") is False:
            result["T"] = raw
        return result

    monkeypatch.setattr(message, "decode", changed)
    with pytest.raises(ValueError, match="raw integer decode at source line 1"):
        run((db, profile), context() + anchor())


@pytest.mark.parametrize("invalid_rows", [1, 3])
def test_declared_raw_rejection_reaches_native_strict_and_chunked_quality_contract(
    tmp_path, setup, invalid_rows
):
    from batterylog import DataQualityConfig, ValidationLimits, validate_result_semantics
    from batterylog.analysis.core import _analyze_battery_frame
    from batterylog.analysis.streaming import analyze_measurement_loader
    from batterylog.loaders.csv import CsvPathLoader

    _, profile = setup
    profile["signals"][2]["invalid_raw_values"] = [255]
    log, dbc, p, destination = [tmp_path / name for name in ("a.log", "a.dbc", "p.json", "out")]
    valid_context = "FFF6FF00" if invalid_rows == 3 else "3CF6FF00"
    log.write_text(
        context("0", payload=valid_context)
        + anchor("0.1")
        + context("0.2", payload="FFF6FF00")
        + anchor("0.3")
        + context("0.4", payload=valid_context)
        + anchor("0.5")
    )
    dbc.write_text(DBC)
    profile["dbc_sha256"] = sha256(dbc)
    p.write_text(json.dumps(profile))
    report = prepare_paths(log, dbc, p, destination)
    assert report["declared_invalid_raw_values_observed_by_column"] == {"temp_1_c": invalid_rows}
    canonical = destination / "canonical.csv"
    limits = ValidationLimits(
        cell_min_v=2.5, cell_max_v=4.2, imbalance_max_v=0.1, temperature_max_c=55
    )
    quality = DataQualityConfig("exclude_invalid_rows")
    full = _analyze_battery_frame(pd.read_csv(canonical), limits=limits, data_quality=quality)
    validate_result_semantics(full)
    assert (full["rows_input"], full["rows_analyzed"], full["rows_excluded"]) == (
        3,
        3 - invalid_rows,
        invalid_rows,
    )
    assert full["validation_status"] == "FAIL"
    assert not full["violations"]
    for chunk in (1, 2, 65536):
        loader = CsvPathLoader(canonical, chunk_rows=chunk)
        result = analyze_measurement_loader(loader, limits=limits, data_quality=quality)
        validate_result_semantics(result)
        assert json.dumps(result, sort_keys=True) == json.dumps(full, sort_keys=True)
        first_invalid = 1 if invalid_rows == 3 else 2
        with pytest.raises(ValueError, match=f"data row {first_invalid}.*temp_1_c"):
            analyze_measurement_loader(loader, limits=limits)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("profile", "bus", ""),
        ("profile", "dbc_sha256", "A" * 64),
        ("anchor", "frame_id", True),
        ("anchor", "frame_id", 0x800),
        ("anchor", "extended", 1),
        ("anchor", "multiplexer_signal", "V0"),
        ("anchor", "multiplexer_value", True),
        ("anchor", "multiplexer_value", 256),
        ("anchor", "multiplexer_signal", None),
        ("signal", "column", 1),
        ("signal", "column", "voltage_guess"),
        ("signal", "frame_id", -1),
        ("signal", "frame_id", 0x800),
        ("signal", "extended", 0),
        ("signal", "signal", 1),
        ("signal", "signal", "Mux"),
        ("signal", "max_age_s", float("inf")),
        ("signal", "max_age_s", "0"),
    ],
)
def test_fault_injected_profile_is_rejected_before_any_stream_output(setup, target, field, value):
    db, profile = setup
    destination = {
        "profile": profile,
        "anchor": profile["anchor"],
        "signal": profile["signals"][0],
    }[target]
    destination[field] = value
    output, trace = io.StringIO(), io.StringIO()
    with pytest.raises((ValueError, TypeError, KeyError)):
        prepare_stream(io.StringIO(context() + anchor()), db, profile, output, trace)
    assert output.getvalue() == trace.getvalue() == ""


@pytest.mark.parametrize("value", [None, True, "20", float("nan"), float("inf"), -float("inf")])
def test_decoder_fault_does_not_publish_a_partially_prepared_directory(
    tmp_path, setup, monkeypatch, value
):
    db, profile = setup
    import batterylog_research.can_prepare as module

    original = db.get_message_by_frame_id(0x200).decode

    def corrupted(*args, **kwargs):
        result = original(*args, **kwargs)
        result["T"] = value
        return result

    monkeypatch.setattr(db.get_message_by_frame_id(0x200), "decode", corrupted)
    monkeypatch.setattr(cantools.database, "load_file", lambda *args, **kwargs: db)
    log, dbc, spec = [tmp_path / name for name in ("a.log", "a.dbc", "p.json")]
    log.write_text(context() + anchor(), encoding="utf-8")
    dbc.write_text(DBC, encoding="utf-8")
    profile["dbc_sha256"] = module.sha256(dbc)
    spec.write_text(json.dumps(profile), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in (log, dbc, spec)}
    with pytest.raises(ValueError, match="Non-finite/non-numeric decoded value at source line 1"):
        prepare_paths(log, dbc, spec, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".can-prepare-*"))
    assert before == {p.name: p.read_bytes() for p in (log, dbc, spec)}


@pytest.mark.parametrize("changed_source", ["a.log", "a.dbc", "p.json"])
def test_changed_input_snapshot_is_rejected_before_publication(
    tmp_path, setup, monkeypatch, changed_source
):
    import batterylog_research.can_prepare as module

    _, profile = setup
    log, dbc, spec = [tmp_path / name for name in ("a.log", "a.dbc", "p.json")]
    log.write_text(context() + anchor(), encoding="utf-8")
    dbc.write_text(DBC, encoding="utf-8")
    profile["dbc_sha256"] = sha256(dbc)
    spec.write_text(json.dumps(profile), encoding="utf-8")
    original = module.prepare_stream

    def change_after_read(*args, **kwargs):
        report = original(*args, **kwargs)
        with (tmp_path / changed_source).open("ab") as stream:
            stream.write(b"\n")
        return report

    monkeypatch.setattr(module, "prepare_stream", change_after_read)
    with pytest.raises(ValueError, match="changed during preparation"):
        prepare_paths(log, dbc, spec, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".can-prepare-*"))
