# Copyright (c) 2026 Berk Ozfiliz.
# SPDX-License-Identifier: Apache-2.0
"""Original phase/time classification must survive binary64 conversion."""

import json

import numpy as np
import pytest

from batterylog_research.precharge_capture_review import review_precharge_capture
from batterylog_research.precharge_curve_review import review_precharge_curve

ENVELOPE = [[0, 0, 2, 0, 0.2], [2, 0, 2, 0, 0.2]]
INTERFACES = [review_precharge_curve, review_precharge_capture]


@pytest.mark.parametrize("direction", ["above_one", "above_zero"])
def test_unknown_phase_is_classified_before_conversion(direction):
    edge = np.nextafter(np.longdouble(1 if direction == "above_one" else 0), np.longdouble(2))
    phase = np.array([0, edge, edge, edge], dtype=np.longdouble)
    original = phase.copy()
    result = review_precharge_capture(
        [-0.1, 0, 1, 2], phase, [1] * 4, [100] * 4, [90] * 4, ENVELOPE, max_gap_s=1
    )
    assert result["unknown_phase_samples"] == 3
    assert result["observed_activations"] == 0
    assert result["covered_reference_intervals"] == 0
    assert result["active_spans"] == []
    np.testing.assert_array_equal(phase, original)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("interface", INTERFACES)
def test_rounded_unknown_phase_cannot_bridge_an_earlier_deviation(interface):
    unknown = np.nextafter(np.longdouble(1), np.longdouble(2))
    phase = np.array([0, 1, unknown, 1, 1], dtype=np.longdouble)
    result = interface(
        [-0.1, 0, 0.5, 1, 2],
        phase,
        [1, 3, 1, 1, 1],
        [100] * 5,
        [90] * 5,
        ENVELOPE,
        max_gap_s=1,
    )
    assert result["reviewed_samples"] == 1
    assert result["outside_envelope_samples"] == 1
    if interface is review_precharge_capture:
        assert result["covered_reference_intervals"] == 0
        assert result["unknown_phase_samples"] == 1
        assert result["unobserved_active_spans"] == 1
        assert result["active_spans"][0]["examples"][0]["sample_index"] == 1
    else:
        assert not result["declared_interval_covered"]
        assert "unknown_phase_sample" in result["incomplete_reasons"]
        assert result["examples"][0]["sample_index"] == 1


@pytest.mark.parametrize("dtype", [np.int64, np.uint64, np.longdouble])
@pytest.mark.parametrize("interface", INTERFACES)
def test_original_descending_time_is_rejected_even_if_float_rounding_hides_it(dtype, interface):
    if dtype is np.longdouble:
        time = np.array([np.nextafter(np.longdouble(1), np.longdouble(2)), 1], dtype=dtype)
    else:
        time = np.array([2**53 + 1, 2**53], dtype=dtype)
    with pytest.raises(ValueError, match="nondecreasing source time"):
        interface(time, [0, 1], [1, 1], [100] * 2, [90] * 2, ENVELOPE, max_gap_s=1)


@pytest.mark.parametrize("interface", INTERFACES)
def test_ascending_time_lost_to_float_rounding_remains_unqualified(interface):
    time = np.array([2**53, 2**53 + 1], dtype=np.int64)
    result = interface(time, [0, 1], [1, 1], [100] * 2, [90] * 2, ENVELOPE, max_gap_s=1)
    assert result["reviewed_samples"] == 0
    if interface is review_precharge_capture:
        assert result["observed_activations"] == 0
        assert result["covered_reference_intervals"] == 0
    else:
        assert not result["declared_interval_covered"]
