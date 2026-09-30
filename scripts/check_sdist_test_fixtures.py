"""Verify that source distributions preserve the complete test corpus."""

import argparse
import tarfile
from pathlib import Path


def check_sdist_test_fixtures(archive_path: Path) -> None:
    source_tests = Path(__file__).resolve().parents[1] / "tests"
    with tarfile.open(archive_path) as archive:
        roots = {name.split("/", 1)[0] for name in archive.getnames()}
        if len(roots) != 1:
            raise ValueError("Source distribution must contain one top-level directory")
        root = roots.pop()
        for source in sorted(source_tests.rglob("*")):
            if not source.is_file() or source.suffix not in {".py", ".json", ".md"}:
                continue
            member_name = f"{root}/tests/{source.relative_to(source_tests).as_posix()}"
            try:
                member = archive.extractfile(member_name)
            except KeyError as exc:
                raise ValueError(
                    f"Source distribution omits test corpus file: {member_name}"
                ) from exc
            if member is None or member.read() != source.read_bytes():
                raise ValueError(f"Source distribution changed test corpus file: {member_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    check_sdist_test_fixtures(parser.parse_args().archive)
