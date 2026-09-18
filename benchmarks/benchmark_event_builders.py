import argparse
from time import perf_counter

import numpy as np
import pandas as pd

from batterylog.analysis.rules import build_high_events


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthetic worst-case benchmark for BatteryLog event construction."
    )
    parser.add_argument("--rows", type=_positive_int, default=300_000)
    parser.add_argument("--signals", type=_positive_int, default=20)
    args = parser.parse_args()

    timestamps = pd.Series(np.arange(args.rows, dtype=float))
    values = np.zeros((args.rows, args.signals), dtype=float)
    values[:, 0] = np.where(
        np.arange(args.rows) % 2 == 0,
        5.0,
        0.0,
    )
    columns = [f"cell_{index + 1}_v" for index in range(args.signals)]
    numeric = pd.DataFrame(values, columns=columns)
    row_max = numeric.max(axis=1)

    started = perf_counter()
    events = build_high_events(
        numeric=numeric,
        timestamps=timestamps,
        signal_cols=columns,
        row_max=row_max,
        limit=4.2,
        code="CELL_OVERVOLTAGE",
        unit="V",
    )
    elapsed = perf_counter() - started

    print(f"rows={args.rows}")
    print(f"signals={args.signals}")
    print(f"events={len(events)}")
    print(f"elapsed_s={elapsed:.3f}")
    print(f"events_per_s={len(events) / elapsed:.0f}")


if __name__ == "__main__":
    main()
