"""Block raw third-party data, internal notes and unsafe wheel/sdist entries.

This scanner is a release *preflight*, not a complete proof of source provenance:
new Core builds additionally need approved source review and full CI.
"""

from __future__ import annotations

import argparse
import stat
import tarfile
import zipfile
from pathlib import Path


def _forbidden(member: str) -> bool:
    # Reject traversal, platform-specific separators and absolute paths instead
    # of leaving ambiguity between archive scanners and unpacking tools.
    if not member or "\\" in member or member.startswith("/") or ":" in member.split("/")[0]:
        return True
    pieces = member.split("/")
    if any(part in ("", "..") for part in pieces):
        return True
    if pieces[0] == ".":
        pieces = pieces[1:]
    # Archive wrappers can add one or several directories. Inspect all suffixes,
    # not just a single sdist-style top-level package prefix.
    for i in range(len(pieces)):
        name = "/".join(pieces[i:])
        lower = name.lower()
        if (
            name.startswith("docs/BUG_HUNT_")
            or name == "docs/RESEARCH_ACCESS_TERMS_DRAFT.md"
            or any(
                part.lower() in {"downloads", "raw_data", "third_party_data"} for part in pieces[i:]
            )
            or lower.endswith(
                (".dbc", ".log", ".blf", ".mf4", ".mdf", ".parquet", ".pcap", ".pcapng")
            )
            or name
            in {
                "batterylog_research/packaging/build_candidate.py",
                "batterylog_research/packaging/verify_candidate.py",
            }
        ):
            return True
    return False


def scan_archive(path: Path) -> list[str]:
    """Find forbidden entries; reject missing, malformed, or unsupported archives."""
    if not path.is_file():
        raise ValueError(f"Missing archive: {path}")
    try:
        if path.name.endswith(".tar.gz"):
            flagged: list[str] = []
            with tarfile.open(path, mode="r:gz") as archive:
                for member in archive:
                    if member.isdir():
                        continue
                    if not member.isfile():
                        flagged.append(f"Unsupported archive entry: {member.name}")
                    elif _forbidden(member.name):
                        flagged.append(member.name)
            return flagged
        if path.name.endswith(".whl"):
            with zipfile.ZipFile(path) as archive:
                return [
                    item.filename
                    for item in archive.infolist()
                    if not item.is_dir()
                    and (
                        stat.S_IFMT(item.external_attr >> 16) == stat.S_IFLNK
                        or _forbidden(item.filename)
                    )
                ]
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid distribution archive {path}: {exc}") from exc
    raise ValueError(f"Expected a built .tar.gz or .whl artifact: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args(argv)
    failure = False
    for artifact in args.artifacts:
        try:
            blocked = scan_archive(artifact)
        except ValueError as exc:
            print(f"BLOCKED: {exc}")
            failure = True
            continue
        if blocked:
            print(f"BLOCKED: excluded or unsafe path(s) in {artifact}:")
            for member in blocked:
                print(f"  {member}")
            failure = True
        else:
            print(f"OK: no excluded or unsafe paths in {artifact}")
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
