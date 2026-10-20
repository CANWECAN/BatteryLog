"""Regressions for scalar/vector edge parity and supported real gap controls."""

import hashlib
import json
import math
import subprocess
import sys
from fractions import Fraction

import numpy as np
import pytest

from batterylog_research.precharge_capture_review import review_precharge_capture
from batterylog_research.precharge_curve_review import REL, review_precharge_curve


def one_activation():
    return ([-0.25, 0, 0.25], [0, 1, 1], [0, 8, 7], [400] * 3, [0] * 3)


def reference(horizon=0.25):
    return [[0, 0, 10, -0.1, 1.1], [horizon, 0, 10, -0.1, 1.1]]


@pytest.mark.parametrize("exponent", [-800, -40, 0, 40, 800])
def test_multiple_activation_guard_uses_the_same_symmetric_tolerance(exponent):
    scale = math.ldexp(1.0, exponent)
    gap = 0.24999999999999956 * scale
    dt = 0.25 * scale
    assert math.isclose(dt, gap, rel_tol=REL, abs_tol=0)
    time = np.array([-0.25, 0, 0.25, 0.5, 0.75, 1, 1.25]) * scale
    with pytest.raises(ValueError, match="multiple observed activations"):
        review_precharge_curve(
            time,
            [0, 1, 1, 0, 0, 1, 1],
            [0, 8, 7, 0, 0, 8, 7],
            [400] * 7,
            [0] * 7,
            reference(dt),
            max_gap_s=gap,
        )


def test_same_boundary_still_qualifies_single_activation_and_capture_spans():
    gap = 0.24999999999999956
    single = review_precharge_curve(*one_activation(), reference(), max_gap_s=gap)
    assert single["declared_interval_covered"]
    capture = review_precharge_capture(
        [-0.25, 0, 0.25, 0.5, 0.75, 1, 1.25],
        [0, 1, 1, 0, 0, 1, 1],
        [0, 8, 7, 0, 0, 8, 7],
        [400] * 7,
        [0] * 7,
        reference(),
        max_gap_s=gap,
    )
    assert capture["observed_activations"] == 2
    assert capture["covered_reference_intervals"] == 2


@pytest.mark.parametrize("reviewer", [review_precharge_curve, review_precharge_capture])
@pytest.mark.parametrize("gap", [10**400, -(10**400), Fraction(10**400, 1), Fraction(1, 10**400)])
def test_unrepresentable_real_gap_has_a_controlled_error(reviewer, gap):
    with pytest.raises(ValueError, match="max_gap_s"):
        reviewer(*one_activation(), reference(), max_gap_s=gap)


@pytest.mark.parametrize("reviewer", [review_precharge_curve, review_precharge_capture])
@pytest.mark.parametrize(
    "gap", [Fraction(1, 4), np.float32(0.25), np.float64(0.25), np.longdouble(0.25)]
)
def test_representable_real_controls_match_binary64(reviewer, gap):
    expected = reviewer(*one_activation(), reference(), max_gap_s=0.25)
    actual = reviewer(*one_activation(), reference(), max_gap_s=gap)
    assert actual == expected


@pytest.mark.parametrize("gap", [10**400, -(10**400)])
def test_huge_json_gap_cli_rejects_without_traceback_or_output(tmp_path, gap):
    from batterylog_research import precharge_file_review as file_review

    capture = tmp_path / "aligned.csv"
    capture.write_bytes(
        (",".join(file_review.COLUMNS) + "\n-.25,0,0,400,0\n0,1,8,400,0\n.25,1,7,400,0\n").encode()
    )
    context = tmp_path / "context.json"
    declaration = {
        "format": "batterylog-precharge-aligned-v1",
        "capture_sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
        "input_kind": "authored_fixture",
        "measurement_context": dict.fromkeys(file_review.CONTEXT_FIELDS, "Authored fixture only"),
        "same_reference_for_all_spans": True,
        "max_gap_s": gap,
        "envelope": reference(),
    }
    context.write_text(json.dumps(declaration), encoding="utf-8")
    output = tmp_path / "report.json"
    before = [capture.read_bytes(), context.read_bytes()]
    command = [
        sys.executable,
        "-m",
        "batterylog_research.precharge_file_review",
        "--csv",
        str(capture),
        "--context",
        str(context),
        "--output",
        str(output),
    ]
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    assert done.returncode == 2
    assert "max_gap_s" in done.stderr and "error:" in done.stderr
    assert "Traceback" not in done.stderr
    assert not output.exists() and not list(tmp_path.glob(".batterylog-precharge-*"))
    assert before == [capture.read_bytes(), context.read_bytes()]
