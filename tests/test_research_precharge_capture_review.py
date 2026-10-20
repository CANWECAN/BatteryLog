# Copyright (c) 2026 Berk Ozfiliz.
# SPDX-License-Identifier: Apache-2.0
"""Capture boundaries, source traceability and conservative qualification."""

import json

import numpy as np
import pytest

from batterylog_research.precharge_capture_review import review_precharge_capture
from batterylog_research.precharge_curve_review import review_precharge_curve


def _source():
    return (
        np.array([-0.1, 0, 1, 2, 2.1, 3, 3.1, 4.1, 5.1, 5.2]),
        np.array([0, 1, 1, 1, 0, 0, 1, 1, 1, 0]),
        np.array([0, 1, 1, 1, 0, 0, 1, 3, 1, 0], dtype=float),
        np.full(10, 100.0),
        np.full(10, 90.0),
    )


def _envelope():
    return np.array([[0, 0, 2, 0, 0.2], [2, 0, 2, 0, 0.2]], dtype=float)


def _review(source=None, **kwargs):
    return review_precharge_capture(
        *(_source() if source is None else source), _envelope(), max_gap_s=1, **kwargs
    )


def test_two_observed_activations_are_independent_and_traceable():
    report = _review()
    assert report["observed_activations"] == 2
    assert report["covered_reference_intervals"] == 2
    assert report["unobserved_active_spans"] == 0
    assert report["reviewed_samples"] == 6
    assert report["outside_envelope_samples"] == 1
    first, second = report["active_spans"]
    assert first["source_active_start_index"] == 1
    assert first["source_active_stop_index_exclusive"] == 4
    assert first["source_review_start_index"] == 0
    assert first["source_review_stop_index_exclusive"] == 5
    assert first["observed_start_bracket_s"] == [-0.1, 0]
    assert second["source_active_start_index"] == 6
    assert second["source_active_stop_index_exclusive"] == 9
    assert second["source_review_start_index"] == 5
    assert second["source_review_stop_index_exclusive"] == 10
    assert second["observed_start_bracket_s"] == [3, 3.1]
    assert second["examples"][0]["sample_index"] == 7
    assert second["examples"][0]["current_a"] == 3


def test_single_observer_still_rejects_multiple_activations():
    with pytest.raises(ValueError, match="multiple observed activations"):
        review_precharge_curve(*_source(), _envelope(), max_gap_s=1)


@pytest.mark.parametrize("unknown", [np.nan, np.inf, -1, 2])
def test_unknown_phase_fragments_do_not_invent_or_resume_an_activation(unknown):
    time = np.array([-0.1, 0, 0.5, 1, 1.5, 2, 2.5, 3])
    source = (time, [0, 1, 1, unknown, 1, 1, 0, 1], np.ones(8), [100] * 8, [90] * 8)
    report = _review(source)
    assert len(report["active_spans"]) == 3
    assert report["observed_activations"] == 2
    assert report["unobserved_active_spans"] == 1
    assert report["unknown_phase_samples"] == 1
    assert report["covered_reference_intervals"] == 0
    first, orphan, later = report["active_spans"]
    assert "unknown_phase_sample" in first["incomplete_reasons"]
    assert orphan["observed_start_bracket_s"] is None
    assert orphan["reviewed_samples"] == 0
    assert later["observed_start_bracket_s"] == [2.5, 3]
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("kind", ["gap", "duplicate", "invalid_measurement"])
def test_interruption_does_not_heal_within_a_known_active_span(kind):
    time = np.array([-0.1, 0, 0.5, 1, 1.5, 2, 2.1])
    current = np.array([0, 3, 1, 1, 1, 1, 0], dtype=float)
    if kind == "gap":
        time[3:] += 3
    elif kind == "duplicate":
        time[3] = time[2]
    else:
        current[3] = np.nan
    source = (time, [0, 1, 1, 1, 1, 1, 0], current, [100] * 7, [90] * 7)
    report = _review(source)
    assert len(report["active_spans"]) == 1
    assert report["observed_activations"] == 1
    assert report["covered_reference_intervals"] == 0
    assert report["reviewed_samples"] == 2
    assert report["outside_envelope_samples"] == 1
    assert report["active_spans"][0]["examples"][0]["sample_index"] == 1


def test_left_censored_span_does_not_poison_a_later_observed_activation():
    report = _review(tuple(a[1:] for a in _source()))
    first, later = report["active_spans"]
    assert not first["activation_observed"]
    assert first["reviewed_samples"] == 0
    assert later["activation_observed"]
    assert later["declared_interval_covered"]
    assert later["examples"][0]["sample_index"] == 6
    assert report["observed_activations"] == 1
    assert report["covered_reference_intervals"] == 1


@pytest.mark.parametrize("kind", ["gap", "duplicate"])
def test_interrupted_onset_is_not_observed(kind):
    source = [a.copy() for a in _source()]
    if kind == "gap":
        source[0][6:] += 2
    else:
        source[0][6] = source[0][5]
    report = _review(source)
    first, later = report["active_spans"]
    assert first["declared_interval_covered"]
    assert not later["activation_observed"]
    assert later["reviewed_samples"] == 0
    assert report["unobserved_active_spans"] == 1


def test_early_phase_end_and_capture_end_remain_distinct():
    source = ([-0.1, 0, 0.5, 0.6, 1, 1.5], [0, 1, 1, 0, 0, 1], [1] * 6, [100] * 6, [90] * 6)
    first, later = _review(source)["active_spans"]
    assert "phase_ended_before_coverage_completed" in first["incomplete_reasons"]
    assert later["incomplete_reasons"] == ["capture_ended_before_reference_horizon"]


def test_capture_end_at_exact_horizon_can_cover_the_declared_interval():
    source = tuple(a[:4] for a in _source())
    report = _review(source)
    assert report["covered_reference_intervals"] == 1
    assert report["active_spans"][0]["reference_horizon_bracket_s"] == [2, 2]


def test_horizon_bracket_is_retained_without_comparing_later_source():
    source = (
        [-0.1, 0, 0.8, 1.6, 2.4, 2.5],
        [0, 1, 1, 1, 1, 0],
        [1, 1, 1, 1, 9, 0],
        [100] * 6,
        [90] * 6,
    )
    report = _review(source)
    span = report["active_spans"][0]
    assert span["reference_horizon_bracket_s"] == [1.6, 2.4]
    assert span["source_active_stop_index_exclusive"] == 5
    assert report["known_active_samples"] == 4
    assert report["reviewed_samples"] == 3
    assert report["outside_envelope_samples"] == 0


@pytest.mark.parametrize("phase", [[0, 0, 0], [np.nan, 2, np.inf]])
def test_no_active_rows_is_an_empty_inventory_not_a_complete_curve(phase):
    source = ([0, 1, 2], phase, [np.nan] * 3, [np.inf] * 3, [np.nan] * 3)
    report = _review(source)
    assert report["active_spans"] == []
    assert report["observed_activations"] == 0
    assert report["covered_reference_intervals"] == 0
    assert report["reviewed_samples"] == 0
    assert report["unknown_phase_samples"] == (3 if phase[0] != 0 else 0)
    json.dumps(report, allow_nan=False)


def test_boolean_phase_is_allowed_and_capture_inputs_are_immutable():
    source = list(_source())
    source[1] = source[1].astype(bool)
    copies = [a.copy() for a in source]
    envelope = _envelope()
    original_envelope = envelope.copy()
    report = review_precharge_capture(*source, envelope, max_gap_s=1)
    assert report["observed_activations"] == 2
    for actual, original in zip(source, copies, strict=True):
        np.testing.assert_array_equal(actual, original)
    np.testing.assert_array_equal(envelope, original_envelope)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2"])
def test_bad_span_bound_is_rejected(limit):
    with pytest.raises(ValueError, match="max_spans must be a positive integer"):
        _review(max_spans=limit)


def test_span_bound_raises_before_any_partial_review(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No curve evaluation is allowed before the inventory limit check")

    monkeypatch.setattr(
        "batterylog_research.precharge_capture_review.review_precharge_curve", forbidden
    )
    with pytest.raises(ValueError, match="2 active spans; max_spans is 1"):
        _review(max_spans=1)


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_examples_are_bounded_per_span_without_losing_deviation_counts(limit):
    source = list(_source())
    source[2][[1, 2, 3, 6, 7, 8]] = 3
    report = _review(source, max_examples=limit, max_spans=2)
    assert report["outside_envelope_samples"] == 6
    for span, expected_start in zip(report["active_spans"], [1, 6], strict=True):
        assert len(span["examples"]) == limit
        if limit:
            assert span["examples"][0]["sample_index"] == expected_start


@pytest.mark.parametrize(
    "kind",
    [
        "bad_reference",
        "bad_control",
        "boolean_measurement",
        "unaligned",
        "nonfinite_time",
        "descending_time",
        "empty",
    ],
)
def test_whole_capture_validation_is_not_skipped_when_no_phase_is_active(kind):
    source = [[0, 1, 2], [0, 0, 0], [1, 1, 1], [100] * 3, [90] * 3]
    envelope, gap = _envelope(), 1
    if kind == "bad_reference":
        envelope[0, 2] = np.nan
    elif kind == "bad_control":
        gap = True
    elif kind == "boolean_measurement":
        source[2][1] = True
    elif kind == "unaligned":
        source[2].pop()
    elif kind == "nonfinite_time":
        source[0][1] = np.inf
    elif kind == "descending_time":
        source[0][1] = -1
    else:
        source = [[] for _ in source]
    with pytest.raises(ValueError):
        review_precharge_capture(*source, envelope, max_gap_s=gap)


def test_elapsed_overflow_is_rejected_by_the_capture_adapter_too():
    source = (
        [-1.5e308, -1.4e308, -0.5e308, 0.5e308],
        [0, 1, 1, 1],
        [0, 1, 1, 1],
        [100] * 4,
        [90] * 4,
    )
    envelope = [[0, 0, 2, 0, 0.2], [1.6e308, 0, 2, 0, 0.2]]
    with pytest.raises(ValueError, match="Elapsed-time calculation overflowed"):
        review_precharge_capture(*source, envelope, max_gap_s=1.1e308)
