"""Small execution of the larger reproducible authored-byte stress campaign."""

import json

import pytest

pytest.importorskip("cantools")

from batterylog_research.can_boundary_stress import DBC, run


def test_exact_boundary_campaign_runs_and_preserves_saved_evidence(tmp_path):
    destination = tmp_path / "stress"
    result = run(destination, cycles=3)
    assert result["frames_input"] == 12
    assert result["canonical_rows_checked_independently"] == 6
    assert result["frames_at_exact_age_boundary"] == 3
    assert result["frames_one_nanosecond_past_age_boundary"] == 3
    assert not result["diagnostic_claim"]
    assert json.loads((destination / "summary.json").read_text()) == result
    assert (destination / "stress.dbc").read_bytes() == DBC.encode("utf-8")
    for name in ("profile.json", "prepared/alignment.jsonl", "prepared/preparation.json"):
        assert b"\r\n" not in (destination / name).read_bytes()
    with pytest.raises(FileExistsError):
        run(destination, cycles=3)


@pytest.mark.parametrize("cycles", [0, -1, True, 1.5])
def test_invalid_campaign_size_creates_no_files(tmp_path, cycles):
    destination = tmp_path / "stress"
    with pytest.raises((TypeError, ValueError), match="positive integer"):
        run(destination, cycles=cycles)
    assert not destination.exists()


@pytest.mark.parametrize("interval", [1, 2, 7])
def test_declared_raw_rejection_campaign_preserves_missing_and_receipt_identity(tmp_path, interval):
    result = run(tmp_path / "stress", cycles=7, invalid_every=interval)
    assert result["declared_raw_invalid_context_frames"] == (7 + interval - 1) // interval
    assert result["canonical_rows_checked_independently"] == 14


@pytest.mark.parametrize("interval", [0, -1, True, 1.5])
def test_invalid_raw_rejection_interval_creates_no_files(tmp_path, interval):
    with pytest.raises(ValueError, match="invalid_every"):
        run(tmp_path / "stress", cycles=2, invalid_every=interval)
    assert not (tmp_path / "stress").exists()
