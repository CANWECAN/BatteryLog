"""Artifact allowlist must not accept candidate Research builds as published Core."""

import hashlib

import pytest

from scripts.validation import check_approved_core_release as policy


def test_release_pins_use_expected_official_github_asset_digests():
    assert policy._APPROVED_SHA256 == {
        "batterylog-0.10.0-py3-none-any.whl": "5ccef6874811c955f3a2d2c082113d95a6afd1c1b2349b1a0ebcad619fcaff41",
        "batterylog-0.10.0.tar.gz": "d417d7ba44a324fbb890114230b60678d1db014f8a9bbef329f808c89cdbb0ab",
    }


@pytest.mark.parametrize(
    "name",
    [
        "batterylog-0.11.0-py3-none-any.whl",
        "batterylog-0.11.0.tar.gz",
        "BatteryLog-0.10.0.tar.gz",
        "research-0.10.0.tar.gz",
        "batterylog-0.10.0-py3-none-any.whl.zip",
    ],
)
def test_unknown_names_rejected_even_with_archive_payload(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"anything")
    ok, detail = policy.approved_core_artifact(path)
    assert not ok and "Not an approved" in detail


@pytest.mark.parametrize("name", tuple(policy._APPROVED_SHA256))
def test_tampered_official_name_rejected(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"looks like the real package but is not")
    ok, detail = policy.approved_core_artifact(path)
    assert not ok and "Checksum mismatch" in detail


def test_missing_approved_name_does_not_pass(tmp_path):
    ok, message = policy.approved_core_artifact(tmp_path / "batterylog-0.10.0-py3-none-any.whl")
    assert not ok and "Cannot read" in message


def test_pinned_digest_must_match_entire_file_not_just_filename(tmp_path, monkeypatch):
    payload = b"tiny synthetic artifact"
    path = tmp_path / "batterylog-0.10.0.tar.gz"
    path.write_bytes(payload)
    monkeypatch.setitem(policy._APPROVED_SHA256, path.name, hashlib.sha256(payload).hexdigest())
    assert policy.approved_core_artifact(path)[0]
    with path.open("ab") as file:
        file.write(b"\nappended hidden content")
    assert not policy.approved_core_artifact(path)[0]


def test_cli_checks_all_artifacts_and_exits_on_any_failure(tmp_path, capsys, monkeypatch):
    name = "batterylog-0.10.0.tar.gz"
    payload = b"approved fixture"
    monkeypatch.setitem(policy._APPROVED_SHA256, name, hashlib.sha256(payload).hexdigest())
    good = tmp_path / name
    bad = tmp_path / "batterylog-0.11.0.tar.gz"
    good.write_bytes(payload)
    bad.write_bytes(payload)
    assert policy.main([str(good), str(bad)]) == 1
    output = capsys.readouterr().out
    assert "PASS:" in output and "BLOCKED:" in output


def test_zero_approved_artifacts_not_silently_treated_as_success(tmp_path):
    assert policy.main([str(tmp_path / "nonexistent-file.whl")]) == 1
