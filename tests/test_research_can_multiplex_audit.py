"""Authored multiplex timing cases; observations are never physical fault labels."""

import copy
import io
import json
import random
from decimal import Decimal, localcontext

import pytest

from batterylog_research.can_multiplex_audit import audit_paths, audit_stream, compile_audit
from batterylog_research.can_prepare import sha256

cantools = pytest.importorskip("cantools")

DBC = """VERSION ""
NS_ :
BS_:
BU_: Test
BO_ 1025 Groups: 2 Test
 SG_ Mux M : 0|8@1+ (1,0) [0|4] "" Test
 SG_ V0 m0 : 8|8@1+ (0.1,0) [0|25.5] "V" Test
 SG_ V1 m1 : 8|8@1+ (0.1,0) [0|25.5] "V" Test
 SG_ V2 m2 : 8|8@1+ (0.1,0) [0|25.5] "V" Test
 SG_ V3 m3 : 8|8@1+ (0.1,0) [0|25.5] "V" Test
 SG_ V4 m4 : 8|8@1+ (0.1,0) [0|25.5] "V" Test
"""


@pytest.fixture
def setup():
    return cantools.database.load_string(DBC, database_format="dbc", strict=True), {
        "bus": "can0",
        "dbc_sha256": "a" * 64,
        "frame_id": 0x401,
        "extended": False,
        "selector": "Mux",
        "required_groups": [0, 1, 2],
        "ignored_groups": [3],
        "max_frame_gap_s": 5,
        "max_sweep_span_s": 2,
        "freshness_budgets_s": [1, 2, 3],
    }


def line(t, group, value=35, bus="can0", identifier="401"):
    return f"({t}) {bus} {identifier}#{group:02X}{value:02X}\n"


def run(setup, records):
    return audit_stream(io.StringIO("".join(records)), *setup)


def test_complete_coverage_at_exact_span_and_age_boundary(setup):
    r = run(setup, [line(0, 0), line(1, 1), line(2, 2), line(3, 0)])
    assert r["complete_coverage_windows"] == 1
    assert r["complete_windows_within_span_bound"] == 1
    assert r["windows"][0]["observed_span_s"] == 2
    assert r["freshness_at_required_group_arrivals"]["1"]["all_groups_within_age"] == 0
    assert r["freshness_at_required_group_arrivals"]["2"]["all_groups_within_age"] == 2
    assert r["diagnostic_claim"] is False
    assert all(w["boundary_authenticated"] is False for w in r["windows"])


def test_nanosecond_past_boundary_is_not_rounded_to_complete_fresh_coverage(setup):
    r = run(
        setup,
        [
            line("1674587734.000000001", 0),
            line("1674587735.000000001", 1),
            line("1674587736.000000002", 2),
        ],
    )
    assert r["complete_coverage_windows"] == 1
    assert r["complete_windows_within_span_bound"] == 0
    assert r["freshness_at_required_group_arrivals"]["2"]["all_groups_within_age"] == 0
    assert r["windows"][0]["observed_span_s"] == 2.000000001


def test_cached_previous_groups_do_not_fill_head_or_tail_window_coverage(setup):
    r = run(setup, [line(0, 1), line(1, 2), line(2, 0), line(3, 1)])
    assert [w["missing_groups"] for w in r["windows"]] == [[0], [2]]
    assert r["windows"][0]["opened_by_start_group"] is False
    assert r["windows"][1]["closing_reason"] == "end_of_recording"
    assert r["complete_coverage_windows"] == 0
    # Receipt-age history exists, but no measurements or complete window are fabricated.
    assert r["freshness_at_required_group_arrivals"]["3"]["all_groups_seen"] == 2


def test_missing_group_in_closed_window_retains_identity_and_order_evidence(setup):
    r = run(setup, [line(0, 0), line(1, 2), line(2, 0)])
    assert r["windows"][0]["closing_reason"] == "next_start_group"
    assert r["windows"][0]["missing_groups"] == [1]
    assert r["examples"]["order_departures"] == [
        {
            "source_line": 2,
            "previous_group": 0,
            "expected_group": 1,
            "observed_group": 2,
        }
    ]


def test_same_time_identical_repeat_is_counted_without_deduplication(setup):
    r = run(setup, [line(0, 0), line(1, 1), line(1, 1), line(2, 2)])
    assert r["counts"]["required_group_frames"] == 4
    assert r["counts"]["duplicate_selected_timestamps"] == 1
    assert r["counts"]["adjacent_identical_payload_repeats"] == 1
    assert r["windows"][0]["duplicate_group_observations"] == {"1": 1}
    assert r["windows"][0]["coverage_complete"] is True


def test_changed_payload_repeat_does_not_claim_identical_retransmission(setup):
    r = run(setup, [line(0, 0), line(1, 1, value=35), line(1, 1, value=36), line(2, 2)])
    assert r["counts"]["adjacent_group_repeats"] == 1
    assert r["counts"].get("adjacent_identical_payload_repeats", 0) == 0
    assert r["examples"]["repeats"][0]["identical_payload"] is False


def test_start_group_repeat_is_an_explicit_unauthenticated_boundary(setup):
    r = run(setup, [line(0, 0), line(0, 0), line(1, 1), line(2, 2)])
    assert len(r["windows"]) == 2
    assert r["windows"][0]["missing_groups"] == [1, 2]
    assert r["windows"][1]["coverage_complete"] is True
    assert r["counts"]["adjacent_group_repeats"] == 1
    assert all(w["boundary_authenticated"] is False for w in r["windows"])


def test_reordering_can_preserve_coverage_but_still_has_order_departures(setup):
    r = run(setup, [line(0, 0), line(1, 2), line(2, 1), line(3, 0)])
    assert r["windows"][0]["coverage_complete"] is True
    assert r["counts"]["declared_order_departures"] == 3


def test_declared_ignored_group_is_counted_but_not_a_missing_required_group(setup):
    r = run(setup, [line(0, 0), line(1, 3), line(2, 1), line(3, 2)])
    assert r["counts"]["declared_ignored_group_frames"] == 1
    assert r["windows"][0]["missing_groups"] == []
    assert r["counts"].get("declared_order_departures", 0) == 0


def test_unconfigured_dbc_known_selector_is_observed_without_filling_coverage(setup):
    r = run(setup, [line(0, 0), line(1, 4), line(2, 1)])
    assert r["counts"]["unexpected_group_frames"] == 1
    assert r["examples"]["unexpected_groups"] == [{"source_line": 2, "group": 4}]
    assert r["windows"][0]["missing_groups"] == [2]


def test_large_selected_message_gap_clears_receipt_history(setup):
    r = run(setup, [line(0, 0), line(1, 1), line(2, 3), line(8, 2)])
    assert r["counts"]["selected_frame_gaps"] == 1
    assert r["windows"][0]["closing_reason"] == "selected_frame_gap"
    assert r["windows"][1]["opened_after_gap"] is True
    assert r["freshness_at_required_group_arrivals"]["3"]["all_groups_seen"] == 0


@pytest.mark.parametrize("time,expected_gaps", [("6", 0), ("6.000000001", 1)])
def test_selected_gap_boundary_is_exact(setup, time, expected_gaps):
    r = run(setup, [line(0, 0), line(1, 1), line(time, 2)])
    assert r["counts"].get("selected_frame_gaps", 0) == expected_gaps


def test_an_unselected_bus_or_extended_id_cannot_complete_a_group_window(setup):
    r = run(
        setup, [line(0, 0), line(1, 1, bus="can1"), line(2, 1, identifier="00000401"), line(3, 2)]
    )
    assert r["counts"]["other_transport_frames"] == 2
    assert r["windows"][0]["missing_groups"] == [1]


@pytest.mark.parametrize(
    "change",
    [
        "overlap",
        "duplicate_groups",
        "unknown_group",
        "invalid_selector",
        "zero_gap",
        "bool_span",
        "nan_budget",
        "duplicate_budget",
        "unknown_key",
    ],
)
def test_invalid_audit_profile_rejected(setup, change):
    db, profile = setup
    p = copy.deepcopy(profile)
    if change == "overlap":
        p["ignored_groups"] = [0]
    elif change == "duplicate_groups":
        p["required_groups"] = [0, 1, 1]
    elif change == "unknown_group":
        p["required_groups"] = [0, 5]
    elif change == "invalid_selector":
        p["selector"] = "V0"
    elif change == "zero_gap":
        p["max_frame_gap_s"] = 0
    elif change == "bool_span":
        p["max_sweep_span_s"] = True
    elif change == "nan_budget":
        p["freshness_budgets_s"] = [float("nan")]
    elif change == "duplicate_budget":
        p["freshness_budgets_s"] = [1, 1.0]
    elif change == "unknown_key":
        p["guess_counter"] = True
    with pytest.raises((ValueError, TypeError)):
        compile_audit(db, p)


def test_clock_regression_is_rejected_even_on_other_transport_frames(setup):
    with pytest.raises(ValueError, match="source line 2"):
        run(setup, [line(1, 0), "(0) can0 123#00\n"])


def test_unknown_dbc_selector_rejected_without_partial_file_publication(tmp_path, setup):
    _, profile = setup
    dbc, log, p, output = [tmp_path / n for n in ["a.dbc", "a.log", "p.json", "result.json"]]
    dbc.write_text(DBC)
    profile["dbc_sha256"] = sha256(dbc)
    p.write_text(json.dumps(profile))
    log.write_text(line(0, 0) + line(1, 255))
    with pytest.raises(ValueError, match="Multiplex decode failed at source line 2"):
        audit_paths(log, dbc, p, output)
    assert not output.exists()


def test_no_selected_groups_is_not_a_successful_audit(setup):
    with pytest.raises(ValueError, match="No required multiplex"):
        run(setup, [line(0, 3)])


def test_persisted_audit_has_platform_independent_line_endings(tmp_path, setup):
    _, profile = setup
    dbc, log, p, output = [tmp_path / name for name in ("a.dbc", "a.log", "p.json", "out.json")]
    dbc.write_text(DBC)
    log.write_text(line(0, 0) + line(1, 1) + line(2, 2))
    profile["dbc_sha256"] = sha256(dbc)
    p.write_text(json.dumps(profile))
    result = audit_paths(log, dbc, p, output)
    assert output.read_bytes() == (json.dumps(result, indent=2, allow_nan=False) + "\n").encode()


@pytest.mark.parametrize("conversion", ["(1,1)", "(2,0)", "(0.5,0)"])
def test_scaled_selector_cannot_relabel_raw_groups(setup, conversion):
    _, profile = setup
    db = cantools.database.load_string(
        DBC.replace("Mux M : 0|8@1+ (1,0)", f"Mux M : 0|8@1+ {conversion}"),
        database_format="dbc",
        strict=True,
    )
    with pytest.raises(ValueError, match="raw unsigned integer multiplexer"):
        run((db, profile), [line(0, 0), line(1, 1), line(2, 2)])


def test_conflicting_duplicate_audit_groups_rejected_before_publication(tmp_path, setup):
    _, profile = setup
    dbc, log, p = [tmp_path / name for name in ("a.dbc", "a.log", "p.json")]
    dbc.write_text(DBC)
    log.write_text(line(0, 0) + line(1, 1) + line(2, 2))
    profile["dbc_sha256"] = sha256(dbc)
    p.write_text(
        json.dumps(profile).replace(
            '"required_groups": [0, 1, 2]',
            '"required_groups": [0, 1, 2, 3], "required_groups": [0, 1, 2]',
        )
    )
    with pytest.raises(ValueError, match="Duplicate CAN profile key"):
        audit_paths(log, dbc, p, tmp_path / "out.json")
    assert not (tmp_path / "out.json").exists()


def test_concurrent_audit_creation_is_not_overwritten(tmp_path, setup, monkeypatch):
    from batterylog_research import can_multiplex_audit

    _, profile = setup
    dbc, log, p, output = [tmp_path / name for name in ("a.dbc", "a.log", "p.json", "out.json")]
    dbc.write_text(DBC)
    log.write_text(line(0, 0) + line(1, 1) + line(2, 2))
    profile["dbc_sha256"] = sha256(dbc)
    p.write_text(json.dumps(profile))
    original = can_multiplex_audit.sha256
    calls = 0

    def concurrent_creation(path):
        nonlocal calls
        calls += 1
        digest = original(path)
        if calls == 6:
            output.write_text("concurrent audit must survive")
        return digest

    monkeypatch.setattr(can_multiplex_audit, "sha256", concurrent_creation)
    with pytest.raises(FileExistsError):
        audit_paths(log, dbc, p, output)
    assert output.read_text() == "concurrent audit must survive"
    assert not list(tmp_path.glob(".can-audit-*"))


def test_caller_decimal_context_cannot_round_a_span_into_complete_fresh_coverage(setup):
    with localcontext() as caller:
        caller.prec = 8
        caller.Emax = 1
        result = run(
            setup,
            [
                line("1674587734.000000001", 0),
                line("1674587735.000000001", 1),
                line("1674587736.000000002", 2),
            ],
        )
        assert caller.prec == 8 and caller.Emax == 1
    assert result["windows"][0]["observed_span_s"] == 2.000000001
    assert result["complete_windows_within_span_bound"] == 0
    assert result["freshness_at_required_group_arrivals"]["2"]["all_groups_within_age"] == 0


@pytest.mark.parametrize("seed", range(24))
def test_generated_windows_match_offline_partitions_and_receipt_search(setup, seed):
    from batterylog_research.can_multiplex_validation import compare_reference

    db, profile = setup
    rng = random.Random(seed)
    rng.shuffle(profile["required_groups"])
    profile["max_frame_gap_s"] = rng.choice([0.5, 1, 5])
    profile["max_sweep_span_s"] = rng.choice([1, 2, 10])
    timestamp = Decimal("1674587734.000000001")
    records = [line(timestamp, profile["required_groups"][0])]
    for _ in range(320):
        timestamp += Decimal(rng.choice(["0", "0.000000001", "0.5", "1", "6"]))
        bus, cid = rng.choice(
            [
                ("can0", "401"),
                ("can0", "401"),
                ("can1", "401"),
                ("can0", "00000401"),
                ("can0", "777"),
            ]
        )
        records.append(
            line(timestamp, rng.randrange(5), rng.randrange(256), bus=bus, identifier=cid)
        )
    result = audit_stream(io.StringIO("".join(records)), db, profile)
    assert compare_reference(result, records, profile) == len(result["windows"])
