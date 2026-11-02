# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Research-only streaming audit of peer-relative cell-voltage steps (not fault diagnosis)."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from statistics import median
from typing import TextIO

_CELL = re.compile(r"cell_(\d+)_v\Z")
_REL_TOL = 8 * math.ulp(1.0)


def _number(value: object, name: str, *, strictly_positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")  # noqa: TRY004 - public value contract
    try:
        number = float(value)  # accepts only finite real numeric CSV tokens
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    if strictly_positive and number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} arithmetic overflowed")
    return value


def audit_voltage_csv(
    source: TextIO,
    *,
    peer_step_threshold_v: float,
    max_gap_s: float,
    max_examples: int = 10,
) -> dict[str, object]:
    """Observe per-cell voltage changes relative to median peer changes.

    Requires canonical, synchronous series-cell samples. Each flagged step is an
    observation for review, never a statement about cell or sensor health.
    Input CSV is processed once; retained memory is O(cell_count + max_examples).
    """
    threshold = _number(peer_step_threshold_v, "peer_step_threshold_v", strictly_positive=True)
    gap = _number(max_gap_s, "max_gap_s", strictly_positive=True)
    if (
        isinstance(max_examples, bool)
        or not isinstance(max_examples, int)
        or not 0 <= max_examples <= 100
    ):
        raise ValueError("max_examples must be an integer from 0 to 100")
    rows = csv.reader(source, strict=True)
    header = next(rows, None)
    if not header:
        raise ValueError("Missing CSV header")
    if len(header) != len(set(header)):
        raise ValueError("Duplicate CSV column name")
    if "timestamp_s" not in header:
        raise ValueError("Missing canonical timestamp_s")
    positions = [
        (int(match[1]), name, i)
        for i, name in enumerate(header)
        if (match := _CELL.fullmatch(name)) is not None
    ]
    positions.sort()
    if len(positions) < 3:
        raise ValueError("At least three synchronous series-cell voltages are required")
    if len({index for index, _, _ in positions}) != len(positions):
        raise ValueError("Duplicate canonical cell index")
    names = [name for _, name, _ in positions]
    columns = [i for _, _, i in positions]
    time_column = header.index("timestamp_s")
    current_column = header.index("pack_current_a") if "pack_current_a" in header else None
    previous: tuple[float, list[float], float | None] | None = None
    counts: Counter[str] = Counter()
    sensors: Counter[str] = Counter()
    examples: list[dict[str, object]] = []
    row_count = compared_pairs = flagged = ambiguous_pairs = 0
    # csv.reader yields logical records; embedded quoted newlines mean that
    # enumerate(rows) is NOT a physical source-file line number. Preserve
    # the beginning of each record for evidence and actionable errors.
    previous_physical_line = rows.line_num
    for row in rows:
        line = previous_physical_line + 1
        previous_physical_line = rows.line_num
        if len(row) != len(header):
            raise ValueError(f"CSV row {line} has {len(row)} columns; expected {len(header)}")
        if not row or all(not value.strip() for value in row):
            raise ValueError(f"Empty CSV record at row {line}")
        t = _number(row[time_column], f"timestamp_s at CSV row {line}")
        cell = [_number(row[i], f"{names[n]} at CSV row {line}") for n, i in enumerate(columns)]
        current = (
            _number(row[current_column], f"pack_current_a at CSV row {line}")
            if current_column is not None
            else None
        )
        row_count += 1
        if previous is not None:
            old_t, old_cells, old_current = previous
            dt = _finite(t - old_t, "Timestamp difference")
            if dt < 0:
                raise ValueError(f"timestamp_s decreases at CSV row {line}")
            if dt == 0:
                counts["duplicate_timestamps"] += 1
            elif dt > gap and not math.isclose(dt, gap, rel_tol=_REL_TOL, abs_tol=0):
                counts["gaps_beyond_limit"] += 1
            else:
                compared_pairs += 1
                changes = [
                    _finite(now - old, "Cell voltage difference")
                    for now, old in zip(cell, old_cells, strict=True)
                ]
                common = _finite(float(median(changes)), "Median cell step")
                # A median alone is not a reliable reference for a split population.
                # Require a strict majority of cells to agree within the *same*
                # engineer-provided review threshold before attributing outliers.
                supporters = sum(
                    abs(_finite(change - common, "Peer consensus deviation")) < threshold
                    or math.isclose(abs(change - common), threshold, rel_tol=_REL_TOL, abs_tol=0)
                    for change in changes
                )
                if supporters <= len(changes) // 2:
                    ambiguous_pairs += 1
                    previous = (t, cell, current)
                    continue
                delta_current = (
                    _finite(current - old_current, "Current difference")
                    if current is not None and old_current is not None
                    else None
                )
                for name, change in zip(names, changes, strict=True):
                    residual = _finite(change - common, "Peer-relative voltage step")
                    magnitude = abs(residual)
                    if magnitude > threshold and not math.isclose(
                        magnitude, threshold, rel_tol=_REL_TOL, abs_tol=0
                    ):
                        flagged += 1
                        sensors[name] += 1
                        if len(examples) < max_examples:
                            examples.append(
                                {
                                    "csv_row": line,
                                    "signal": name,
                                    "previous_time_s": old_t,
                                    "time_s": t,
                                    "interval_s": dt,
                                    "cell_delta_v": change,
                                    "median_peer_delta_v": common,
                                    "peer_relative_step_v": residual,
                                    "delta_current_a": delta_current,
                                }
                            )
        previous = (t, cell, current)
    if not row_count:
        raise ValueError("No measurement rows")
    return {
        "scope": "research_observational_peer_relative_cell_step",
        "diagnostic_claim": False,
        "assumptions": "Synchronous, correctly mapped series-cell voltages in V; elapsed time in s",
        "threshold_v": threshold,
        "max_gap_s": gap,
        "source_has_current": current_column is not None,
        "rows_read": row_count,
        "eligible_sample_pairs": compared_pairs,
        "cell_step_observations_flagged": flagged,
        "ambiguous_peer_reference_pairs": ambiguous_pairs,
        "continuity": dict(sorted(counts.items())),
        "observations_by_cell": dict(sorted(sensors.items())),
        "examples": examples,
        "interpretation": (
            "Candidates for engineering review, not fault labels, health status "
            "or validated safety limits; ambiguous reference pairs are not classified"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--peer-step-threshold-v", type=float, required=True)
    parser.add_argument("--max-gap-s", type=float, required=True)
    parser.add_argument("--max-examples", type=int, default=10)
    options = parser.parse_args(argv)
    try:
        with options.csv_file.open(encoding="utf-8-sig", newline="") as source:
            report = audit_voltage_csv(
                source,
                peer_step_threshold_v=options.peer_step_threshold_v,
                max_gap_s=options.max_gap_s,
                max_examples=options.max_examples,
            )
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
