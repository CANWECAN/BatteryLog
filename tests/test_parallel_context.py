import copy
import json
from dataclasses import FrozenInstanceError
from io import BytesIO

import pytest
from hypothesis import given
from hypothesis import strategies as st

from batterylog import ValidationLimits
from batterylog.analysis.core import analyze_battery_bytes
from batterylog.analysis.streaming import analyze_measurement_loader
from batterylog.loaders import CsvFileLoader
from batterylog.measurement_context import (
    DeclaredChannel,
    DeclaredTopology,
    MeasurementContext,
)
from batterylog.parallel_context import ParallelBranchAssessment
from batterylog.reporting import render_json_result


def _context(branches=("a", "b")):
    return MeasurementContext(
        topology=DeclaredTopology("parallel", branches),
        channels=tuple(
            channel
            for branch in branches
            for channel in (
                DeclaredChannel(
                    f"i_{branch}",
                    "branch_current",
                    "A",
                    branch_id=branch,
                    time_basis="clock",
                    acquisition="simultaneous",
                ),
                DeclaredChannel(
                    f"v_{branch}",
                    "branch_voltage",
                    "V",
                    branch_id=branch,
                    time_basis="clock",
                    acquisition="simultaneous",
                ),
            )
        ),
    )


def _common_context():
    return MeasurementContext(
        topology=DeclaredTopology("parallel", ("a", "b")),
        channels=(
            DeclaredChannel("pack_voltage_v", "pack_voltage", "V"),
            DeclaredChannel("pack_current_a", "pack_current", "A"),
        ),
    )


@pytest.mark.parametrize(
    "context,reason",
    [
        (None, "MEASUREMENT_CONTEXT_NOT_SUPPLIED"),
        (MeasurementContext(), "PARALLEL_TOPOLOGY_NOT_DECLARED"),
        (
            MeasurementContext(topology=DeclaredTopology("unknown", ("a",))),
            "PARALLEL_TOPOLOGY_NOT_DECLARED",
        ),
        (MeasurementContext(topology=DeclaredTopology("series")), "NON_PARALLEL_TOPOLOGY_DECLARED"),
        (
            MeasurementContext(topology=DeclaredTopology("parallel")),
            "BRANCH_IDENTITIES_NOT_DECLARED",
        ),
        (_common_context(), "COMMON_TERMINAL_DATA_PERMUTATION_AMBIGUITY"),
        (_context(), "BRANCH_LOCALIZATION_MODEL_NOT_AVAILABLE"),
    ],
)
def test_no_declaration_pattern_is_promoted_to_a_physical_diagnosis(context, reason):
    result = ParallelBranchAssessment(context).to_dict()
    assert result["scope"] == "declared_measurement_context_only"
    assert result["status"] == "NOT_EVALUATED"
    assert result["diagnostic_claim"] is False
    assert result["branch_inventory_verified"] is False
    assert result["measurement_properties_verified"] is False
    assert result["localization_method_available"] is False
    assert reason in result["reason_codes"]
    assert "faulty_branch_id" not in result


def test_complete_declarations_do_not_claim_verified_measurements_or_a_ready_method():
    result = ParallelBranchAssessment(_context()).to_dict()
    assert result["reason_codes"] == [
        "BRANCH_INVENTORY_NOT_VERIFIED",
        "BRANCH_LOCALIZATION_MODEL_NOT_AVAILABLE",
        "MEASUREMENT_PROPERTIES_NOT_VERIFIED",
    ]
    assert result["declared_branch_ids"] == ["a", "b"]
    assert result["branches"][0] == {
        "branch_id": "a",
        "current_sources": ["i_a"],
        "terminal_voltage_sources": ["v_a"],
        "cell_voltage_sources": [],
    }


def test_series_declaration_is_not_interpreted_as_an_ideal_parallel_counterexample():
    result = ParallelBranchAssessment(
        MeasurementContext(topology=DeclaredTopology("series"), channels=_common_context().channels)
    ).to_dict()
    assert "NON_PARALLEL_TOPOLOGY_DECLARED" in result["reason_codes"]
    assert "COMMON_TERMINAL_DATA_PERMUTATION_AMBIGUITY" not in result["reason_codes"]
    assert result["branches"] == []


def test_channel_names_do_not_supply_missing_physical_branch_identity():
    context = MeasurementContext(
        topology=DeclaredTopology("parallel", ("a", "b")),
        channels=(DeclaredChannel("branch_a_current", "branch_current", "A"),),
    )
    result = ParallelBranchAssessment(context).to_dict()
    gap = next(
        item for item in result["issues"] if item["code"] == "BRANCH_ASSIGNMENT_NOT_DECLARED"
    )
    assert gap["field"] == "channels.branch_id"
    assert gap["source"] == "branch_a_current" and gap["branch_id"] is None
    assert all(branch["current_sources"] == [] for branch in result["branches"])


def test_cell_voltage_is_not_substituted_for_a_branch_terminal_voltage():
    context = MeasurementContext(
        topology=DeclaredTopology("parallel", ("a",)),
        channels=(DeclaredChannel("cell_v", "cell_voltage", "V", branch_id="a", cell_id="c1"),),
    )
    result = ParallelBranchAssessment(context).to_dict()
    assert result["branches"][0]["cell_voltage_sources"] == ["cell_v"]
    assert result["branches"][0]["terminal_voltage_sources"] == []
    assert "BRANCH_TERMINAL_VOLTAGE_NOT_DECLARED" in result["reason_codes"]
    assert "BRANCH_CURRENT_NOT_DECLARED" in result["reason_codes"]
    assert result["status"] == "NOT_EVALUATED"


@pytest.mark.parametrize("role", ["branch_current", "branch_voltage"])
def test_current_or_voltage_only_is_a_valid_inventory_not_a_universal_requirement(role):
    unit = "mA" if role == "branch_current" else "mV"
    channel = DeclaredChannel(
        "x", role, unit, branch_id="a", time_basis="clock", acquisition="simultaneous"
    )
    context = MeasurementContext(topology=DeclaredTopology("parallel", ("a",)), channels=(channel,))
    result = ParallelBranchAssessment(context).to_dict()
    assert result["status"] == "NOT_EVALUATED"
    assert context.channels[0].unit == unit
    assert "BRANCH_LOCALIZATION_MODEL_NOT_AVAILABLE" in result["reason_codes"]


@pytest.mark.parametrize(
    "mode,reason",
    [
        (None, "CHANNEL_ACQUISITION_NOT_DECLARED"),
        ("unknown", "CHANNEL_ACQUISITION_NOT_DECLARED"),
        ("asynchronous", "ASYNCHRONOUS_ACQUISITION_DECLARED"),
        ("previous_sample_hold", "PREVIOUS_SAMPLE_HOLD_DECLARED"),
    ],
)
def test_acquisition_limits_are_explicit_and_do_not_certify_alignment(mode, reason):
    context = MeasurementContext(
        topology=DeclaredTopology("parallel", ("a",)),
        channels=(DeclaredChannel("i_a", "branch_current", branch_id="a", acquisition=mode),),
    )
    result = ParallelBranchAssessment(context).to_dict()
    assert {reason, "CHANNEL_UNIT_NOT_DECLARED", "CHANNEL_TIME_BASIS_NOT_DECLARED"} <= set(
        result["reason_codes"]
    )
    item = next(item for item in result["issues"] if item["code"] == reason)
    assert item["branch_id"] == "a" and item["source"] == "i_a"
    assert result["measurement_properties_verified"] is False


def test_multiple_clock_labels_are_reported_without_inventing_a_clock_transform():
    context = MeasurementContext(
        topology=DeclaredTopology("parallel", ("a",)),
        channels=(
            DeclaredChannel("i", "branch_current", "A", branch_id="a", time_basis="z"),
            DeclaredChannel("v", "branch_voltage", "V", branch_id="a", time_basis="a"),
        ),
    )
    result = ParallelBranchAssessment(context).to_dict()
    assert result["declared_time_bases"] == ["a", "z"]
    assert "MULTIPLE_TIME_BASES_DECLARED" in result["reason_codes"]
    assert result["status"] == "NOT_EVALUATED"


@given(st.permutations(_context().channels), st.permutations(("a", "b")))
def test_channel_and_branch_order_do_not_change_the_payload(channels, branches):
    context = MeasurementContext(
        topology=DeclaredTopology("parallel", tuple(branches)), channels=tuple(channels)
    )
    assert (
        ParallelBranchAssessment(context).to_dict()
        == ParallelBranchAssessment(_context()).to_dict()
    )


def test_renaming_physical_branch_labels_moves_inventory_and_gaps_consistently():
    context = MeasurementContext(
        topology=DeclaredTopology("parallel", ("a", "b")),
        channels=(
            DeclaredChannel("current", "branch_current", "A", branch_id="a"),
            DeclaredChannel("voltage", "branch_voltage", "V", branch_id="b"),
        ),
    )
    before = ParallelBranchAssessment(context).to_dict()
    swapped = MeasurementContext(
        topology=DeclaredTopology("parallel", ("b", "a")),
        channels=(
            DeclaredChannel("current", "branch_current", "A", branch_id="b"),
            DeclaredChannel("voltage", "branch_voltage", "V", branch_id="a"),
        ),
    )
    after = ParallelBranchAssessment(swapped).to_dict()
    inverse = {"a": "b", "b": "a", None: None}
    for branch in after["branches"]:
        branch["branch_id"] = inverse[branch["branch_id"]]
    for issue in after["issues"]:
        issue["branch_id"] = inverse[issue["branch_id"]]
    after["branches"].sort(key=lambda item: item["branch_id"])
    after["issues"].sort(
        key=lambda item: (
            item["code"],
            item["branch_id"] or "",
            item["source"] or "",
            item["field"],
        )
    )
    assert after == before


def test_hidden_branch_current_swap_leaves_common_observations_and_engineering_fail_unchanged():
    # A sum/permutation counterexample, not a calibrated physical cell model.
    limits = ValidationLimits(pack_discharge_max_a=10, pack_current_positive_direction="discharge")
    outputs = []
    for currents in [((5, 15), (10, 12)), ((15, 5), (12, 10))]:
        rows = "".join(f"{index},3.8,25,3.8,{sum(pair)}\n" for index, pair in enumerate(currents))
        data = ("timestamp_s,cell_1_v,temp_c,pack_voltage_v,pack_current_a\n" + rows).encode()
        whole = analyze_battery_bytes(data, limits=limits)
        before = render_json_result(whole)
        report = ParallelBranchAssessment(_common_context()).to_dict()
        assert report["status"] == "NOT_EVALUATED"
        assert "COMMON_TERMINAL_DATA_PERMUTATION_AMBIGUITY" in report["reason_codes"]
        assert whole["validation_status"] == "FAIL"
        assert whole["violations"][0]["code"] == "PACK_DISCHARGE_OVERCURRENT"
        assert render_json_result(whole) == before
        for size in (1, 2, 100):
            streamed = analyze_measurement_loader(
                CsvFileLoader(BytesIO(data), chunk_rows=size), limits=limits
            )
            assert render_json_result(streamed) == before
        outputs.append(before)
    assert outputs[0] == outputs[1]


def test_exported_inventory_and_issues_cannot_mutate_the_review_or_context():
    context = _common_context()
    before = copy.deepcopy(context.to_dict())
    review = ParallelBranchAssessment(context)
    expected = review.to_dict()
    exported = review.to_dict()
    exported["branches"][0]["current_sources"].append("invented")
    exported["issues"][0]["detail"] = "invented"
    exported["reason_codes"].clear()
    exported["declared_branch_ids"].clear()
    assert review.to_dict() == expected
    assert context.to_dict() == before
    assert json.loads(json.dumps(expected, allow_nan=False)) == expected
    with pytest.raises(FrozenInstanceError):
        review.status = "PASS"
    with pytest.raises(TypeError):
        ParallelBranchAssessment(context, diagnostic_claim=True)


@pytest.mark.parametrize("context", [True, {}, "parallel", 1])
def test_unvalidated_context_is_rejected(context):
    with pytest.raises(TypeError, match="validated MeasurementContext"):
        ParallelBranchAssessment(context)
