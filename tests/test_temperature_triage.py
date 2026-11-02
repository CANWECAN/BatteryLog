"""Independent tests for Research-only temperature event triage."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from batterylog_research.temperature_triage import main, triage_temperature_events


def _event(before, after, rate, *, sensor="temp_1_c", when=2.0):
    return {
        "code": "TEMPERATURE_RISE_HIGH",
        "peak_time_s": when,
        "measured_value": rate,
        "signals": [sensor],
        "evidence": {"previous_temperature_c": before, "temperature_c": after},
    }


def _result(*events):
    return {
        "schema_version": 9,
        "failure_models": {
            "evaluations": [{"code": "TEMPERATURE_RISE_HIGH", "events": list(events)}]
        },
    }


def test_spike_flagged_without_mutating_result_or_relabeling_fault():
    result = _result(
        _event(2.22, 655.28, 122190.6, when=2247.305),
        _event(22, 24, 6, sensor="temp_2_c"),
    )
    before = copy.deepcopy(result)
    summary = triage_temperature_events(result, max_temperature_c=150)
    assert summary["events_flagged"] == 1
    assert summary["temperature_events_reviewed"] == 2
    assert summary["events_without_review_flags"] == 1
    assert summary["reason_counts"] == {"temperature_above_review_ceiling": 1}
    assert summary["representative_sensor_counts"] == {"temp_1_c": 1}
    assert summary["examples"][0]["peak_time_s"] == 2247.305
    assert result == before
    assert "not proof" in summary["interpretation"].lower()


def test_distinct_reasons_and_bounded_examples():
    summary = triage_temperature_events(
        _result(_event(-50, 200, 1000), _event(15, 16, 900, sensor="temp_2_c")),
        min_temperature_c=-40,
        max_temperature_c=150,
        max_reported_rate_c_per_min=500,
        max_examples=1,
    )
    assert summary["events_flagged"] == 2
    assert summary["reason_counts"] == {
        "reported_rise_above_review_ceiling": 2,
        "temperature_above_review_ceiling": 1,
        "temperature_below_review_floor": 1,
    }
    assert len(summary["examples"]) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"min_temperature_c": 50, "max_temperature_c": 40},
        {"max_reported_rate_c_per_min": 0},
        {"max_temperature_c": float("inf")},
        {"max_temperature_c": 120, "max_examples": True},
        {"max_temperature_c": 120, "max_examples": 101},
    ],
)
def test_invalid_review_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        triage_temperature_events(_result(), **kwargs)


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 8},
        {"schema_version": 9, "failure_models": {"evaluations": []}},
        _result(_event(1, float("nan"), 60)),
        _result({"code": "TEMPERATURE_RISE_HIGH", "signals": []}),
    ],
)
def test_missing_or_malformed_evidence_fails_closed(payload):
    with pytest.raises(ValueError):
        triage_temperature_events(payload, max_temperature_c=150)


def test_no_temperature_events_is_not_a_clean_sensor_bill_of_health():
    summary = triage_temperature_events(_result(), max_temperature_c=150)
    assert summary["temperature_events_reviewed"] == 0
    assert summary["events_flagged"] == 0
    assert summary["scope"] == "existing_temperature_rise_events_only"


def test_cli_prints_review_only_and_does_not_modify_source(tmp_path, capsys, monkeypatch):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(_result(_event(25, 655.28, 30000))), encoding="utf-8")
    original = path.read_bytes()
    validated = []
    monkeypatch.setattr(
        "batterylog_research.temperature_triage._validate_source_result",
        lambda payload: validated.append(payload),
    )
    assert main([str(path), "--max-temperature-c", "150", "--max-examples", "0"]) == 0
    assert len(validated) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["events_flagged"] == 1
    assert report["examples"] == []
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema_version":9,"schema_version":9}',
        '{"schema_version":9,"failure_models":{"evaluations":[{"x":1,"x":2}]}}',
        '{"schema_version":9,"measurement":1e9999}',
        '{"schema_version":9,"measurement":NaN}',
    ],
)
def test_cli_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path, capsys, raw):
    path = tmp_path / "invalid.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        main([str(path), "--max-temperature-c", "150"])
    assert "error:" in capsys.readouterr().err


def test_cli_refuses_unvalidated_result(tmp_path, monkeypatch, capsys):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(_result(_event(25, 655, 30000))), encoding="utf-8")

    def refuse(_payload):
        raise ValueError("failed semantic validation")

    monkeypatch.setattr("batterylog_research.temperature_triage._validate_source_result", refuse)
    with pytest.raises(SystemExit, match="2"):
        main([str(path), "--max-temperature-c", "150"])
    assert "failed semantic validation" in capsys.readouterr().err


def test_large_event_count_has_bounded_examples_and_exact_accounting():
    template = _event(22, 655.28, 120000)
    ordinary = _event(22, 24, 6)
    result = _result(*([template, ordinary] * 10_000))
    before = len(result["failure_models"]["evaluations"][0]["events"])
    summary = triage_temperature_events(result, max_temperature_c=150, max_examples=3)
    assert summary["temperature_events_reviewed"] == before == 20_000
    assert summary["events_flagged"] == 10_000
    assert summary["events_without_review_flags"] == 10_000
    assert len(summary["examples"]) == 3
    assert len(result["failure_models"]["evaluations"][0]["events"]) == before


@pytest.mark.skipif(
    importlib.util.find_spec("batterylog") is None,
    reason="Requires complete Research checkout with BatteryLog runtime dependencies",
)
def test_cli_accepts_genuine_model_result_v9(tmp_path, capsys):
    from batterylog import AnalysisService
    from batterylog.config import load_validation_config_bytes

    root = Path(__file__).parents[1]
    config = load_validation_config_bytes(
        (root / "examples/failure_models.example.yaml").read_bytes()
    )
    result = AnalysisService(config).analyze_path(root / "examples/failure_models_demo.csv").result
    assert result["schema_version"] == 9
    assert any(
        item["code"] == "TEMPERATURE_RISE_HIGH" for item in result["failure_models"]["evaluations"]
    )
    path = tmp_path / "actual-model-output.json"
    path.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    original = path.read_bytes()
    assert main([str(path), "--max-reported-rate-c-per-min", "1"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["temperature_events_reviewed"] >= 1
    assert summary["events_flagged"] >= 1
    assert path.read_bytes() == original


@pytest.mark.skipif(
    importlib.util.find_spec("batterylog") is None,
    reason="Requires complete Research checkout with BatteryLog runtime dependencies",
)
@pytest.mark.parametrize("mutation", ["status", "row_count"])
def test_cli_rejects_inconsistent_genuine_model_result(tmp_path, capsys, monkeypatch, mutation):
    from jsonschema import Draft202012Validator, ValidationError

    from batterylog import AnalysisService
    from batterylog.config import load_validation_config_bytes

    root = Path(__file__).parents[1]
    config = load_validation_config_bytes(
        (root / "examples/failure_models.example.yaml").read_bytes()
    )
    result = AnalysisService(config).analyze_path(root / "examples/failure_models_demo.csv").result
    assert result["validation_status"] == "FAIL"
    schema = json.loads((root / "batterylog/schema/result-v9.json").read_text())
    validator = Draft202012Validator(schema)
    validator.validate(result)
    if mutation == "status":
        result["validation_status"] = "PASS"
        # The schema rejects PASS while violations or FAIL evaluations remain.
        with pytest.raises(ValidationError):
            validator.validate(result)
    else:
        result["rows_input"] += 1
        # This shape is valid; semantic row accounting must still reject it.
        validator.validate(result)

    def refuse_triage(*args, **kwargs):
        pytest.fail("Invalid source reached temperature triage")

    monkeypatch.setattr(
        "batterylog_research.temperature_triage.triage_temperature_events", refuse_triage
    )
    path = tmp_path / "tampered-result.json"
    path.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(SystemExit, match="2"):
        main([str(path), "--max-temperature-c", "150"])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err
    if mutation == "row_count":
        assert "rows_input" in captured.err
    assert path.read_bytes() == original
