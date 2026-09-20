import argparse
import tempfile
import tracemalloc
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from batterylog import ValidationLimits, analyze_battery_log


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _write_synthetic_csv(path: Path, *, rows: int, cells: int) -> None:
    write_chunk_rows = 10_000
    first = True

    for start in range(0, rows, write_chunk_rows):
        count = min(write_chunk_rows, rows - start)
        data: dict[str, np.ndarray] = {
            "timestamp_s": np.arange(start, start + count, dtype=float),
            "temp_1_c": np.full(count, 25.0),
        }
        data.update(
            {
                f"cell_{index + 1}_v": np.full(count, 3.7 + (index % 5) * 0.001)
                for index in range(cells)
            }
        )
        pd.DataFrame(data).to_csv(
            path,
            mode="w" if first else "a",
            header=first,
            index=False,
            float_format="%.4f",
        )
        first = False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark end-to-end chunked CSV analysis and Python heap usage."
    )
    parser.add_argument("--rows", type=_positive_int, default=200_000)
    parser.add_argument("--cells", type=_positive_int, default=100)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="batterylog-benchmark-") as directory:
        path = Path(directory) / "synthetic.csv"
        _write_synthetic_csv(path, rows=args.rows, cells=args.cells)

        tracemalloc.start()
        started = perf_counter()
        result = analyze_battery_log(
            path,
            limits=ValidationLimits(
                cell_min_v=2.8,
                cell_max_v=4.2,
                imbalance_max_v=0.08,
                temperature_min_c=-20.0,
                temperature_max_c=55.0,
            ),
        )
        elapsed = perf_counter() - started
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        print(f"rows={result['rows_analyzed']}")
        print(f"cells={result['cells_detected']}")
        print(f"csv_mib={path.stat().st_size / 1024 / 1024:.1f}")
        print(f"elapsed_s={elapsed:.3f}")
        print(f"python_heap_peak_mib={peak_bytes / 1024 / 1024:.1f}")
        print(f"status={result['validation_status']}")


if __name__ == "__main__":
    main()
