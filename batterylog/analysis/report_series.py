from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

DEFAULT_REPORT_SERIES_MAX_POINTS = 2400
_MAX_BUCKET_CANDIDATES = 14
_MIN_REPORT_SERIES_MAX_POINTS = _MAX_BUCKET_CANDIDATES
_MIN_BASE_BLOCK_ROWS = 16
_METRICS = (
    "cell_min_v",
    "cell_max_v",
    "cell_delta_v",
    "temperature_min_c",
    "temperature_max_c",
    "pack_current_a",
    "pack_cell_delta_v",
)


@dataclass(frozen=True, slots=True)
class ReportSeriesPoint:
    row_index: int
    timestamp_s: float
    cell_min_v: float
    cell_max_v: float
    cell_delta_v: float
    temperature_min_c: float
    temperature_max_c: float
    pack_current_a: float | None = None
    pack_voltage_v: float | None = None
    cell_voltage_sum_v: float | None = None

    @property
    def pack_cell_delta_v(self) -> float | None:
        if self.pack_voltage_v is None or self.cell_voltage_sum_v is None:
            return None
        return abs(self.pack_voltage_v - self.cell_voltage_sum_v)

    @property
    def temperature_spread_c(self) -> float:
        return self.temperature_max_c - self.temperature_min_c


@dataclass(frozen=True, slots=True)
class ReportSeries:
    points: tuple[ReportSeriesPoint, ...]
    source_rows: int
    max_points: int
    strategy: str = "extrema-preserving-v1"

    @property
    def is_downsampled(self) -> bool:
        return len(self.points) < self.source_rows


@dataclass(frozen=True, slots=True)
class _SeriesBucket:
    candidates: tuple[ReportSeriesPoint, ...]


def _select_bucket_candidates(
    points: tuple[ReportSeriesPoint, ...],
) -> tuple[ReportSeriesPoint, ...]:
    if not points:  # pragma: no cover - internal invariant guard
        raise ValueError("Report-series bucket cannot be empty")

    selected: dict[int, ReportSeriesPoint] = {
        points[0].row_index: points[0],
        points[-1].row_index: points[-1],
    }
    for metric in _METRICS:
        metric_points = tuple(point for point in points if getattr(point, metric) is not None)
        if not metric_points:
            continue
        minimum = min(
            metric_points,
            key=lambda point: (getattr(point, metric), point.row_index),
        )
        maximum = max(
            metric_points,
            key=lambda point: (getattr(point, metric), -point.row_index),
        )
        selected[minimum.row_index] = minimum
        selected[maximum.row_index] = maximum

    return tuple(selected[index] for index in sorted(selected))


def _merge_buckets(buckets: list[_SeriesBucket]) -> _SeriesBucket:
    candidates = tuple(point for bucket in buckets for point in bucket.candidates)
    return _SeriesBucket(candidates=_select_bucket_candidates(candidates))


def _point_from_arrays(
    local_index: int,
    *,
    row_offset: int,
    timestamps: NDArray[np.float64],
    cell_min: NDArray[np.float64],
    cell_max: NDArray[np.float64],
    cell_delta: NDArray[np.float64],
    temperature_min: NDArray[np.float64],
    temperature_max: NDArray[np.float64],
    pack_current: NDArray[np.float64] | None,
    pack_voltage: NDArray[np.float64] | None,
    cell_sum: NDArray[np.float64] | None,
) -> ReportSeriesPoint:
    return ReportSeriesPoint(
        row_index=row_offset + local_index,
        timestamp_s=float(timestamps[local_index]),
        cell_min_v=float(cell_min[local_index]),
        cell_max_v=float(cell_max[local_index]),
        cell_delta_v=float(cell_delta[local_index]),
        temperature_min_c=float(temperature_min[local_index]),
        temperature_max_c=float(temperature_max[local_index]),
        pack_current_a=(float(pack_current[local_index]) if pack_current is not None else None),
        pack_voltage_v=(float(pack_voltage[local_index]) if pack_voltage is not None else None),
        cell_voltage_sum_v=(float(cell_sum[local_index]) if cell_sum is not None else None),
    )


def _summarize_array_block(
    *,
    row_offset: int,
    timestamps: NDArray[np.float64],
    cell_min: NDArray[np.float64],
    cell_max: NDArray[np.float64],
    cell_delta: NDArray[np.float64],
    temperature_min: NDArray[np.float64],
    temperature_max: NDArray[np.float64],
    pack_current: NDArray[np.float64] | None,
    pack_voltage: NDArray[np.float64] | None,
    cell_sum: NDArray[np.float64] | None,
) -> _SeriesBucket:
    length = len(timestamps)
    if length == 0:  # pragma: no cover - internal invariant guard
        raise ValueError("Report-series array block cannot be empty")

    selected_indexes = {0, length - 1}
    arrays = [cell_min, cell_max, cell_delta, temperature_min, temperature_max]
    if pack_current is not None:
        arrays.append(pack_current)
    if pack_voltage is not None and cell_sum is not None:
        arrays.append(np.abs(pack_voltage - cell_sum))
    for values in arrays:
        selected_indexes.add(int(np.argmin(values)))
        selected_indexes.add(int(np.argmax(values)))

    candidates = tuple(
        _point_from_arrays(
            local_index,
            row_offset=row_offset,
            timestamps=timestamps,
            cell_min=cell_min,
            cell_max=cell_max,
            cell_delta=cell_delta,
            temperature_min=temperature_min,
            temperature_max=temperature_max,
            pack_current=pack_current,
            pack_voltage=pack_voltage,
            cell_sum=cell_sum,
        )
        for local_index in sorted(selected_indexes)
    )
    return _SeriesBucket(candidates=candidates)


class ReportSeriesCollector:
    def __init__(self, *, max_points: int = DEFAULT_REPORT_SERIES_MAX_POINTS) -> None:
        if isinstance(max_points, bool) or not isinstance(max_points, int):
            raise TypeError("max_points must be an integer")
        if max_points < _MIN_REPORT_SERIES_MAX_POINTS:
            raise ValueError(f"max_points must be at least {_MIN_REPORT_SERIES_MAX_POINTS}")

        self._max_points = max_points
        self._target_buckets = max(1, max_points // _MAX_BUCKET_CANDIDATES)
        self._base_block_rows = max(
            _MIN_BASE_BLOCK_ROWS,
            (max_points + self._target_buckets - 1) // self._target_buckets,
        )
        self._raw_points: list[ReportSeriesPoint] = []
        self._buckets: list[_SeriesBucket] = []
        self._pending_points: list[ReportSeriesPoint] = []
        self._source_rows = 0
        self._downsampled = False
        self._finished: ReportSeries | None = None

    @property
    def source_rows(self) -> int:
        return self._source_rows

    def consume(self, point: ReportSeriesPoint) -> None:
        if self._finished is not None:
            raise RuntimeError("Cannot consume report-series data after finish()")
        if point.row_index != self._source_rows:
            raise ValueError(
                "Report-series points must arrive in contiguous row order: "
                f"expected {self._source_rows}, got {point.row_index}"
            )

        if not self._downsampled:
            self._raw_points.append(point)
            self._source_rows += 1
            if len(self._raw_points) > self._max_points:
                self._downsampled = True
                self._initialize_downsampled_buckets()
            return

        self._pending_points.append(point)
        self._source_rows += 1
        if len(self._pending_points) == self._base_block_rows:
            self._append_bucket(
                _SeriesBucket(candidates=_select_bucket_candidates(tuple(self._pending_points)))
            )
            self._pending_points.clear()

    def consume_chunk(
        self,
        *,
        row_offset: int,
        timestamps: NDArray[np.float64],
        cell_min: NDArray[np.float64],
        cell_max: NDArray[np.float64],
        cell_delta: NDArray[np.float64],
        temperature_min: NDArray[np.float64],
        temperature_max: NDArray[np.float64],
        pack_current: NDArray[np.float64] | None = None,
        pack_voltage: NDArray[np.float64] | None = None,
        cell_sum: NDArray[np.float64] | None = None,
    ) -> None:
        if self._finished is not None:
            raise RuntimeError("Cannot consume report-series data after finish()")

        arrays = (timestamps, cell_min, cell_max, cell_delta, temperature_min, temperature_max)
        length = len(timestamps)
        if (
            any(len(values) != length for values in arrays[1:])
            or (pack_current is not None and len(pack_current) != length)
            or (pack_voltage is not None and len(pack_voltage) != length)
            or (cell_sum is not None and len(cell_sum) != length)
        ):
            raise ValueError("Report-series chunk arrays must have equal lengths")
        if row_offset != self._source_rows:
            raise ValueError(
                "Report-series chunks must arrive in contiguous row order: "
                f"expected {self._source_rows}, got {row_offset}"
            )
        if length == 0:
            return

        position = 0
        if not self._downsampled:
            keep = min(length, self._max_points + 1 - len(self._raw_points))
            for local_index in range(keep):
                self._raw_points.append(
                    _point_from_arrays(
                        local_index,
                        row_offset=row_offset,
                        timestamps=timestamps,
                        cell_min=cell_min,
                        cell_max=cell_max,
                        cell_delta=cell_delta,
                        temperature_min=temperature_min,
                        temperature_max=temperature_max,
                        pack_current=pack_current,
                        pack_voltage=pack_voltage,
                        cell_sum=cell_sum,
                    )
                )
            position = keep
            self._source_rows += keep

            if len(self._raw_points) > self._max_points:
                self._downsampled = True
                self._initialize_downsampled_buckets()

        if position < length:
            self._consume_downsampled_arrays(
                row_offset=row_offset + position,
                timestamps=timestamps[position:],
                cell_min=cell_min[position:],
                cell_max=cell_max[position:],
                cell_delta=cell_delta[position:],
                temperature_min=temperature_min[position:],
                temperature_max=temperature_max[position:],
                pack_current=(pack_current[position:] if pack_current is not None else None),
                pack_voltage=(pack_voltage[position:] if pack_voltage is not None else None),
                cell_sum=(cell_sum[position:] if cell_sum is not None else None),
            )
            self._source_rows += length - position

    def _initialize_downsampled_buckets(self) -> None:
        points = self._raw_points
        self._raw_points = []
        start = 0
        while start + self._base_block_rows <= len(points):
            block = tuple(points[start : start + self._base_block_rows])
            self._append_bucket(_SeriesBucket(candidates=_select_bucket_candidates(block)))
            start += self._base_block_rows
        self._pending_points.extend(points[start:])

    def _consume_downsampled_arrays(
        self,
        *,
        row_offset: int,
        timestamps: NDArray[np.float64],
        cell_min: NDArray[np.float64],
        cell_max: NDArray[np.float64],
        cell_delta: NDArray[np.float64],
        temperature_min: NDArray[np.float64],
        temperature_max: NDArray[np.float64],
        pack_current: NDArray[np.float64] | None,
        pack_voltage: NDArray[np.float64] | None,
        cell_sum: NDArray[np.float64] | None,
    ) -> None:
        position = 0
        length = len(timestamps)

        if self._pending_points:
            needed = self._base_block_rows - len(self._pending_points)
            take = min(needed, length)
            for local_index in range(take):
                self._pending_points.append(
                    _point_from_arrays(
                        local_index,
                        row_offset=row_offset,
                        timestamps=timestamps,
                        cell_min=cell_min,
                        cell_max=cell_max,
                        cell_delta=cell_delta,
                        temperature_min=temperature_min,
                        temperature_max=temperature_max,
                        pack_current=pack_current,
                        pack_voltage=pack_voltage,
                        cell_sum=cell_sum,
                    )
                )
            position = take
            if len(self._pending_points) == self._base_block_rows:
                self._append_bucket(
                    _SeriesBucket(candidates=_select_bucket_candidates(tuple(self._pending_points)))
                )
                self._pending_points.clear()

        while position + self._base_block_rows <= length:
            end = position + self._base_block_rows
            self._append_bucket(
                _summarize_array_block(
                    row_offset=row_offset + position,
                    timestamps=timestamps[position:end],
                    cell_min=cell_min[position:end],
                    cell_max=cell_max[position:end],
                    cell_delta=cell_delta[position:end],
                    temperature_min=temperature_min[position:end],
                    temperature_max=temperature_max[position:end],
                    pack_current=(pack_current[position:end] if pack_current is not None else None),
                    pack_voltage=(pack_voltage[position:end] if pack_voltage is not None else None),
                    cell_sum=(cell_sum[position:end] if cell_sum is not None else None),
                )
            )
            position = end

        for local_index in range(position, length):
            self._pending_points.append(
                _point_from_arrays(
                    local_index,
                    row_offset=row_offset,
                    timestamps=timestamps,
                    cell_min=cell_min,
                    cell_max=cell_max,
                    cell_delta=cell_delta,
                    temperature_min=temperature_min,
                    temperature_max=temperature_max,
                    pack_current=pack_current,
                    pack_voltage=pack_voltage,
                    cell_sum=cell_sum,
                )
            )

    def _append_bucket(self, bucket: _SeriesBucket) -> None:
        self._buckets.append(bucket)
        if len(self._buckets) >= 2 * self._target_buckets:
            self._compact_to_target()

    def _compact_to_target(self) -> None:
        count = len(self._buckets)
        if count <= self._target_buckets:
            return

        compacted: list[_SeriesBucket] = []
        for bucket_index in range(self._target_buckets):
            start = bucket_index * count // self._target_buckets
            end = (bucket_index + 1) * count // self._target_buckets
            compacted.append(_merge_buckets(self._buckets[start:end]))
        self._buckets = compacted

    def finish(self) -> ReportSeries:
        if self._finished is not None:
            return self._finished

        if not self._downsampled:
            points = tuple(self._raw_points)
        else:
            if self._pending_points:
                self._append_bucket(
                    _SeriesBucket(candidates=_select_bucket_candidates(tuple(self._pending_points)))
                )
                self._pending_points.clear()
            self._compact_to_target()

            unique: dict[int, ReportSeriesPoint] = {}
            for bucket in self._buckets:
                for point in bucket.candidates:
                    unique[point.row_index] = point
            points = tuple(unique[index] for index in sorted(unique))

        if len(points) > self._max_points:  # pragma: no cover - invariant guard
            raise RuntimeError("Report-series reducer exceeded its max_points contract")

        self._finished = ReportSeries(
            points=points,
            source_rows=self._source_rows,
            max_points=self._max_points,
        )
        return self._finished
