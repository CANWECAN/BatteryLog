import copy
import json
from dataclasses import FrozenInstanceError
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from batterylog.interpretation import InterpretationReport
from batterylog.measurement_context import (
    MAX_CONTEXT_BYTES,
    DeclaredChannel,
    DeclaredSOC,
    DeclaredTopology,
    MeasurementContext,
    load_measurement_context,
    load_measurement_context_bytes,
)

ROOT = Path(__file__).parents[1]


def _raw():
    return {
        "measurement_context_schema_version": 1,
        "topology": {"kind": "parallel", "branch_ids": ["a", "b"]},
        "channels": [
            {"source": "i_a", "role": "branch_current", "unit": "A", "branch_id": "a"},
            {
                "source": "v_a",
                "role": "cell_voltage",
                "unit": "V",
                "branch_id": "a",
                "cell_id": "c1",
            },
        ],
        "chemistry": "LFP",
        "soc": {"value_percent": 50, "source": "BMS estimate"},
        "operating_state": "rest",
    }


def _load(raw):
    return load_measurement_context_bytes(json.dumps(raw).encode())


def test_missing_context_is_preserved_without_inference():
    context = _load({"measurement_context_schema_version": 1})
    assert context.topology is context.chemistry is context.soc is context.operating_state is None
    assert context.channels == ()
    assert context.measurement_properties_verified is False
    assert context.evidence_level == "DECLARED"
    raw = {
        "measurement_context_schema_version": 1,
        "channels": [{"source": "cell_7_v", "role": "cell_voltage"}],
    }
    channel = _load(raw).channels[0]
    assert channel.unit is channel.cell_id is channel.branch_id is channel.time_basis is None
    assert channel.acquisition is None


def test_declared_measurements_never_become_verified_properties():
    raw = _raw()
    raw["channels"][0].update(time_basis="clock_a", acquisition="simultaneous")
    context = _load(raw)
    assert context.channels[0].acquisition == "simultaneous"
    assert context.measurement_properties_verified is False
    assert InterpretationReport("FAIL").to_dict()["diagnostic_claim"] is False
    assert load_measurement_context_bytes(json.dumps(context.to_dict()).encode()) == context


def test_unknown_topology_and_partial_branch_inventory_are_not_completed():
    raw = _raw()
    raw["topology"] = {"kind": "unknown", "branch_ids": ["a"]}
    context = _load(raw)
    assert context.topology == DeclaredTopology("unknown", ("a",))
    assert context.channels[0].branch_id == "a"


def test_export_and_caller_mutations_cannot_change_nested_context():
    raw = _raw()
    before = copy.deepcopy(raw)
    context = _load(raw)
    assert raw == before
    exported = context.to_dict()
    exported["topology"]["branch_ids"].clear()
    exported["channels"][0]["source"] = "changed"
    exported["soc"]["value_percent"] = 0
    assert context.topology.branch_ids == ("a", "b")
    assert context.channels[0].source == "i_a"
    assert context.soc.value_percent == 50
    with pytest.raises(FrozenInstanceError):
        context.soc.value_percent = 0
    with pytest.raises(FrozenInstanceError):
        context.measurement_properties_verified = True
    with pytest.raises(TypeError):
        MeasurementContext(measurement_properties_verified=True)


@pytest.mark.parametrize("version", [True, False, 1.0, "1", 0, 2, None])
def test_schema_version_is_exact_and_never_coerced(version):
    with pytest.raises(ValueError, match="integer 1"):
        _load({"measurement_context_schema_version": version})


@pytest.mark.parametrize("target", ["root", "topology", "channel", "soc"])
def test_unknown_or_self_certifying_fields_are_rejected(target):
    raw = _raw()
    item = {
        "root": raw,
        "topology": raw["topology"],
        "channel": raw["channels"][0],
        "soc": raw["soc"],
    }[target]
    item["measurement_properties_verified"] = True
    with pytest.raises(ValueError, match="Measurement context"):
        _load(raw)


@pytest.mark.parametrize(
    "data",
    [
        b'{"measurement_context_schema_version":1,"measurement_context_schema_version":1}',
        b'{"measurement_context_schema_version":1,"soc":{"source":"x","source":"y"}}',
    ],
)
def test_duplicate_keys_are_rejected_even_if_equal(data):
    with pytest.raises(ValueError, match="Duplicate"):
        load_measurement_context_bytes(data)


@pytest.mark.parametrize(
    "value", [True, "50", -0.01, 100.01, float("nan"), float("inf"), -float("inf")]
)
def test_soc_requires_finite_numbers_within_percent_range(value):
    raw = _raw()
    raw["soc"]["value_percent"] = value
    with pytest.raises(ValueError):
        _load(raw)


@given(st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False))
def test_soc_declarations_round_trip_without_becoming_estimates(value):
    context = MeasurementContext(soc=DeclaredSOC(value_percent=value))
    assert _load(context.to_dict()) == context
    assert context.soc.source is None
    assert context.measurement_properties_verified is False


@pytest.mark.parametrize("value", [0, 100])
def test_soc_endpoints_are_valid_and_not_missing(value):
    assert (
        _load(
            {"measurement_context_schema_version": 1, "soc": {"value_percent": value}}
        ).soc.value_percent
        == value
    )


@pytest.mark.parametrize("value", [Decimal(50), Decimal("NaN"), Fraction(1, 2)])
def test_direct_soc_cannot_export_non_json_numeric_objects(value):
    with pytest.raises(ValueError, match="JSON number"):
        MeasurementContext(soc=DeclaredSOC(value_percent=value))


@pytest.mark.parametrize(
    "role,unit", [("branch_current", "V"), ("cell_voltage", "A"), ("temperature", "mA")]
)
def test_role_unit_mismatch_is_rejected_without_conversion(role, unit):
    raw = {
        "measurement_context_schema_version": 1,
        "channels": [{"source": "x", "role": role, "unit": unit}],
    }
    with pytest.raises(ValueError, match="incompatible"):
        _load(raw)


def test_compatible_source_units_are_preserved_without_normalization():
    context = MeasurementContext(channels=(DeclaredChannel("v", "cell_voltage", "mV"),))
    assert context.channels[0].unit == "mV"


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate_source",
        "undeclared_branch",
        "duplicate_branch",
        "duplicate_cell",
        "duplicate_ids",
        "series_branches",
        "pack_branch",
        "current_cell",
    ],
)
def test_contradictory_and_ambiguous_mappings_are_rejected(defect):
    raw = _raw()
    if defect == "duplicate_source":
        raw["channels"][1]["source"] = "i_a"
    elif defect == "undeclared_branch":
        raw["channels"][0]["branch_id"] = "typo"
    elif defect in {"duplicate_branch", "duplicate_cell"}:
        copied = copy.deepcopy(raw["channels"][defect == "duplicate_cell"])
        copied["source"] = "redundant"
        raw["channels"].append(copied)
    elif defect == "duplicate_ids":
        raw["topology"]["branch_ids"] = ["a", "a"]
    elif defect == "series_branches":
        raw["topology"]["kind"] = "series"
    elif defect == "pack_branch":
        raw["channels"][0]["role"] = "pack_current"
    else:
        raw["channels"][0]["cell_id"] = "c1"
    with pytest.raises(ValueError):
        _load(raw)


def test_explicit_cell_temperature_and_missing_branch_identity_are_valid():
    raw = _raw()
    raw["channels"].append(
        {"source": "t_a", "role": "temperature", "unit": "degC", "branch_id": "a", "cell_id": "c1"}
    )
    assert _load(raw).channels[-1].cell_id == "c1"
    raw["channels"][0]["branch_id"] = None
    assert _load(raw).channels[0].branch_id is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"channels": []},
        {"channels": ({"source": "x"},)},
        {"topology": {"kind": "series"}},
        {"topology": DeclaredTopology("parallel", ["a"])},
        {"soc": {"value_percent": 50}},
    ],
)
def test_direct_construction_cannot_bypass_immutable_boundary(kwargs):
    with pytest.raises(TypeError):
        MeasurementContext(**kwargs)


@pytest.mark.parametrize(
    "label", ["", "   ", "bad\nlabel", "bad\x00label", "bad\x7flabel", "\ud800", "x" * 257]
)
def test_invalid_labels_are_rejected(label):
    with pytest.raises(ValueError):
        MeasurementContext(chemistry=label)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"[]",
        b"null",
        b"{",
        b"\xff",
        b'{"measurement_context_schema_version":1,"soc":{"value_percent":1e309}}',
    ],
)
def test_malformed_or_non_object_inputs_are_rejected(data):
    with pytest.raises(ValueError):
        load_measurement_context_bytes(data)


def test_input_and_nesting_limits_are_enforced(tmp_path):
    with pytest.raises(ValueError, match="1 MiB"):
        load_measurement_context_bytes(b" " * (MAX_CONTEXT_BYTES + 1))
    path = tmp_path / "oversize.json"
    path.write_bytes(b" " * (MAX_CONTEXT_BYTES + 1))
    with pytest.raises(ValueError, match="1 MiB"):
        load_measurement_context(path)
    raw = b'{"measurement_context_schema_version":1,"extra":' + b"[" * 20 + b"0" + b"]" * 20 + b"}"
    with pytest.raises(ValueError, match="nesting"):
        load_measurement_context_bytes(raw)
    with pytest.raises(TypeError, match="bytes"):
        load_measurement_context_bytes("{}")


def test_channel_count_limit_and_bom_example_loading():
    raw = {
        "measurement_context_schema_version": 1,
        "channels": [{"source": str(i), "role": "cell_voltage"} for i in range(4097)],
    }
    with pytest.raises(ValueError):
        _load(raw)
    path = ROOT / "examples/measurement_context.json"
    assert load_measurement_context(path) == load_measurement_context_bytes(
        b"\xef\xbb\xbf" + path.read_bytes()
    )
