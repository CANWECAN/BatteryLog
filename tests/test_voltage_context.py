import json
from dataclasses import FrozenInstanceError, replace
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
    DeclaredSOC,
    MeasurementContext,
    load_measurement_context_bytes,
)
from batterylog.reporting import render_json_result
from batterylog.voltage_context import VoltageSpreadAssessment

DATA = b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.7,3.6,25\n1,3.8,3.6,25\n2,3.7,3.6,25\n"


def _complete_context():
    return MeasurementContext(
        chemistry="LFP",
        soc=DeclaredSOC(0, "declared BMS estimate"),
        operating_state="rest",
        channels=tuple(
            DeclaredChannel(
                f"cell_{index}_v",
                "cell_voltage",
                "V",
                cell_id=f"physical_{index}",
                time_basis="clock",
                acquisition="simultaneous",
            )
            for index in (1, 2)
        ),
    )


def test_absent_context_is_distinguished_from_an_empty_declaration():
    absent = VoltageSpreadAssessment().to_dict()
    minimal = VoltageSpreadAssessment(MeasurementContext()).to_dict()
    assert absent["context_supplied"] is False
    assert absent["declared_soc"] is None
    assert absent["cell_voltage_channels"] == []
    assert "MEASUREMENT_CONTEXT_NOT_SUPPLIED" in absent["reason_codes"]
    assert minimal["context_supplied"] is True
    assert "MEASUREMENT_CONTEXT_NOT_SUPPLIED" not in minimal["reason_codes"]
    assert {
        "CHEMISTRY_NOT_DECLARED",
        "SOC_VALUE_NOT_DECLARED",
        "SOC_SOURCE_NOT_DECLARED",
        "OPERATING_STATE_NOT_DECLARED",
        "CELL_VOLTAGE_CHANNELS_NOT_DECLARED",
    } <= set(minimal["reason_codes"])
    assert all(issue["source"] is None for issue in minimal["issues"])


def test_complete_context_still_has_unverified_inventory_conditions_and_no_soc_method():
    payload = VoltageSpreadAssessment(_complete_context()).to_dict()
    assert payload["reason_codes"] == [
        "CELL_INVENTORY_NOT_VERIFIED",
        "MEASUREMENT_PROPERTIES_NOT_VERIFIED",
        "OPERATING_CONTEXT_NOT_VERIFIED",
        "REST_EQUILIBRATION_NOT_VERIFIED",
        "SOC_IMBALANCE_MODEL_NOT_AVAILABLE",
    ]
    assert payload["declared_soc"] == {"value_percent": 0, "source": "declared BMS estimate"}
    assert payload["declared_chemistry"] == "LFP"
    assert payload["declared_operating_state"] == "rest"
    assert payload["declared_time_bases"] == ["clock"]
    assert payload["status"] == "NOT_EVALUATED"
    assert payload["diagnostic_claim"] is False
    assert payload["cell_inventory_verified"] is False
    assert payload["operating_context_verified"] is False
    assert payload["measurement_properties_verified"] is False
    assert payload["soc_imbalance_method_available"] is False
    assert "soc_delta_percent" not in payload
    assert "fault_cause" not in payload


@pytest.mark.parametrize(
    "soc,missing,present",
    [
        (DeclaredSOC(50), "SOC_SOURCE_NOT_DECLARED", "SOC_VALUE_NOT_DECLARED"),
        (
            DeclaredSOC(source="external estimator"),
            "SOC_VALUE_NOT_DECLARED",
            "SOC_SOURCE_NOT_DECLARED",
        ),
    ],
)
def test_soc_value_and_provenance_are_reviewed_independently(soc, missing, present):
    payload = VoltageSpreadAssessment(replace(_complete_context(), soc=soc)).to_dict()
    assert missing in payload["reason_codes"]
    assert present not in payload["reason_codes"]
    issue = next(issue for issue in payload["issues"] if issue["code"] == missing)
    assert issue["field"] in {"soc.value_percent", "soc.source"}
    assert payload["status"] == "NOT_EVALUATED"


@pytest.mark.parametrize(
    "state,reason",
    [
        (None, "OPERATING_STATE_NOT_DECLARED"),
        ("unknown", "OPERATING_STATE_NOT_DECLARED"),
        ("rest", "REST_EQUILIBRATION_NOT_VERIFIED"),
        ("charge", "UNDER_LOAD_OPERATION_DECLARED"),
        ("discharge", "UNDER_LOAD_OPERATION_DECLARED"),
        ("mixed", "UNDER_LOAD_OPERATION_DECLARED"),
    ],
)
def test_rest_and_load_labels_never_certify_equilibrium_or_classify_time_intervals(state, reason):
    payload = VoltageSpreadAssessment(replace(_complete_context(), operating_state=state)).to_dict()
    assert reason in payload["reason_codes"]
    assert payload["declared_operating_state"] == state
    assert payload["operating_context_verified"] is False
    assert payload["status"] == "NOT_EVALUATED"


def test_source_names_and_pack_voltage_do_not_supply_physical_cell_metadata():
    context = MeasurementContext(
        channels=(
            DeclaredChannel("cell_7_lfp_soc50_rest_v", "cell_voltage"),
            DeclaredChannel("cell_8_v", "pack_voltage", "V", time_basis="other"),
        )
    )
    payload = VoltageSpreadAssessment(context).to_dict()
    assert payload["cell_voltage_channels"] == [
        {
            "source": "cell_7_lfp_soc50_rest_v",
            "unit": None,
            "branch_id": None,
            "cell_id": None,
            "time_basis": None,
            "acquisition": None,
        }
    ]
    assert payload["declared_chemistry"] is None
    assert payload["declared_soc"] is None
    assert payload["declared_operating_state"] is None
    assert payload["declared_time_bases"] == []
    for code in (
        "CELL_IDENTITY_NOT_DECLARED",
        "CHANNEL_UNIT_NOT_DECLARED",
        "CHANNEL_TIME_BASIS_NOT_DECLARED",
        "CHANNEL_ACQUISITION_NOT_DECLARED",
    ):
        issue = next(issue for issue in payload["issues"] if issue["code"] == code)
        assert issue["source"] == "cell_7_lfp_soc50_rest_v"
        assert issue["field"].startswith("channels.")


def test_pack_and_branch_voltage_are_not_substituted_for_cell_sources():
    context = MeasurementContext(
        channels=(
            DeclaredChannel("a", "pack_voltage", "V"),
            DeclaredChannel("b", "branch_voltage", "V"),
        )
    )
    payload = VoltageSpreadAssessment(context).to_dict()
    assert payload["cell_voltage_channels"] == []
    assert "CELL_VOLTAGE_CHANNELS_NOT_DECLARED" in payload["reason_codes"]


@pytest.mark.parametrize(
    "acquisition,reason",
    [
        (None, "CHANNEL_ACQUISITION_NOT_DECLARED"),
        ("unknown", "CHANNEL_ACQUISITION_NOT_DECLARED"),
        ("asynchronous", "ASYNCHRONOUS_ACQUISITION_DECLARED"),
        ("previous_sample_hold", "PREVIOUS_SAMPLE_HOLD_DECLARED"),
    ],
)
def test_unqualified_and_held_acquisition_limits_remain_source_specific(acquisition, reason):
    context = _complete_context()
    first, second = context.channels
    context = replace(context, channels=(replace(first, acquisition=acquisition), second))
    payload = VoltageSpreadAssessment(context).to_dict()
    issues = [issue for issue in payload["issues"] if issue["code"] == reason]
    assert len(issues) == 1
    assert issues[0]["source"] == first.source
    assert issues[0]["field"] == "channels.acquisition"
    assert payload["measurement_properties_verified"] is False


def test_multiple_cell_clocks_are_distinguished_from_matching_labels():
    context = _complete_context()
    first, second = context.channels
    payload = VoltageSpreadAssessment(
        replace(context, channels=(first, replace(second, time_basis="different")))
    ).to_dict()
    assert payload["declared_time_bases"] == ["clock", "different"]
    assert "MULTIPLE_TIME_BASES_DECLARED" in payload["reason_codes"]
    assert payload["measurement_properties_verified"] is False


@given(st.permutations(_complete_context().channels))
def test_declaration_order_does_not_change_the_entire_export(channels):
    context = _complete_context()
    assert (
        VoltageSpreadAssessment(replace(context, channels=tuple(channels))).to_dict()
        == VoltageSpreadAssessment(context).to_dict()
    )


def test_export_is_detached_and_does_not_mutate_the_context():
    context = _complete_context()
    context_before = context.to_dict()
    review = VoltageSpreadAssessment(context)
    expected = review.to_dict()
    exported = review.to_dict()
    exported["declared_soc"]["value_percent"] = 99
    exported["cell_voltage_channels"][0]["cell_id"] = "wrong"
    exported["reason_codes"].clear()
    exported["issues"][0]["detail"] = "wrong"
    assert review.to_dict() == expected
    assert context.to_dict() == context_before
    assert json.loads(json.dumps(expected, allow_nan=False)) == expected
    with pytest.raises(FrozenInstanceError):
        review.context = None
    with pytest.raises(FrozenInstanceError):
        review.status = "PASS"


@pytest.mark.parametrize("value", [{}, [], True, "context.json", object()])
def test_unvalidated_context_is_rejected(value):
    with pytest.raises(TypeError, match="validated MeasurementContext"):
        VoltageSpreadAssessment(value)


def test_diagnostic_status_is_not_a_constructor_option():
    with pytest.raises(TypeError):
        VoltageSpreadAssessment(status="PASS")
    with pytest.raises(TypeError):
        VoltageSpreadAssessment(diagnostic_claim=True)


CONTEXTS = [
    None,
    MeasurementContext(),
    _complete_context(),
    replace(
        _complete_context(), chemistry="NMC", soc=DeclaredSOC(100, "lab"), operating_state="charge"
    ),
    replace(_complete_context(), chemistry="unknown", operating_state="mixed"),
]


@pytest.mark.parametrize("context", CONTEXTS)
@pytest.mark.parametrize(
    "limits,status",
    [
        (ValidationLimits(), "NOT_EVALUATED"),
        (ValidationLimits(imbalance_max_v=0.5), "PASS"),
        (ValidationLimits(imbalance_max_v=0.05), "FAIL"),
    ],
)
def test_identical_voltage_observation_and_engineering_result_survive_context_changes(
    context, limits, status
):
    result = analyze_battery_bytes(DATA, limits=limits)
    before = render_json_result(result)
    review = VoltageSpreadAssessment(context).to_dict()
    assert render_json_result(result) == before
    assert result["validation_status"] == status
    assert result["max_delta_v"] == 0.2
    if status == "FAIL":
        violation = next(
            item for item in result["violations"] if item["code"] == "CELL_IMBALANCE_HIGH"
        )
        assert violation["measured_value"] == 0.2
        assert violation["limit_value"] == 0.05
    assert review["claim"] == "CELL_SOC_IMBALANCE"
    assert review["status"] == "NOT_EVALUATED"
    assert review["diagnostic_claim"] is False
    assert review["soc_imbalance_method_available"] is False


@pytest.mark.parametrize("chunk_rows", [1, 2, 100])
def test_chunking_preserves_observation_and_context_is_not_used_to_reinterpret_samples(chunk_rows):
    limits = ValidationLimits(imbalance_max_v=0.05)
    whole = analyze_battery_bytes(DATA, limits=limits)
    streamed = analyze_measurement_loader(
        CsvFileLoader(BytesIO(DATA), chunk_rows=chunk_rows), limits=limits
    )
    context = load_measurement_context_bytes(json.dumps(_complete_context().to_dict()).encode())
    VoltageSpreadAssessment(context).to_dict()
    assert render_json_result(streamed) == render_json_result(whole)
    assert whole["validation_status"] == "FAIL"
