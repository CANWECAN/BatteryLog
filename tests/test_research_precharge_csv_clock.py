"""CSV timing decisions must use encoded durations, independent of clock origin."""

import hashlib
import json
from decimal import Decimal, localcontext

import pytest

from batterylog_research import precharge_file_review as review


def capture_files(tmp_path, offset, point, gap, *, old_prefix=False):
    with localcontext() as context:
        context.prec = 250
        base = Decimal(offset)
        stamps = [str(base + Decimal(t)) for t in ("-0.1", "0", point, "1.1")]
        phases = [0, 1, 1, 0]
        if old_prefix:
            stamps.insert(0, str(base - Decimal("1e12")))
            phases.insert(0, 0)
    text = ",".join(review.COLUMNS) + "\n"
    text += "".join(
        f"{stamp},{phase},2,400,200\n" for stamp, phase in zip(stamps, phases, strict=True)
    )
    capture = tmp_path / "capture.csv"
    context_path = tmp_path / "context.json"
    capture.write_bytes(text.encode())
    declaration = {
        "format": "batterylog-precharge-aligned-v1",
        "capture_sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
        "input_kind": "authored_fixture",
        "measurement_context": dict.fromkeys(
            review.CONTEXT_FIELDS, "Authored CSV clock regression; no physical claim"
        ),
        "same_reference_for_all_spans": True,
        "max_gap_s": gap,
        "envelope": [[0, 0, 10, -1, 1], [1, 0, 10, -1, 1]],
    }
    context_path.write_text(json.dumps(declaration), encoding="utf-8")
    return capture, context_path, tmp_path / "report.json", stamps


@pytest.mark.parametrize("offset", ["0", "1800000000", "1000000000000", "1e100", "-1e100"])
@pytest.mark.parametrize("old_prefix", [False, True])
@pytest.mark.parametrize(
    ("point", "gap", "covered", "reason"),
    [
        ("1.0000001", 1, 0, "source_interval_interrupted"),
        ("0.99999999", 2, 0, "phase_ended_before_coverage_completed"),
        ("1", 2, 1, None),
    ],
)
def test_csv_clock_origin_does_not_hide_gaps_or_finish_early(
    tmp_path, offset, old_prefix, point, gap, covered, reason
):
    capture, context, output, stamps = capture_files(
        tmp_path, offset, point, gap, old_prefix=old_prefix
    )
    before = capture.read_bytes(), context.read_bytes()
    report = review.review_paths(capture, context, output)
    result = report["review"]
    span = result["active_spans"][0]
    assert result["covered_reference_intervals"] == covered
    assert result["observed_activations"] == 1
    assert result["reviewed_samples"] == (1 if reason == "source_interval_interrupted" else 2)
    if reason is None:
        assert span["incomplete_reasons"] == []
    else:
        assert reason in span["incomplete_reasons"]
    start = 2 if old_prefix else 1
    assert span["active_start_time_s_decimal"] == stamps[start]
    assert span["active_end_time_s_decimal"] == stamps[start + 1]
    assert span["observed_start_bracket_s_decimal"] == stamps[start - 1 : start + 1]
    assert span["active_start_time_s"] == float(stamps[start])
    assert report["capture"]["sha256"] == hashlib.sha256(before[0]).hexdigest()
    assert (capture.read_bytes(), context.read_bytes()) == before
    assert json.loads(output.read_text()) == report


def test_csv_duration_subtraction_ignores_ambient_decimal_context(tmp_path):
    capture, context, output, _ = capture_files(tmp_path, "1e100", "1.0000001", 1)
    with localcontext() as decimal_context:
        decimal_context.prec = 6
        decimal_context.Emax, decimal_context.Emin = 3, -3
        result = review.review_paths(capture, context, output)["review"]
    assert result["covered_reference_intervals"] == 0
    assert "source_interval_interrupted" in result["active_spans"][0]["incomplete_reasons"]


@pytest.mark.parametrize("offset", ["1800000000", "1e100", "-1e100"])
@pytest.mark.parametrize("old_prefix", [False, True])
def test_exact_elapsed_time_retains_declared_envelope_departure(tmp_path, offset, old_prefix):
    capture, context, output, stamps = capture_files(
        tmp_path, offset, "0.50000001", 0.6, old_prefix=old_prefix
    )
    with localcontext() as decimal_context:
        decimal_context.prec = 250
        stamps.insert(-1, str(Decimal(offset) + 1))
    phases = [0] * old_prefix + [0, 1, 1, 1, 0]
    currents = [0] * old_prefix + [0, 0.5, 0.5, 0, 0]
    text = ",".join(review.COLUMNS) + "\n"
    text += "".join(
        f"{stamp},{phase},{current},400,200\n"
        for stamp, phase, current in zip(stamps, phases, currents, strict=True)
    )
    capture.write_bytes(text.encode())
    declaration = json.loads(context.read_text())
    declaration["capture_sha256"] = hashlib.sha256(capture.read_bytes()).hexdigest()
    declaration["envelope"] = [[0, 0, 1, -1, 1], [1, 0, 0, -1, 1]]
    context.write_text(json.dumps(declaration))
    result = review.review_paths(capture, context, output)["review"]
    assert result["covered_reference_intervals"] == 1
    assert result["reviewed_samples"] == 3
    assert result["outside_envelope_samples"] == 1
    assert result["active_spans"][0]["examples"][0]["elapsed_s"] == 0.50000001


@pytest.mark.parametrize(
    "times",
    [
        [],
        [[Decimal(0)]],
        [Decimal("NaN"), Decimal(1)],
        [Decimal("-Infinity"), Decimal(0)],
    ],
)
@pytest.mark.parametrize("capture", [False, True])
def test_decimal_clock_api_rejects_unusable_time_before_review(times, capture):
    import numpy as np

    from batterylog_research.precharge_capture_review import review_precharge_capture
    from batterylog_research.precharge_curve_review import review_precharge_curve

    observer = review_precharge_capture if capture else review_precharge_curve
    clock = np.asarray(times, dtype=object)
    size = len(clock)
    with pytest.raises(ValueError, match="finite one-dimensional decimal source time"):
        observer(
            clock,
            [0] * size,
            [1] * size,
            [400] * size,
            [200] * size,
            [[0, 0, 10, -1, 1], [1, 0, 10, -1, 1]],
            max_gap_s=1,
        )
