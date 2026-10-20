"""Conservative peer-step observations: no physical fault classifications."""

import io
import math
import random

import pytest

from batterylog_research.voltage_step_audit import audit_voltage_csv


def inspect(steps, *, threshold=0.04, gap=1.0, current=True, max_examples=4):
    cells = len(steps[0]) - (2 if current else 1)
    header = "timestamp_s," + ",".join(f"cell_{i}_v" for i in range(1, cells + 1))
    if current:
        header += ",pack_current_a"
    csv = "\n".join([header, *[",".join(map(str, row)) for row in steps]]) + "\n"
    return audit_voltage_csv(
        io.StringIO(csv),
        peer_step_threshold_v=threshold,
        max_gap_s=gap,
        max_examples=max_examples,
    )


@pytest.mark.parametrize("n", [3, 4, 5, 8, 16, 96])
def test_one_cell_change_detected_across_cell_counts(n):
    before = [3.5] * n
    after = [3.38] + [3.5] * (n - 1)
    result = inspect([[0, *before, 0], [1, *after, 0]])
    assert result["cell_step_observations_flagged"] == 1
    assert result["ambiguous_peer_reference_pairs"] == 0
    assert result["examples"][0]["signal"] == "cell_1_v"


@pytest.mark.parametrize("n", [3, 4, 5, 8, 16, 96])
def test_common_mode_shift_with_current_step_not_flagged(n):
    result = inspect([[0, *([3.5] * n), 0], [1, *([3.2] * n), 100]])
    assert result["cell_step_observations_flagged"] == 0
    assert result["ambiguous_peer_reference_pairs"] == 0


@pytest.mark.parametrize("n", [4, 8, 16, 96])
def test_even_split_cannot_establish_reference_majority(n):
    shifted = [3.2] * (n // 2) + [3.5] * (n // 2)
    result = inspect([[0, *([3.5] * n), 0], [1, *shifted, 0]])
    assert result["eligible_sample_pairs"] == 1
    assert result["cell_step_observations_flagged"] == 0
    assert result["ambiguous_peer_reference_pairs"] == 1
    assert result["examples"] == []


def test_five_cells_two_deviants_still_have_three_peers():
    result = inspect([[0, 3.5, 3.5, 3.5, 3.5, 3.5, 0], [1, 3.2, 3.2, 3.5, 3.5, 3.5, 100]])
    assert result["cell_step_observations_flagged"] == 2
    assert result["ambiguous_peer_reference_pairs"] == 0
    assert result["examples"][0]["delta_current_a"] == 100


def test_three_way_split_marks_unknown_not_healthy():
    result = inspect([[0, 3.5, 3.5, 3.5], [1, 3.5, 3.3, 3.1]], current=False)
    assert result["ambiguous_peer_reference_pairs"] == 1
    assert result["cell_step_observations_flagged"] == 0
    assert result["diagnostic_claim"] is False


def test_duplicate_and_gap_are_ineligible():
    result = inspect(
        [[0, 3.5, 3.5, 3.5, 3.5, 0], [0, 3.5, 3.2, 3.5, 3.5, 0], [4, 3.5, 3.2, 3.5, 3.5, 0]]
    )
    assert result["eligible_sample_pairs"] == 0
    assert result["continuity"] == {"duplicate_timestamps": 1, "gaps_beyond_limit": 1}


@pytest.mark.parametrize("bad", ["NaN", "Inf", "-Inf", "1e9999", "broken", ""])
def test_invalid_numeric_rejected(bad):
    with pytest.raises(ValueError):
        inspect([[0, 3.5, 3.5, 3.5, 3.5, 0], [1, bad, 3.5, 3.5, 3.5, 0]])


def test_seeded_oracle_majority_and_event_count():
    rng = random.Random(20261012)
    for n in (3, 4, 5, 8, 16):
        for _ in range(60):
            common = rng.choice([-0.2, 0.0, 0.13])
            changes = [common + rng.uniform(-0.01, 0.01) for _ in range(n)]
            for i in rng.sample(range(n), rng.randrange(n + 1)):
                changes[i] += rng.choice([-0.2, 0.2])
            base = [3.5] * n
            result = inspect([[0, *base, 0], [1, *[3.5 + d for d in changes], 20]])
            ordered = sorted(changes)
            center = n // 2
            median = ordered[center] if n % 2 else (ordered[center - 1] + ordered[center]) / 2
            supporters = sum(abs(d - median) <= 0.04 for d in changes)
            expected = sum(abs(d - median) > 0.04 for d in changes) if supporters > n // 2 else 0
            assert result["cell_step_observations_flagged"] == expected
            assert result["ambiguous_peer_reference_pairs"] == int(supporters <= n // 2)
            assert result["cell_step_observations_flagged"] <= n


def test_examples_cap_does_not_change_observation_counts():
    rows = [[t, 3.5, 3.5 if t % 2 == 0 else 3.35, 3.5, 3.5, 0] for t in range(101)]
    result = inspect(rows, max_examples=1)
    assert result["cell_step_observations_flagged"] == 100
    assert len(result["examples"]) == 1


def test_threshold_and_gap_exact_boundaries():
    result = inspect(
        [[0, 3.5, 3.5, 3.5, 3.5, 0], [math.nextafter(1.0, math.inf), 3.5, 3.3, 3.5, 3.5, 0]]
    )
    assert result["eligible_sample_pairs"] == 1
    assert result["cell_step_observations_flagged"] == 1
