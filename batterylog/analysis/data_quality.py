from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from batterylog.models import DataQualityCode, DataQualityEvent

_EventKey = tuple[DataQualityCode, tuple[str, ...]]


@dataclass
class DataQualityCollector:
    completed: list[DataQualityEvent] = field(default_factory=list)
    active: dict[_EventKey, DataQualityEvent] = field(default_factory=dict)

    def consume_chunk(
        self,
        frame: pd.DataFrame,
        numeric: pd.DataFrame,
        *,
        row_offset: int,
    ) -> NDArray[np.bool_]:
        columns = list(numeric.columns)
        numeric_missing = numeric.isna().to_numpy(dtype=bool)
        raw_missing = frame.loc[:, columns].isna().to_numpy(dtype=bool)
        missing = numeric_missing & raw_missing
        non_numeric = numeric_missing & ~raw_missing

        values = numeric.to_numpy(dtype=float)
        non_finite = ~np.isfinite(values) & ~numeric_missing

        invalid_rows = (missing | non_numeric | non_finite).any(axis=1)

        defect_masks: tuple[tuple[DataQualityCode, NDArray[np.bool_]], ...] = (
            ("MISSING_REQUIRED_VALUE", missing),
            ("NON_NUMERIC_REQUIRED_VALUE", non_numeric),
            ("NON_FINITE_REQUIRED_VALUE", non_finite),
        )
        for row_pos in range(len(numeric)):
            row_number = row_offset + row_pos + 1
            defects: dict[_EventKey, int] = {}
            for code, mask in defect_masks:
                positions = np.flatnonzero(mask[row_pos])
                if len(positions):
                    signals = tuple(columns[int(position)] for position in positions)
                    defects[(code, signals)] = len(positions)
            self._consume_row(row_number, defects)

        return invalid_rows

    def _consume_row(self, row_number: int, defects: dict[_EventKey, int]) -> None:
        current_keys = set(defects)
        for key in tuple(self.active):
            if key not in current_keys:
                self.completed.append(self.active.pop(key))

        for (code, signals), affected_values in defects.items():
            key = (code, signals)
            current = self.active.get(key)
            if current is not None and current["end_row"] == row_number - 1:
                current["end_row"] = row_number
                current["affected_values"] += affected_values
                continue

            if current is not None:
                self.completed.append(current)

            self.active[key] = {
                "code": code,
                "start_row": row_number,
                "end_row": row_number,
                "signals": list(signals),
                "affected_values": affected_values,
            }

    def break_contiguity(self) -> None:
        for event in self.active.values():
            self.completed.append(event)
        self.active.clear()

    def finish(self) -> list[DataQualityEvent]:
        self.break_contiguity()
        self.completed.sort(
            key=lambda event: (
                event["start_row"],
                event["code"],
                tuple(event["signals"]),
            )
        )
        return self.completed
