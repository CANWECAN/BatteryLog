"""Accept only byte-identical artifacts from the approved public Core v0.10.0 release.

Digests are pinned from the GitHub v0.10.0 release asset API as of 2026-10-12.
This is a regression/republication gate, not a signature or a process for
approving new versions. Future releases require an explicit new approval.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

_APPROVED_SHA256 = {
    "batterylog-0.10.0-py3-none-any.whl": (
        "5ccef6874811c955f3a2d2c082113d95a6afd1c1b2349b1a0ebcad619fcaff41"
    ),
    "batterylog-0.10.0.tar.gz": (
        "d417d7ba44a324fbb890114230b60678d1db014f8a9bbef329f808c89cdbb0ab"
    ),
}


def approved_core_artifact(path: Path) -> tuple[bool, str]:
    """Check an exact release asset by filename and SHA-256, without unpacking it."""
    expected = _APPROVED_SHA256.get(path.name)
    if expected is None:
        return False, f"Not an approved Core v0.10.0 artifact: {path.name}"
    try:
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
    except OSError as exc:
        return False, f"Cannot read Core artifact {path}: {exc}"
    if digest != expected:
        return False, f"Checksum mismatch for {path.name} (expected {expected}, got {digest})"
    return True, f"Matches approved public Core v0.10.0 artifact: {path.name}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args(argv)
    failures = 0
    for artifact in args.artifacts:
        approved, detail = approved_core_artifact(artifact)
        print(("PASS: " if approved else "BLOCKED: ") + detail)
        failures += not approved
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
