import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


@dataclass(frozen=True)
class FileEvidence:
    name: str
    sha256: str
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True)
class FileSnapshot:
    data: bytes
    evidence: FileEvidence


@dataclass(frozen=True)
class ReportMetadata:
    batterylog_version: str
    generated_at_utc: str
    source: FileEvidence
    config: FileEvidence | None = None


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_file_snapshot(path: str | Path) -> FileSnapshot:
    file_path = Path(path)
    before = file_path.stat()
    data = file_path.read_bytes()
    after = file_path.stat()

    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ValueError(f"Evidence file changed while snapshotting: {file_path.name}")
    if len(data) != after.st_size:
        raise ValueError(f"Evidence file size changed while snapshotting: {file_path.name}")

    evidence = FileEvidence(
        name=file_path.name,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        mtime_ns=after.st_mtime_ns,
    )
    return FileSnapshot(data=data, evidence=evidence)


def capture_file_evidence(path: str | Path) -> FileEvidence:
    return capture_file_snapshot(path).evidence


def verify_file_unchanged(path: str | Path, evidence: FileEvidence) -> None:
    current = capture_file_evidence(path)
    if current.sha256 != evidence.sha256:
        raise ValueError(f"Evidence file changed during analysis: {evidence.name}")


def _installed_version() -> str:
    try:
        return version("batterylog")
    except PackageNotFoundError:
        return "unknown"


def build_report_metadata(
    source: FileEvidence,
    config: FileEvidence | None = None,
    *,
    generated_at: datetime | None = None,
) -> ReportMetadata:
    instant = generated_at or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")

    generated_at_utc = instant.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return ReportMetadata(
        batterylog_version=_installed_version(),
        generated_at_utc=generated_at_utc,
        source=source,
        config=config,
    )
