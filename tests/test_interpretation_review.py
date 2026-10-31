import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from batterylog import ValidationConfig, ValidationLimits
from batterylog.analysis.service import AnalysisService
from batterylog.failure_config import FailureModelConfig, SustainedImbalanceConfig
from batterylog.interpretation_review import review_measurement
from batterylog.reporting import render_json_result

DATA = b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.8,3.6,25\n1,3.8,3.6,25\n"


def inputs(tmp_path):
    source = tmp_path / "source.csv"
    source.write_bytes(DATA)
    context = tmp_path / "declarations.json"
    context.write_bytes(b'\xef\xbb\xbf{"measurement_context_schema_version":1,"chemistry":"LFP"}\n')
    return source, context, tmp_path / "review"


@pytest.mark.parametrize("limit,status", [(None, "NOT_EVALUATED"), (0.5, "PASS"), (0.05, "FAIL")])
def test_same_source_analysis_exact_result_and_context_bytes_are_bound_without_diagnosis(
    tmp_path, limit, status
):
    source, context, target = inputs(tmp_path)
    config = ValidationConfig(limits=ValidationLimits(imbalance_max_v=limit))
    original = render_json_result(AnalysisService(config).analyze_path(source).result).encode()
    bundle = review_measurement(source, target, context_path=context, config=config)
    payload = bundle.to_dict()
    assert bundle.engineering_status == status
    assert bundle.output_directory == target
    assert (target / "result.json").read_bytes() == original == bundle.result_json.encode()
    assert (target / "context.json").read_bytes() == context.read_bytes()
    assert payload == json.loads((target / "interpretation.json").read_bytes())
    assert payload["engineering_status"] == status
    assert payload["physical_interpretation_status"] == "NOT_EVALUATED"
    assert payload["diagnostic_claim"] is False
    assert payload["measurement_properties_verified"] is False
    assert all(claim["status"] == "NOT_EVALUATED" for claim in payload["claims"])
    assert payload["binding"]["source"]["sha256"] == hashlib.sha256(DATA).hexdigest()
    assert payload["binding"]["source_channel_mapping_verified"] is False
    for key in ("result", "context", "effective_config"):
        artifact = payload["binding"][key]
        data = (target / artifact["path"]).read_bytes()
        assert len(data) == artifact["size_bytes"]
        assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
    if status == "FAIL":
        assert payload["observations"]["violations"] == json.loads(original)["violations"]
        assert payload["observations"]["violations"][0]["code"] == "CELL_IMBALANCE_HIGH"
    assert source.read_bytes() == DATA
    exported = bundle.to_dict()
    exported["claims"][0]["reason_codes"].clear()
    assert bundle.to_dict() == payload
    with pytest.raises(FrozenInstanceError):
        bundle.result_json = "{}"


def test_no_context_and_repeated_runs_have_explicit_deterministic_evidence(tmp_path):
    source, _, target = inputs(tmp_path)
    first = review_measurement(source, target)
    second = review_measurement(source, tmp_path / "again")
    assert first.interpretation_json == second.interpretation_json
    assert first.result_json == second.result_json
    assert first.to_dict()["binding"]["context"] is None
    assert first.to_dict()["context_evidence_level"] == "NOT_SUPPLIED"
    assert not (target / "context.json").exists()
    assert "MEASUREMENT_CONTEXT_NOT_SUPPLIED" in first.to_dict()["claims"][0]["reason_codes"]


def test_context_change_changes_only_contextual_evidence_and_not_engineering_result(tmp_path):
    source, context, target = inputs(tmp_path)
    config = ValidationConfig(limits=ValidationLimits(imbalance_max_v=0.05))
    first = review_measurement(source, target, context_path=context, config=config)
    context.write_text(
        '{"measurement_context_schema_version":1,"chemistry":"NMC","operating_state":"discharge"}'
    )
    second = review_measurement(source, tmp_path / "second", context_path=context, config=config)
    assert first.result_json == second.result_json
    assert first.to_dict()["binding"]["source"] == second.to_dict()["binding"]["source"]
    assert first.to_dict()["binding"]["context"] != second.to_dict()["binding"]["context"]
    assert first.to_dict()["claims"] != second.to_dict()["claims"]
    assert first.engineering_status == second.engineering_status == "FAIL"


@pytest.mark.parametrize("changed", ["source", "context"])
def test_changed_input_is_rejected_before_publication(tmp_path, monkeypatch, changed):
    import batterylog.interpretation_review as module

    source, context, target = inputs(tmp_path)
    original = module._verify_artifacts

    def tamper(directory, payload):
        original(directory, payload)
        path = source if changed == "source" else context
        path.write_bytes(path.read_bytes() + b" ")

    monkeypatch.setattr(module, "_verify_artifacts", tamper)
    with pytest.raises(ValueError, match="changed during analysis"):
        review_measurement(source, target, context_path=context)
    assert not target.exists()
    assert not list(tmp_path.glob(".batterylog-interpret-*"))


@pytest.mark.parametrize(
    "artifact", ["result.json", "context.json", "effective-config.json", "interpretation.json"]
)
def test_staged_artifact_tampering_never_publishes_a_bundle(tmp_path, monkeypatch, artifact):
    import batterylog.interpretation_review as module

    source, context, target = inputs(tmp_path)
    original = Path.write_bytes
    original_text = Path.write_text

    def replaced(path, data):
        return original(path, data + b" " if path.name == artifact else data)

    def replaced_text(path, data, *args, **kwargs):
        return original_text(path, data + " " if path.name == artifact else data, *args, **kwargs)

    monkeypatch.setattr(module.Path, "write_bytes", replaced)
    monkeypatch.setattr(module.Path, "write_text", replaced_text)
    with pytest.raises(ValueError, match="changed before publication"):
        review_measurement(source, target, context_path=context)
    assert not target.exists()
    assert not list(tmp_path.glob(".batterylog-interpret-*"))


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_write_error_and_cancellation_leave_no_partial_output(tmp_path, monkeypatch, failure):
    source, context, target = inputs(tmp_path)
    original = Path.write_bytes

    def failed(path, data):
        if path.name == "effective-config.json":
            raise failure("stop")
        return original(path, data)

    monkeypatch.setattr(Path, "write_bytes", failed)
    with pytest.raises(failure):
        review_measurement(source, target, context_path=context)
    assert not target.exists()
    assert not list(tmp_path.glob(".batterylog-interpret-*"))


@pytest.mark.parametrize("exists_early", [True, False])
def test_existing_or_appearing_destination_is_preserved(tmp_path, monkeypatch, exists_early):
    import batterylog.interpretation_review as module

    source, context, target = inputs(tmp_path)

    def reserve():
        target.mkdir()
        (target / "keep").write_text("original")

    if exists_early:
        reserve()
    else:
        original = module._verify_artifacts

        def appears(directory, payload):
            original(directory, payload)
            reserve()

        monkeypatch.setattr(module, "_verify_artifacts", appears)
    with pytest.raises(ValueError, match="output (already exists|appeared)"):
        review_measurement(source, target, context_path=context)
    assert (target / "keep").read_text() == "original"
    assert list(target.iterdir()) == [target / "keep"]


@pytest.mark.parametrize(
    "data",
    [
        b"[]",
        b'{"measurement_context_schema_version":1,"chemistry":"LFP","chemistry":"NMC"}',
        b" " * (1024 * 1024 + 1),
    ],
)
def test_invalid_or_oversize_context_has_no_success_output(tmp_path, data):
    source, context, target = inputs(tmp_path)
    context.write_bytes(data)
    with pytest.raises(ValueError):
        review_measurement(source, target, context_path=context)
    assert not target.exists()


def test_missing_context_file_and_invalid_config_are_rejected(tmp_path):
    source, context, target = inputs(tmp_path)
    context.unlink()
    with pytest.raises(FileNotFoundError):
        review_measurement(source, target, context_path=context)
    with pytest.raises(TypeError, match="config"):
        review_measurement(source, target, config={})
    assert not target.exists()


def test_input_directory_and_unsupported_format_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="one CSV"):
        review_measurement(tmp_path, tmp_path / "out")
    source = tmp_path / "data.txt"
    source.write_bytes(DATA)
    with pytest.raises(ValueError, match="one CSV"):
        review_measurement(source, tmp_path / "out")


def test_result_v9_failure_model_evidence_remains_byte_identical(tmp_path):
    source, context, target = inputs(tmp_path)
    config = ValidationConfig(
        failure_models=FailureModelConfig(2, sustained_imbalance=SustainedImbalanceConfig(0.05, 1))
    )
    original = render_json_result(AnalysisService(config).analyze_path(source).result)
    assert json.loads(original)["schema_version"] == 9
    assert json.loads(original)["validation_status"] == "FAIL"
    bundle = review_measurement(source, target, context_path=context, config=config)
    assert bundle.result_json == original
    assert (target / "result.json").read_bytes() == original.encode()
    assert bundle.engineering_status == "FAIL"


def test_dangling_output_symlink_is_not_followed(tmp_path):
    source, _, target = inputs(tmp_path)
    try:
        target.symlink_to(tmp_path / "unrelated")
    except (OSError, NotImplementedError):
        pytest.skip("This runner cannot create symlinks")
    with pytest.raises(ValueError, match="already exists"):
        review_measurement(source, target)
    assert target.is_symlink()
    assert not (tmp_path / "unrelated").exists()
