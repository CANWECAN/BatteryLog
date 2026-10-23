"""Independent peer-context calculation: continuity, consensus and grouping."""

import csv
import io

import numpy as np

from batterylog_research.field_episode_review import clusters, observe_pairs, sampled_run
from batterylog_research.voltage_step_audit import audit_voltage_csv


def test_array_context_matches_csv_observer_at_threshold_duplicates_and_gap():
    times = np.array([0, 5, 5, 10, 71, 76, 81], dtype=float)
    volts = np.full((len(times), 8), 3.0)
    volts[:, 0] += [0, 0.05, 0.8, 0.86, 0.9, 1, 1.1]
    eligible, _, flagged = observe_pairs(times, volts)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["timestamp_s", *(f"cell_{i}_v" for i in range(1, 9))])
    writer.writerows(zip(times, *volts.T, strict=True))
    stream.seek(0)
    reference = audit_voltage_csv(stream, peer_step_threshold_v=0.05, max_gap_s=60)
    assert eligible.tolist() == [True, False, True, False, True, True]
    assert int(flagged.sum()) == reference["cell_step_observations_flagged"] == 3
    assert [int(i) + 3 for i in np.flatnonzero(flagged[:, 0])] == [
        e["csv_row"] for e in reference["examples"]
    ]


def test_backwards_time_and_split_peer_population_are_not_attributed():
    times = np.array([0, 5, 4, 9], dtype=float)
    volts = np.full((4, 8), 3.0)
    volts[1, :4] = 3.2  # Equal groups: no strict majority within 0.05 V.
    volts[2, 0] = 3.5  # Backward source time is ineligible for pair review.
    volts[3, 0] = 3.6
    eligible, _, flagged = observe_pairs(times, volts)
    assert eligible.tolist() == [True, False, True]
    assert not flagged[:2].any()
    assert flagged[2].tolist() == [True, False, False, False, False, False, False, False]


def test_review_groups_cannot_bridge_ineligible_pairs():
    times = np.array([0, 5, 5, 10, 15, 20], dtype=float)
    eligible = np.array([True, False, True, True, True])
    flagged = np.array([True, False, True, False, True])
    assert clusters(times, eligible, flagged, 60) == {
        "groups": 2,
        "largest_observation_count": 2,
    }
    assert clusters(times, eligible, flagged, 5)["groups"] == 3


def test_sampled_voltage_run_does_not_fill_duplicate_or_large_gap():
    times = np.array([0, 5, 5, 10, 75], dtype=float)
    run = sampled_run(times, np.array([False, True, True, True, True]), 2)
    assert run == {
        "first_source_data_row": 3,
        "last_source_data_row": 4,
        "sample_count": 2,
        "observed_sample_span_s": 5.0,
        "previous_neighbor_interval_s": 0.0,
        "next_neighbor_interval_s": 65.0,
    }
