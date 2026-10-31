"""Publish an opt-in, source-bound interpretation beside an unchanged result."""

import hashlib
import json
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from .analysis.service import AnalysisService
from .config import ValidationConfig
from .interpretation import InterpretationReport
from .measurement_context import MAX_CONTEXT_BYTES, load_measurement_context_bytes
from .models import ValidationStatus
from .parallel_context import ParallelBranchAssessment
from .reporting import render_json_result, verify_file_unchanged
from .reporting.evidence import FileEvidence, capture_file_backed_snapshot, sha256_file
from .reporting.interpretation import render_interpretation_report
from .voltage_context import VoltageSpreadAssessment


def _json_text(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


def _artifact(path: str, data: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


def _source_identity(evidence: FileEvidence) -> dict:
    return {"name": evidence.name, "sha256": evidence.sha256, "size_bytes": evidence.size_bytes}


@dataclass(frozen=True)
class InterpretationBundle:
    """Published JSON texts; exports cannot mutate the saved evidence."""

    output_directory: Path
    result_json: str
    interpretation_json: str

    @property
    def engineering_status(self) -> ValidationStatus:
        return cast(ValidationStatus, self.to_dict()["engineering_status"])

    def to_dict(self) -> dict:
        return json.loads(self.interpretation_json)


def _verify_artifacts(directory: Path, review: dict) -> None:
    for key in ("result", "effective_config", "context"):
        artifact = review["binding"][key]
        if artifact is not None:
            path = directory / artifact["path"]
            if (
                path.stat().st_size != artifact["size_bytes"]
                or sha256_file(path) != artifact["sha256"]
            ):
                raise ValueError(f"Interpretation artifact changed before publication: {key}")


def review_measurement(
    input_path: str | Path,
    output_directory: str | Path,
    *,
    context_path: str | Path | None = None,
    config: ValidationConfig | None = None,
) -> InterpretationBundle:
    """Analyze one captured file and publish all evidence or no completed bundle.

    No external engineering result is accepted. The existing engine analyzes the
    captured source with the supplied effective config. Hash association does not
    verify channel mappings, physical metadata or diagnostic sufficiency. Raw
    YAML provenance is not claimed; effective settings are captured separately.
    """
    if config is not None and type(config) is not ValidationConfig:
        raise TypeError("config must be a ValidationConfig or None")
    effective = config if config is not None else ValidationConfig()
    source = Path(input_path).resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in {".csv", ".mf4", ".mdf"}:
        raise ValueError("Interpretation review requires one CSV, MDF or MF4 file")
    requested_target = Path(output_directory).absolute()
    if requested_target.is_symlink() or requested_target.exists():
        raise ValueError("Interpretation output already exists; choose a new directory")
    target = requested_target.resolve()
    context_source = Path(context_path).resolve(strict=True) if context_path is not None else None
    config_bytes = _json_text(asdict(effective)).encode("utf-8")

    with ExitStack() as stack:
        source_snapshot = stack.enter_context(capture_file_backed_snapshot(source))
        context_snapshot = (
            stack.enter_context(capture_file_backed_snapshot(context_source))
            if context_source is not None
            else None
        )
        context_bytes = None
        context = None
        if context_snapshot is not None:
            if context_snapshot.evidence.size_bytes > MAX_CONTEXT_BYTES:
                raise ValueError("Measurement context exceeds 1 MiB")
            context_bytes = context_snapshot.handle.read(MAX_CONTEXT_BYTES + 1)
            context = load_measurement_context_bytes(context_bytes)
        output = AnalysisService(effective).analyze_file(
            source_snapshot.handle, source_name=source.name
        )
        result = output.result
        result_text = render_json_result(result)
        result_bytes = result_text.encode("utf-8")
        # Derive the observation view from detached result JSON; never alter result-v8/v9.
        observations = json.loads(result_text)
        baseline = InterpretationReport(result["validation_status"]).to_dict()
        review = {
            "interpretation_review_schema_version": 1,
            "scope": "source_bound_interpretation_limits",
            "engineering_status": result["validation_status"],
            "physical_interpretation_status": "NOT_EVALUATED",
            "diagnostic_claim": False,
            "measurement_properties_verified": False,
            "context_evidence_level": "DECLARED" if context is not None else "NOT_SUPPLIED",
            "binding": {
                "kind": "same_snapshot_analysis_and_exact_artifact_hashes",
                "source": _source_identity(source_snapshot.evidence),
                "result": _artifact("result.json", result_bytes),
                "context": (
                    {
                        **_artifact("context.json", context_bytes),
                        "original_name": context_snapshot.evidence.name,
                    }
                    if context_bytes is not None and context_snapshot is not None
                    else None
                ),
                "effective_config": _artifact("effective-config.json", config_bytes),
                "source_channel_mapping_verified": False,
            },
            "observations": {
                "max_delta_v": observations["max_delta_v"],
                "voltage_spread_limit_v": observations["limits_applied"]["imbalance_max_v"],
                "rules_evaluated": observations["rules_evaluated"],
                "violations": observations["violations"],
                "data_quality_events": observations["data_quality"]["events"],
                "failure_models": observations.get("failure_models"),
            },
            "claims": [
                VoltageSpreadAssessment(context).to_dict(),
                ParallelBranchAssessment(context).to_dict(),
                baseline["claims"][2],
            ],
        }
        review_text = _json_text(review)
        html_text = render_interpretation_report(review)
        target.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=target.parent, prefix=".batterylog-interpret-") as temporary:
            completed = Path(temporary) / "completed"
            completed.mkdir()
            (completed / "result.json").write_bytes(result_bytes)
            (completed / "effective-config.json").write_bytes(config_bytes)
            if context_bytes is not None:
                (completed / "context.json").write_bytes(context_bytes)
            (completed / "interpretation.json").write_text(
                review_text, encoding="utf-8", newline="\n"
            )
            (completed / "interpretation.html").write_text(
                html_text, encoding="utf-8", newline="\n"
            )
            _verify_artifacts(completed, review)
            if (completed / "interpretation.json").read_bytes() != review_text.encode("utf-8"):
                raise ValueError("Interpretation JSON changed before publication")
            if (completed / "interpretation.html").read_bytes() != html_text.encode("utf-8"):
                raise ValueError("Interpretation HTML changed before publication")
            verify_file_unchanged(source, source_snapshot.evidence)
            if context_source is not None and context_snapshot is not None:
                verify_file_unchanged(context_source, context_snapshot.evidence)
            if target.exists() or target.is_symlink():
                raise ValueError("Interpretation output appeared during processing")
            completed.rename(target)
    return InterpretationBundle(target, result_text, review_text)
