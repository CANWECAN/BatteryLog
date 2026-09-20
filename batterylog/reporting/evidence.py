import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryFile
from typing import BinaryIO

_COPY_CHUNK_BYTES = 1024 * 1024


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
class FileBackedSnapshot:
    handle: BinaryIO
    evidence: FileEvidence


@dataclass(frozen=True)
class ReportMetadata:
    batterylog_version: str
    generated_at_utc: str
    source: FileEvidence
    config: FileEvidence | None = None


def _stream_hash(
    source: BinaryIO,
    *,
    destination: BinaryIO | None = None,
) -> tuple[str, int]:
    digest = hashlib.sha256()
    size_bytes = 0

    for chunk in iter(lambda: source.read(_COPY_CHUNK_BYTES), b""):
        digest.update(chunk)
        size_bytes += len(chunk)
        if destination is not None:
            destination.write(chunk)

    return digest.hexdigest(), size_bytes


def sha256_file(path: str | Path) -> str:
    with Path(path).open("rb") as handle:
        digest, _ = _stream_hash(handle)
    return digest


def _evidence_from_stable_read(
    file_path: Path,
    *,
    digest: str,
    size_bytes: int,
    before_size: int,
    before_mtime_ns: int,
    after_size: int,
    after_mtime_ns: int,
) -> FileEvidence:
    if before_size != after_size or before_mtime_ns != after_mtime_ns:
        raise ValueError(f"Evidence file changed while snapshotting: {file_path.name}")
    if size_bytes != after_size:
        raise ValueError(f"Evidence file size changed while snapshotting: {file_path.name}")

    return FileEvidence(
        name=file_path.name,
        sha256=digest,
        size_bytes=size_bytes,
        mtime_ns=after_mtime_ns,
    )


def capture_file_snapshot(path: str | Path) -> FileSnapshot:
    file_path = Path(path)
    before = file_path.stat()
    data = file_path.read_bytes()
    after = file_path.stat()

    evidence = _evidence_from_stable_read(
        file_path,
        digest=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        before_size=before.st_size,
        before_mtime_ns=before.st_mtime_ns,
        after_size=after.st_size,
        after_mtime_ns=after.st_mtime_ns,
    )
    return FileSnapshot(data=data, evidence=evidence)


@contextmanager
def capture_file_backed_snapshot(path: str | Path) -> Iterator[FileBackedSnapshot]:
    file_path = Path(path)

    with file_path.open("rb") as source, TemporaryFile(mode="w+b") as snapshot_file:
        snapshot_handle = getattr(snapshot_file, "file", snapshot_file)
        before = os.fstat(source.fileno())
        digest, size_bytes = _stream_hash(source, destination=snapshot_handle)
        after = os.fstat(source.fileno())

        evidence = _evidence_from_stable_read(
            file_path,
            digest=digest,
            size_bytes=size_bytes,
            before_size=before.st_size,
            before_mtime_ns=before.st_mtime_ns,
            after_size=after.st_size,
            after_mtime_ns=after.st_mtime_ns,
        )
        snapshot_handle.flush()
        snapshot_handle.seek(0)
        yield FileBackedSnapshot(handle=snapshot_handle, evidence=evidence)


def capture_file_evidence(path: str | Path) -> FileEvidence:
    file_path = Path(path)
    with file_path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        digest, size_bytes = _stream_hash(handle)
        after = os.fstat(handle.fileno())

    return _evidence_from_stable_read(
        file_path,
        digest=digest,
        size_bytes=size_bytes,
        before_size=before.st_size,
        before_mtime_ns=before.st_mtime_ns,
        after_size=after.st_size,
        after_mtime_ns=after.st_mtime_ns,
    )


def verify_file_unchanged(path: str | Path, evidence: FileEvidence) -> None:
    current_sha256 = sha256_file(path)
    if current_sha256 != evidence.sha256:
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
