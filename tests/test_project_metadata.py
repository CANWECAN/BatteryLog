import hashlib
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
OFFICIAL_APACHE_2_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"


def test_license_is_unmodified_official_apache_2_text() -> None:
    license_bytes = (ROOT / "LICENSE").read_bytes()

    assert hashlib.sha256(license_bytes).hexdigest() == OFFICIAL_APACHE_2_SHA256


def test_package_metadata_declares_apache_2() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    metadata = project["project"]

    assert metadata["license"] == "Apache-2.0"
    assert metadata["license-files"] == ["LICENSE", "NOTICE"]
    assert {"name": "Berk Ozfiliz"} in metadata["authors"]
    assert "setuptools>=77" in project["build-system"]["requires"]
    assert project["project"]["optional-dependencies"]["mf4"] == ["asammdf>=8.8,<9"]


def test_notice_records_project_attribution() -> None:
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")

    assert "BatteryLog" in notice
    assert "Copyright 2026 Berk Ozfiliz" in notice
    assert "https://github.com/CANWECAN/BatteryLog" in notice


def test_citation_metadata_matches_package_identity() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))

    assert citation["cff-version"] == "1.2.0"
    assert citation["title"] == "BatteryLog"
    assert citation["type"] == "software"
    assert citation["license"] == "Apache-2.0"
    assert citation["version"] == project["project"]["version"]
    assert citation["repository-code"] == "https://github.com/CANWECAN/BatteryLog"
    assert {
        "family-names": "Ozfiliz",
        "given-names": "Berk",
    } in citation["authors"]
