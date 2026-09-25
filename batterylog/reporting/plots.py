from __future__ import annotations

from collections.abc import Callable, Iterable
from html import escape
from math import isclose, isfinite

from batterylog.analysis.report_series import ReportSeries, ReportSeriesPoint
from batterylog.models import AnalysisResult, ViolationEvent

_SVG_WIDTH = 1000.0
_SVG_HEIGHT = 320.0
_LEFT = 72.0
_RIGHT = 24.0
_TOP = 28.0
_BOTTOM = 48.0
_PLOT_WIDTH = _SVG_WIDTH - _LEFT - _RIGHT
_PLOT_HEIGHT = _SVG_HEIGHT - _TOP - _BOTTOM
_TICK_COUNT = 5

_VOLTAGE_CODES = frozenset({"CELL_UNDERVOLTAGE", "CELL_OVERVOLTAGE"})
_DELTA_CODES = frozenset({"CELL_IMBALANCE_HIGH"})
_TEMPERATURE_CODES = frozenset({"TEMPERATURE_LOW", "TEMPERATURE_HIGH"})
_TEMPERATURE_SPREAD_CODES = frozenset({"TEMPERATURE_SPREAD_HIGH"})
_CURRENT_CODES = frozenset({"PACK_CHARGE_OVERCURRENT", "PACK_DISCHARGE_OVERCURRENT"})
_PACK_CELL_CODES = frozenset({"PACK_VOLTAGE_CELL_SUM_MISMATCH"})
_ALL_PLOT_CODES = (
    _VOLTAGE_CODES
    | _DELTA_CODES
    | _TEMPERATURE_CODES
    | _TEMPERATURE_SPREAD_CODES
    | _CURRENT_CODES
    | _PACK_CELL_CODES
)

GeometryBuilder = Callable[[tuple[ReportSeriesPoint, ...], float, float, float, float], str]


def _fmt(value: float) -> str:
    return f"{value:.8g}"


def _attr_number(value: float) -> str:
    rendered = f"{value:.6f}".rstrip("0").rstrip(".")
    return rendered if rendered not in {"", "-0"} else "0"


def _time_domain(points: tuple[ReportSeriesPoint, ...]) -> tuple[float, float]:
    start = points[0].timestamp_s
    end = points[-1].timestamp_s
    if start == end:
        return start - 0.5, end + 0.5
    return start, end


def _value_domain(
    values: Iterable[float],
    *,
    minimum_padding: float,
) -> tuple[float, float]:
    collected = tuple(values)
    if not collected:
        raise ValueError("Plot value domain requires at least one value")

    minimum = min(collected)
    maximum = max(collected)
    if minimum == maximum:
        padding = max(abs(minimum) * 0.05, minimum_padding)
    else:
        padding = max((maximum - minimum) * 0.08, minimum_padding)
    return minimum - padding, maximum + padding


def _scale(
    value: float, source_min: float, source_max: float, target_min: float, target_max: float
) -> float:
    if source_min == source_max:  # pragma: no cover - domains expand equal ranges
        return (target_min + target_max) / 2.0
    ratio = (value - source_min) / (source_max - source_min)
    return target_min + ratio * (target_max - target_min)


def _x(value: float, start: float, end: float) -> float:
    return _scale(value, start, end, _LEFT, _LEFT + _PLOT_WIDTH)


def _y(value: float, minimum: float, maximum: float) -> float:
    return _scale(value, minimum, maximum, _TOP + _PLOT_HEIGHT, _TOP)


def _polyline(
    points: tuple[ReportSeriesPoint, ...],
    accessor: Callable[[ReportSeriesPoint], float],
    *,
    x_start: float,
    x_end: float,
    y_min: float,
    y_max: float,
    css_class: str,
) -> str:
    coordinates = " ".join(
        f"{_attr_number(_x(point.timestamp_s, x_start, x_end))},"
        f"{_attr_number(_y(accessor(point), y_min, y_max))}"
        for point in points
    )
    polyline = f'<polyline class="{css_class}" points="{coordinates}" />'
    if len(points) != 1:
        return polyline

    point = points[0]
    sample_x = _x(point.timestamp_s, x_start, x_end)
    sample_y = _y(accessor(point), y_min, y_max)
    return (
        polyline + f'<circle class="series-sample {css_class}-sample" '
        f'cx="{_attr_number(sample_x)}" cy="{_attr_number(sample_y)}" r="3" />'
    )


def _envelope_polygon(
    points: tuple[ReportSeriesPoint, ...],
    lower: Callable[[ReportSeriesPoint], float],
    upper: Callable[[ReportSeriesPoint], float],
    *,
    x_start: float,
    x_end: float,
    y_min: float,
    y_max: float,
) -> str:
    upper_points = [
        f"{_attr_number(_x(point.timestamp_s, x_start, x_end))},"
        f"{_attr_number(_y(upper(point), y_min, y_max))}"
        for point in points
    ]
    lower_points = [
        f"{_attr_number(_x(point.timestamp_s, x_start, x_end))},"
        f"{_attr_number(_y(lower(point), y_min, y_max))}"
        for point in reversed(points)
    ]
    return f'<polygon class="chart-envelope" points="{" ".join([*upper_points, *lower_points])}" />'


def _events_for(result: AnalysisResult, codes: frozenset[str]) -> tuple[ViolationEvent, ...]:
    return tuple(event for event in result["violations"] if event["code"] in codes)


def _event_windows(
    events: tuple[ViolationEvent, ...],
    *,
    x_start: float,
    x_end: float,
) -> str:
    parts: list[str] = []
    plot_right = _LEFT + _PLOT_WIDTH

    for event in events:
        start_x = min(max(_x(event["start_time_s"], x_start, x_end), _LEFT), plot_right)
        end_x = min(max(_x(event["end_time_s"], x_start, x_end), _LEFT), plot_right)
        left = min(start_x, end_x)
        width = abs(end_x - start_x)
        code = escape(event["code"])
        if width == 0.0:
            parts.append(
                f'<line class="violation-instant" x1="{_attr_number(left)}" '
                f'x2="{_attr_number(left)}" y1="{_attr_number(_TOP)}" '
                f'y2="{_attr_number(_TOP + _PLOT_HEIGHT)}" data-code="{code}" '
                f'data-start-time-s="{_fmt(event["start_time_s"])}" '
                f'data-end-time-s="{_fmt(event["end_time_s"])}" />'
            )
        else:
            parts.append(
                f'<rect class="violation-window" x="{_attr_number(left)}" '
                f'y="{_attr_number(_TOP)}" width="{_attr_number(width)}" '
                f'height="{_attr_number(_PLOT_HEIGHT)}" data-code="{code}" '
                f'data-start-time-s="{_fmt(event["start_time_s"])}" '
                f'data-end-time-s="{_fmt(event["end_time_s"])}" />'
            )

    return "".join(parts)


def _event_peaks(
    events: tuple[ViolationEvent, ...],
    *,
    x_start: float,
    x_end: float,
    y_min: float,
    y_max: float,
) -> str:
    parts: list[str] = []
    plot_right = _LEFT + _PLOT_WIDTH

    for event in events:
        peak_x = min(max(_x(event["peak_time_s"], x_start, x_end), _LEFT), plot_right)
        peak_y = min(
            max(_y(event["measured_value"], y_min, y_max), _TOP),
            _TOP + _PLOT_HEIGHT,
        )
        code = escape(event["code"])
        parts.append(
            f'<circle class="violation-peak" cx="{_attr_number(peak_x)}" '
            f'cy="{_attr_number(peak_y)}" r="4" data-code="{code}" '
            f'data-peak-time-s="{_fmt(event["peak_time_s"])}" '
            f'data-measured-value="{_fmt(event["measured_value"])}">'
            f"<title>{code}: {_fmt(event['measured_value'])} {escape(event['unit'])} "
            f"at {_fmt(event['peak_time_s'])} s</title></circle>"
        )

    return "".join(parts)


def _limit_lines(
    limits: tuple[tuple[str, float | None], ...],
    *,
    y_min: float,
    y_max: float,
) -> str:
    parts: list[str] = []
    right = _LEFT + _PLOT_WIDTH

    for label, value in limits:
        if value is None:
            continue
        y_position = _y(value, y_min, y_max)
        parts.append(
            f'<line class="limit-line" x1="{_attr_number(_LEFT)}" '
            f'x2="{_attr_number(right)}" y1="{_attr_number(y_position)}" '
            f'y2="{_attr_number(y_position)}" data-limit="{escape(label)}" '
            f'data-value="{_fmt(value)}" />'
        )
        parts.append(
            f'<text class="limit-label" x="{_attr_number(right - 4)}" '
            f'y="{_attr_number(y_position - 5)}" text-anchor="end">'
            f"{escape(label)} {_fmt(value)}</text>"
        )

    return "".join(parts)


def _axes(*, x_start: float, x_end: float, y_min: float, y_max: float, y_unit: str) -> str:
    parts = [
        (
            f'<line class="chart-axis" x1="{_attr_number(_LEFT)}" x2="{_attr_number(_LEFT)}" '
            f'y1="{_attr_number(_TOP)}" y2="{_attr_number(_TOP + _PLOT_HEIGHT)}" />'
        ),
        (
            f'<line class="chart-axis" x1="{_attr_number(_LEFT)}" '
            f'x2="{_attr_number(_LEFT + _PLOT_WIDTH)}" '
            f'y1="{_attr_number(_TOP + _PLOT_HEIGHT)}" '
            f'y2="{_attr_number(_TOP + _PLOT_HEIGHT)}" />'
        ),
    ]

    for index in range(_TICK_COUNT):
        ratio = index / (_TICK_COUNT - 1)
        y_value = y_max - ratio * (y_max - y_min)
        y_position = _TOP + ratio * _PLOT_HEIGHT
        parts.append(
            f'<line class="chart-grid" x1="{_attr_number(_LEFT)}" '
            f'x2="{_attr_number(_LEFT + _PLOT_WIDTH)}" y1="{_attr_number(y_position)}" '
            f'y2="{_attr_number(y_position)}" />'
        )
        parts.append(
            f'<text class="chart-tick" x="{_attr_number(_LEFT - 8)}" '
            f'y="{_attr_number(y_position + 4)}" text-anchor="end">'
            f"{_fmt(y_value)} {escape(y_unit)}</text>"
        )

        x_value = x_start + ratio * (x_end - x_start)
        x_position = _LEFT + ratio * _PLOT_WIDTH
        parts.append(
            f'<text class="chart-tick" x="{_attr_number(x_position)}" '
            f'y="{_attr_number(_TOP + _PLOT_HEIGHT + 24)}" text-anchor="middle">'
            f"{_fmt(x_value)} s</text>"
        )

    return "".join(parts)


def _voltage_geometry(
    points: tuple[ReportSeriesPoint, ...],
    x_start: float,
    x_end: float,
    y_min: float,
    y_max: float,
) -> str:
    return (
        _envelope_polygon(
            points,
            lambda point: point.cell_min_v,
            lambda point: point.cell_max_v,
            x_start=x_start,
            x_end=x_end,
            y_min=y_min,
            y_max=y_max,
        )
        + _polyline(
            points,
            lambda point: point.cell_min_v,
            x_start=x_start,
            x_end=x_end,
            y_min=y_min,
            y_max=y_max,
            css_class="series-secondary",
        )
        + _polyline(
            points,
            lambda point: point.cell_max_v,
            x_start=x_start,
            x_end=x_end,
            y_min=y_min,
            y_max=y_max,
            css_class="series-primary",
        )
    )


def _delta_geometry(
    points: tuple[ReportSeriesPoint, ...],
    x_start: float,
    x_end: float,
    y_min: float,
    y_max: float,
) -> str:
    return _polyline(
        points,
        lambda point: point.cell_delta_v,
        x_start=x_start,
        x_end=x_end,
        y_min=y_min,
        y_max=y_max,
        css_class="series-primary",
    )


def _temperature_geometry(
    points: tuple[ReportSeriesPoint, ...],
    x_start: float,
    x_end: float,
    y_min: float,
    y_max: float,
) -> str:
    return (
        _envelope_polygon(
            points,
            lambda point: point.temperature_min_c,
            lambda point: point.temperature_max_c,
            x_start=x_start,
            x_end=x_end,
            y_min=y_min,
            y_max=y_max,
        )
        + _polyline(
            points,
            lambda point: point.temperature_min_c,
            x_start=x_start,
            x_end=x_end,
            y_min=y_min,
            y_max=y_max,
            css_class="series-secondary",
        )
        + _polyline(
            points,
            lambda point: point.temperature_max_c,
            x_start=x_start,
            x_end=x_end,
            y_min=y_min,
            y_max=y_max,
            css_class="series-primary",
        )
    )


def _temperature_spread_geometry(
    points: tuple[ReportSeriesPoint, ...],
    x_start: float,
    x_end: float,
    y_min: float,
    y_max: float,
) -> str:
    return _polyline(
        points,
        lambda point: point.temperature_spread_c,
        x_start=x_start,
        x_end=x_end,
        y_min=y_min,
        y_max=y_max,
        css_class="series-primary",
    )


def _current_geometry(
    points: tuple[ReportSeriesPoint, ...],
    x_start: float,
    x_end: float,
    y_min: float,
    y_max: float,
) -> str:
    def current(point: ReportSeriesPoint) -> float:
        assert point.pack_current_a is not None
        return point.pack_current_a

    return _polyline(
        points,
        current,
        x_start=x_start,
        x_end=x_end,
        y_min=y_min,
        y_max=y_max,
        css_class="series-primary",
    )


def _pack_cell_geometry(
    points: tuple[ReportSeriesPoint, ...],
    x_start: float,
    x_end: float,
    y_min: float,
    y_max: float,
) -> str:
    def pack(point: ReportSeriesPoint) -> float:
        assert point.pack_voltage_v is not None
        return point.pack_voltage_v

    def summed(point: ReportSeriesPoint) -> float:
        assert point.cell_voltage_sum_v is not None
        return point.cell_voltage_sum_v

    return _polyline(
        points,
        pack,
        x_start=x_start,
        x_end=x_end,
        y_min=y_min,
        y_max=y_max,
        css_class="series-primary",
    ) + _polyline(
        points,
        summed,
        x_start=x_start,
        x_end=x_end,
        y_min=y_min,
        y_max=y_max,
        css_class="series-secondary",
    )


def _pack_cell_delta_geometry(
    points: tuple[ReportSeriesPoint, ...],
    x_start: float,
    x_end: float,
    y_min: float,
    y_max: float,
) -> str:
    def delta(point: ReportSeriesPoint) -> float:
        value = point.pack_cell_delta_v
        assert value is not None
        return value

    return _polyline(
        points,
        delta,
        x_start=x_start,
        x_end=x_end,
        y_min=y_min,
        y_max=y_max,
        css_class="series-primary",
    )


def _render_chart(
    *,
    title: str,
    points: tuple[ReportSeriesPoint, ...],
    result: AnalysisResult,
    codes: frozenset[str],
    y_values: Iterable[float],
    limits: tuple[tuple[str, float | None], ...],
    y_unit: str,
    y_padding_floor: float,
    geometry_builder: GeometryBuilder,
    legend: str,
) -> str:
    x_start, x_end = _time_domain(points)
    events = _events_for(result, codes)
    configured_limits = tuple(value for _, value in limits if value is not None)
    event_values = tuple(event["measured_value"] for event in events)
    y_min, y_max = _value_domain(
        (*tuple(y_values), *configured_limits, *event_values),
        minimum_padding=y_padding_floor,
    )

    return (
        '<figure class="plot-card">'
        f'<figcaption><strong>{escape(title)}</strong><span class="plot-legend">{legend}</span></figcaption>'
        f'<svg class="timeseries-chart" viewBox="0 0 {_attr_number(_SVG_WIDTH)} '
        f'{_attr_number(_SVG_HEIGHT)}" role="img" aria-label="{escape(title)}">'
        f"{_axes(x_start=x_start, x_end=x_end, y_min=y_min, y_max=y_max, y_unit=y_unit)}"
        f"{_event_windows(events, x_start=x_start, x_end=x_end)}"
        f"{geometry_builder(points, x_start, x_end, y_min, y_max)}"
        f"{_limit_lines(limits, y_min=y_min, y_max=y_max)}"
        f"{_event_peaks(events, x_start=x_start, x_end=x_end, y_min=y_min, y_max=y_max)}"
        "</svg></figure>"
    )


def _validate_report_series(result: AnalysisResult, series: ReportSeries) -> None:
    if series.source_rows != result["rows_analyzed"]:
        raise ValueError(
            "Report series/result row mismatch: "
            f"series has {series.source_rows}, result has {result['rows_analyzed']}"
        )
    if series.source_rows < 0:
        raise ValueError("Report series source_rows must be non-negative")
    if len(series.points) > series.max_points:
        raise ValueError("Report series exceeds its declared max_points budget")
    if series.source_rows == 0:
        if series.points:
            raise ValueError("Empty report series cannot contain retained points")
        return
    if not series.points:
        raise ValueError("Non-empty analysis requires retained report-series points")
    if series.points[0].row_index != 0 or series.points[-1].row_index != series.source_rows - 1:
        raise ValueError("Report series must retain the first and last source rows")

    previous_row = -1
    previous_timestamp: float | None = None
    for point in series.points:
        if point.row_index <= previous_row or point.row_index >= series.source_rows:
            raise ValueError("Report-series row indexes must be strictly increasing and in range")
        values = (
            point.timestamp_s,
            point.cell_min_v,
            point.cell_max_v,
            point.cell_delta_v,
            point.temperature_min_c,
            point.temperature_max_c,
        )
        if (
            not all(isfinite(value) for value in values)
            or (point.pack_current_a is not None and not isfinite(point.pack_current_a))
            or (point.pack_voltage_v is not None and not isfinite(point.pack_voltage_v))
            or (point.cell_voltage_sum_v is not None and not isfinite(point.cell_voltage_sum_v))
        ):
            raise ValueError("Report-series plot values must be finite")
        if previous_timestamp is not None and point.timestamp_s < previous_timestamp:
            raise ValueError("Report-series timestamps must be non-decreasing")
        if point.cell_min_v > point.cell_max_v:
            raise ValueError("Report-series cell-voltage envelope is inverted")
        if point.temperature_min_c > point.temperature_max_c:
            raise ValueError("Report-series temperature envelope is inverted")
        expected_delta = point.cell_max_v - point.cell_min_v
        if not isclose(
            point.cell_delta_v,
            expected_delta,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("Report-series cell delta is inconsistent with its voltage envelope")
        previous_row = point.row_index
        previous_timestamp = point.timestamp_s

    domain_start = series.points[0].timestamp_s
    domain_end = series.points[-1].timestamp_s
    for event in result["violations"]:
        if event["code"] not in _ALL_PLOT_CODES:
            raise ValueError(f"Violation code {event['code']!r} has no report-plot mapping")
        event_values = (
            event["start_time_s"],
            event["end_time_s"],
            event["peak_time_s"],
            event["measured_value"],
            event["limit_value"],
        )
        if not all(isfinite(value) for value in event_values):
            raise ValueError("Violation event contains non-finite plot evidence")
        if event["start_time_s"] > event["end_time_s"]:
            raise ValueError("Violation event start time must not exceed its end time")
        if not event["start_time_s"] <= event["peak_time_s"] <= event["end_time_s"]:
            raise ValueError("Violation event peak time must lie inside its event interval")
        if event["start_time_s"] < domain_start or event["end_time_s"] > domain_end:
            raise ValueError("Violation event lies outside the report-series time domain")

    # AnalysisResult.max_delta_v is rounded to 12 decimal places upstream. The
    # 1e-12 absolute guard tolerance below intentionally exceeds the maximum
    # ±0.5e-12 rounding error while still catching materially mismatched series.
    current_present = result["signal_mapping"]["pack_current_source"] is not None
    retained_currents = tuple(
        point.pack_current_a for point in series.points if point.pack_current_a is not None
    )
    if current_present != (len(retained_currents) == len(series.points)):
        raise ValueError("Report-series pack-current presence does not match AnalysisResult")
    voltage_present = result["signal_mapping"]["pack_voltage_source"] is not None
    retained_voltage = tuple(p for p in series.points if p.pack_voltage_v is not None)
    retained_sums = tuple(p for p in series.points if p.cell_voltage_sum_v is not None)
    if voltage_present != (len(retained_voltage) == len(series.points)) or (
        voltage_present != (len(retained_sums) == len(series.points))
    ):
        raise ValueError(
            "Report-series pack-voltage/cell-sum presence does not match AnalysisResult"
        )

    extrema: tuple[tuple[str, float], ...] = (
        ("max_cell_voltage_v", max(point.cell_max_v for point in series.points)),
        ("min_cell_voltage_v", min(point.cell_min_v for point in series.points)),
        ("max_delta_v", max(point.cell_delta_v for point in series.points)),
        ("max_temperature_c", max(point.temperature_max_c for point in series.points)),
        ("min_temperature_c", min(point.temperature_min_c for point in series.points)),
    )
    if retained_currents:
        extrema += (
            ("max_pack_current_a", max(retained_currents)),
            ("min_pack_current_a", min(retained_currents)),
        )
    if retained_voltage:
        extrema += (
            (
                "pack_voltage_cell_sum_peak",
                max(
                    p.pack_cell_delta_v for p in retained_voltage if p.pack_cell_delta_v is not None
                ),
            ),
        )
    for result_key, retained_value in extrema:
        if result_key == "pack_voltage_cell_sum_peak":
            peak = result[result_key]
            if peak is None or not isclose(
                retained_value, peak["absolute_delta_v"], rel_tol=1e-12, abs_tol=1e-12
            ):
                raise ValueError("Report series does not preserve pack/cell-sum mismatch peak")
            continue
        if not isclose(
            retained_value,
            result[result_key],
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "Report series does not preserve AnalysisResult extrema: "
                f"{result_key}={retained_value!r}, result={result[result_key]!r}"
            )


def render_report_plots(result: AnalysisResult, series: ReportSeries) -> str:
    _validate_report_series(result, series)
    if not series.points:
        return '<section class="timeseries"><h2>Time-series plots</h2><p>No plot data available.</p></section>'

    points = series.points
    limits = result["limits_applied"]
    voltage_limits = (("Cell min", limits["cell_min_v"]), ("Cell max", limits["cell_max_v"]))
    delta_limits = (("Delta max", limits["imbalance_max_v"]),)
    temperature_limits = (
        ("Temp min", limits["temperature_min_c"]),
        ("Temp max", limits["temperature_max_c"]),
    )
    temperature_spread_limit = limits["temperature_spread_max_c"]
    positive_direction = limits["pack_current_positive_direction"]
    charge_limit = limits["pack_charge_max_a"]
    discharge_limit = limits["pack_discharge_max_a"]
    current_limits = (
        (
            "Charge max",
            (
                charge_limit
                if positive_direction == "charge" or charge_limit is None
                else -charge_limit
            ),
        ),
        (
            "Discharge max",
            (
                discharge_limit
                if positive_direction == "discharge" or discharge_limit is None
                else -discharge_limit
            ),
        ),
    )

    voltage = _render_chart(
        title="Cell-voltage envelope",
        points=points,
        result=result,
        codes=_VOLTAGE_CODES,
        y_values=(value for point in points for value in (point.cell_min_v, point.cell_max_v)),
        limits=voltage_limits,
        y_unit="V",
        y_padding_floor=0.01,
        geometry_builder=_voltage_geometry,
        legend=(
            '<span class="legend-primary">maximum</span> '
            '<span class="legend-secondary">minimum</span>'
        ),
    )
    delta = _render_chart(
        title="Cell-voltage delta",
        points=points,
        result=result,
        codes=_DELTA_CODES,
        y_values=(point.cell_delta_v for point in points),
        limits=delta_limits,
        y_unit="V",
        y_padding_floor=0.005,
        geometry_builder=_delta_geometry,
        legend='<span class="legend-primary">delta</span>',
    )
    temperature = _render_chart(
        title="Temperature envelope",
        points=points,
        result=result,
        codes=_TEMPERATURE_CODES,
        y_values=(
            value
            for point in points
            for value in (point.temperature_min_c, point.temperature_max_c)
        ),
        limits=temperature_limits,
        y_unit="degC",
        y_padding_floor=1.0,
        geometry_builder=_temperature_geometry,
        legend=(
            '<span class="legend-primary">maximum</span> '
            '<span class="legend-secondary">minimum</span>'
        ),
    )

    temperature_spread = ""
    if temperature_spread_limit is not None:
        temperature_spread = _render_chart(
            title="Temperature spread",
            points=points,
            result=result,
            codes=_TEMPERATURE_SPREAD_CODES,
            y_values=(point.temperature_spread_c for point in points),
            limits=(("Spread max", temperature_spread_limit),),
            y_unit="degC",
            y_padding_floor=1.0,
            geometry_builder=_temperature_spread_geometry,
            legend='<span class="legend-primary">spread</span>',
        )

    current = ""
    if points[0].pack_current_a is not None:
        current = _render_chart(
            title="Pack current",
            points=points,
            result=result,
            codes=_CURRENT_CODES,
            y_values=(point.pack_current_a for point in points if point.pack_current_a is not None),
            limits=current_limits,
            y_unit="A",
            y_padding_floor=1.0,
            geometry_builder=_current_geometry,
            legend='<span class="legend-primary">pack current</span>',
        )

    pack_cell = ""
    if points[0].pack_voltage_v is not None:
        pack_cell = _render_chart(
            title="Pack voltage and cell sum",
            points=points,
            result=result,
            codes=frozenset(),
            y_values=(
                v for p in points for v in (p.pack_voltage_v, p.cell_voltage_sum_v) if v is not None
            ),
            limits=(),
            y_unit="V",
            y_padding_floor=0.01,
            geometry_builder=_pack_cell_geometry,
            legend='<span class="legend-primary">pack</span> <span class="legend-secondary">cell sum</span>',
        ) + _render_chart(
            title="Absolute pack/cell-sum mismatch",
            points=points,
            result=result,
            codes=_PACK_CELL_CODES,
            y_values=(p.pack_cell_delta_v for p in points if p.pack_cell_delta_v is not None),
            limits=(("Mismatch max", limits["pack_voltage_cell_sum_max_delta_v"]),),
            y_unit="V",
            y_padding_floor=0.01,
            geometry_builder=_pack_cell_delta_geometry,
            legend='<span class="legend-primary">absolute mismatch</span>',
        )

    if series.is_downsampled:
        sampling = (
            f"Rendered {len(points)} retained points from {series.source_rows} source rows using "
            f"{escape(series.strategy)}. Validation events remain sourced from AnalysisResult."
        )
    else:
        sampling = (
            f"Rendered all {series.source_rows} source rows. Validation events remain sourced "
            "from AnalysisResult."
        )

    return (
        '<section class="timeseries"><h2>Time-series plots</h2>'
        f'<p class="small plot-note">{sampling}</p>'
        f"{voltage}{delta}{temperature}{temperature_spread}{current}{pack_cell}</section>"
    )
