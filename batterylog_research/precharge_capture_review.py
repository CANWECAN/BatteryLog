# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Review known active row spans with original capture indices; no diagnosis."""

import numpy as np

from batterylog_research.precharge_curve_review import (
    _validate_controls,
    _validated_envelope,
    _validated_source,
    review_precharge_curve,
)


def review_precharge_capture(
    times,
    active,
    current_a,
    pack_voltage_v,
    dc_link_voltage_v,
    envelope,
    *,
    max_gap_s,
    max_examples=5,
    max_spans=1000,
):
    """Apply one justified reference to comparable active spans in an aligned capture.

    A span is adjacent rows with phase exactly one, not a physical episode.
    Unknown phase separates spans; gaps/duplicate times do not heal qualification.
    The same envelope must be appropriate for each observed activation. All arrays
    remain in memory. Excess spans raise before evaluation rather than truncate.
    """
    max_gap_s = _validate_controls(max_gap_s, max_examples)
    if isinstance(max_spans, bool) or not isinstance(max_spans, int) or max_spans < 1:
        raise ValueError("max_spans must be a positive integer")
    time, phase, current, pack, bus, _ = _validated_source(
        times, active, current_a, pack_voltage_v, dc_link_voltage_v
    )
    bounds = _validated_envelope(envelope)
    arrays = np.asarray(times), phase, current, pack, bus
    active_rows = phase == 1
    starts_mask = active_rows & np.r_[True, ~active_rows[:-1]]
    span_count = int(np.count_nonzero(starts_mask))
    if span_count > max_spans:
        raise ValueError(f"Capture has {span_count} active spans; max_spans is {max_spans}")
    starts = np.flatnonzero(starts_mask)
    stops = np.flatnonzero(active_rows & np.r_[~active_rows[1:], True]) + 1
    reviews = []
    for ordinal, (start, stop) in enumerate(zip(starts, stops, strict=True)):
        start, stop = int(start), int(stop)
        review_start, review_stop = max(start - 1, 0), min(stop + 1, len(time))
        result = review_precharge_curve(
            *(a[review_start:review_stop] for a in arrays),
            bounds,
            max_gap_s=max_gap_s,
            max_examples=max_examples,
        )
        for example in result["examples"]:
            example["sample_index"] += review_start
        reviews.append(
            {
                "span_index": ordinal,
                "source_active_start_index": start,
                "source_active_stop_index_exclusive": stop,
                "source_review_start_index": review_start,
                "source_review_stop_index_exclusive": review_stop,
                "active_start_time_s": float(time[start]),
                "active_end_time_s": float(time[stop - 1]),
                "activation_observed": result["observed_start_bracket_s"] is not None,
                **result,
            }
        )
    return {
        "scope": "recorded_active_spans_only",
        "production_decisions_changed": False,
        "source_samples": len(time),
        "known_active_samples": int(np.count_nonzero(active_rows)),
        "unknown_phase_samples": int(np.count_nonzero((phase != 0) & (phase != 1))),
        "observed_activations": sum(r["activation_observed"] for r in reviews),
        "covered_reference_intervals": sum(r["declared_interval_covered"] for r in reviews),
        "unobserved_active_spans": sum(not r["activation_observed"] for r in reviews),
        "reviewed_samples": sum(r["reviewed_samples"] for r in reviews),
        "outside_envelope_samples": sum(r["outside_envelope_samples"] for r in reviews),
        "max_spans": max_spans,
        "max_examples_per_span": max_examples,
        "active_spans": reviews,
    }
