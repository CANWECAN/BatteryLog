import numpy as np
import pandas as pd
import pytest

from batterylog.analysis.comparison import (
    BINARY64_ABS_TOL,
    BINARY64_REL_TOL,
    below_limit,
    exceeds_limit,
    exceeds_limit_scalar,
)


def test_binary64_guard_is_machine_scale() -> None:
    epsilon = float(np.finfo(np.float64).eps)

    assert BINARY64_REL_TOL == pytest.approx(8.0 * epsilon)
    assert BINARY64_ABS_TOL == 0.0
    assert BINARY64_REL_TOL < 1e-12


def test_high_comparison_ignores_only_representation_scale_boundary_noise() -> None:
    limit = 4.2
    boundary_noise = np.nextafter(limit, np.inf)
    meaningful_excess = limit + 1e-9
    values = pd.Series([limit, boundary_noise, meaningful_excess])

    mask = exceeds_limit(values, limit)

    assert mask.tolist() == [False, False, True]


def test_low_comparison_ignores_only_representation_scale_boundary_noise() -> None:
    limit = 2.8
    boundary_noise = np.nextafter(limit, -np.inf)
    meaningful_deficit = limit - 1e-9
    values = pd.Series([limit, boundary_noise, meaningful_deficit])

    mask = below_limit(values, limit)

    assert mask.tolist() == [False, False, True]


def test_scalar_gap_comparison_uses_same_boundary_policy() -> None:
    limit = 0.3

    assert not exceeds_limit_scalar(np.nextafter(limit, np.inf), limit)
    assert exceeds_limit_scalar(limit + 1e-9, limit)


def test_zero_boundary_has_no_unit_dependent_absolute_tolerance() -> None:
    near_zero = np.nextafter(0.0, np.inf)

    assert not exceeds_limit_scalar(0.0, 0.0)
    assert exceeds_limit_scalar(near_zero, 0.0)
