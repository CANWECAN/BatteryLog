import numpy as np
import pandas as pd

BINARY64_GUARD_MULTIPLIER = 8.0
BINARY64_REL_TOL = BINARY64_GUARD_MULTIPLIER * float(np.finfo(np.float64).eps)
BINARY64_ABS_TOL = 0.0


def _boundary_equivalent(values: np.ndarray, limit: float) -> np.ndarray:
    return np.isclose(
        values,
        limit,
        rtol=BINARY64_REL_TOL,
        atol=BINARY64_ABS_TOL,
        equal_nan=False,
    )


def exceeds_limit(values: pd.Series, limit: float) -> pd.Series:
    array = values.to_numpy(dtype=float, copy=False)
    mask = (array > limit) & ~_boundary_equivalent(array, limit)
    return pd.Series(mask, index=values.index, dtype=bool)


def below_limit(values: pd.Series, limit: float) -> pd.Series:
    array = values.to_numpy(dtype=float, copy=False)
    mask = (array < limit) & ~_boundary_equivalent(array, limit)
    return pd.Series(mask, index=values.index, dtype=bool)


def exceeds_limit_scalar(value: float, limit: float) -> bool:
    values = np.asarray([value], dtype=float)
    return bool((values[0] > limit) and not _boundary_equivalent(values, limit)[0])
