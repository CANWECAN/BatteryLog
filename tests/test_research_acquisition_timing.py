"""Acquire-time counterexamples; source observation is not physical diagnosis."""

from __future__ import annotations

import io

import pytest

from batterylog_research.voltage_step_audit import audit_voltage_csv


def _delayed_uniform_pack(n: int, delayed: int):
    """Every cell drops 200mV physically at t=1; some channels publish at t=2."""
    old = [3.8] * n
    new = [3.6] * n
    # This is a row-based zero-order-hold artifact, not a cell failure.
    after_one = [old[i] if i < delayed else new[i] for i in range(n)]
    header = ["timestamp_s", *(f"cell_{i}_v" for i in range(1, n + 1)), "pack_current_a"]
    rows = [[0, *old, 0], [1, *after_one, 100], [2, *new, 100]]
    stream = io.StringIO(
        "\n".join([",".join(header), *(",".join(map(str, row)) for row in rows)]) + "\n"
    )
    return audit_voltage_csv(stream, peer_step_threshold_v=0.05, max_gap_s=1.0, max_examples=4)


@pytest.mark.parametrize("n", [3, 4, 8, 12, 16, 48, 96])
@pytest.mark.parametrize("fraction", [0, 1, 2, 3, 4, 5, 6, 7])
def test_asynchronous_zoh_can_invent_peer_step_observations(n: int, fraction: int):
    late_options = [0, 1, 2, n // 4, n // 2, (n + 1) // 2, n - 1, n]
    delayed = late_options[fraction]
    result = _delayed_uniform_pack(n, delayed)
    assert result["eligible_sample_pairs"] == 2
    assert result["rows_read"] == 3
    assert result["source_has_current"] is True
    assert result["diagnostic_claim"] is False
    if n % 2 == 0 and delayed == n // 2:
        assert result["ambiguous_peer_reference_pairs"] == 2
        assert result["cell_step_observations_flagged"] == 0
    else:
        assert result["ambiguous_peer_reference_pairs"] == 0
        assert result["cell_step_observations_flagged"] == 2 * min(delayed, n - delayed)
    # This is an observational candidate count, not a field false-positive rate.


def test_late_single_channel_generates_two_events_with_different_current_evidence():
    result = _delayed_uniform_pack(12, 1)
    assert result["cell_step_observations_flagged"] == 2
    assert [event["delta_current_a"] for event in result["examples"]] == [100.0, 0.0]
    assert [event["signal"] for event in result["examples"]] == ["cell_1_v", "cell_1_v"]


def test_a_quarter_of_96_channels_delayed_creates_48_spurious_observations():
    result = _delayed_uniform_pack(96, 24)
    assert result["cell_step_observations_flagged"] == 48
    assert result["ambiguous_peer_reference_pairs"] == 0
    assert len(result["examples"]) == 4


def test_common_mode_synchronous_step_stays_unflagged_at_two_different_times():
    for late in (0, 96):
        result = _delayed_uniform_pack(96, late)
        assert result["cell_step_observations_flagged"] == 0
        assert result["ambiguous_peer_reference_pairs"] == 0
