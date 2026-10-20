"""Symmetric binary64 boundary parity and the three retained CORA rejections."""

import json
from math import isclose
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from batterylog_research.cora_temporal_review import COLUMNS, review_branch
from batterylog_research.temporal_characterization import REL, above


def test_vector_comparison_matches_symmetric_scalar_policy_at_boundaries():
    values, limits = [], []
    for limit in (-1e300, -2.0, -0.25, 0.0, 0.25, 2.0, 1e300):
        for direction in (-np.inf, np.inf):
            value = limit
            for _ in range(33):
                values.append(value)
                limits.append(limit)
                value = float(np.nextafter(value, direction))
    expected = [
        value > limit and not isclose(value, limit, rel_tol=REL, abs_tol=0)
        for value, limit in zip(values, limits, strict=True)
    ]
    np.testing.assert_array_equal(above(np.array(values), np.array(limits)), expected)


@pytest.mark.parametrize("case_index,expected_count", [(98, 47), (109, 52), (135, 18)])
def test_retained_exact_source_fixture_now_matches_core(case_index, expected_count):
    evidence = Path(__file__).parents[1] / (
        "batterylog_research/kali_step2_validation_results_20261014.json"
    )
    cases = json.loads(evidence.read_text())["guard_comparison"]["rejection_examples"]
    case = next(item for item in cases if item["case_index"] == case_index)
    frame = pd.DataFrame(case["source_fixture"])[COLUMNS]
    before = frame.copy(deep=True)
    report = review_branch(frame)
    pd.testing.assert_frame_equal(frame, before)
    assert report["temperature"]["adjacent"]["eligible_observations"] == expected_count
    assert report["core"]["TEMPERATURE_RISE_HIGH"]["evaluated_samples"] == expected_count
    assert (
        report["temperature"]["adjacent"]["exceeding_observations"]
        == (case["temperature_counts"]["core_exceeding"])
    )
    assert (
        report["core"]["CELL_SAG_UNDER_LOAD"]["evaluated_samples"]
        == (case["sag_counts"]["core_evaluated"])
    )
    json.dumps(report, allow_nan=False)


def branch(times, current):
    size = len(times)
    values = {
        "timestamp_s": times,
        "pack_current_a": current,
        "pack_voltage_v": [42.0] * size,
    }
    values.update({f"cell_{i}_v": [3.5] * size for i in range(1, 13)})
    values.update({f"temp_{i}_c": [25.0] * size for i in range(1, 25)})
    return pd.DataFrame(values)[COLUMNS]


def test_lower_load_boundary_uses_same_symmetric_policy():
    discharge = 2 - REL * 2
    report = review_branch(
        branch([0, 1, 2, 3, 4, 5], [0, 0, 0, -discharge, -discharge, -discharge])
    )
    assert report["sag_context"]["episodes"][0]["eligible_samples"] == 2
    assert report["core"]["CELL_SAG_UNDER_LOAD"]["evaluated_samples"] == 2


def test_lower_settling_boundary_uses_same_symmetric_policy():
    times = [0, 0.25, 0.75 - REL * 0.5, 1.25, 1.75, 2.25]
    report = review_branch(branch(times, [0, -3, -3, -3, -3, -3]))
    assert report["sag_context"]["episodes"][0]["eligible_samples"] == 4
    assert report["core"]["CELL_SAG_UNDER_LOAD"]["evaluated_samples"] == 4
