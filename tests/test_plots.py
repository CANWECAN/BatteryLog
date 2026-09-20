from dataclasses import replace
from io import BytesIO

import pytest

from batterylog import ValidationLimits
from batterylog.analysis.streaming import analyze_battery_file_with_report_series
from batterylog.reporting.plots import render_report_plots


def _result_and_series():
    source = BytesIO(
        b"timestamp_s,cell_1_v,cell_2_v,temp_c\n"
        b"0,3.80,3.79,25\n"
        b"1,4.30,3.90,56\n"
        b"2,2.70,3.00,-25\n"
        b"3,3.80,3.79,25\n"
    )
    return analyze_battery_file_with_report_series(
        source,
        source_name="capture.csv",
        limits=ValidationLimits(
            cell_min_v=2.8,
            cell_max_v=4.2,
            imbalance_max_v=0.08,
            temperature_min_c=-20.0,
            temperature_max_c=55.0,
        ),
        max_points=12,
    )


def _downsampled_result_and_series():
    rows = ["timestamp_s,cell_1_v,cell_2_v,temp_c"]
    for index in range(40):
        cell_1_v = 4.25 if index == 1 else (4.50 if index == 20 else 3.80)
        rows.append(f"{index},{cell_1_v},3.80,25")
    source = BytesIO(("\n".join(rows) + "\n").encode())
    return analyze_battery_file_with_report_series(
        source,
        source_name="downsampled.csv",
        limits=ValidationLimits(cell_max_v=4.2),
        max_points=12,
    )


def test_render_report_plots_contains_three_self_contained_svgs() -> None:
    result, series = _result_and_series()

    html = render_report_plots(result, series)

    assert html.count('class="timeseries-chart"') == 3
    assert "Cell-voltage envelope" in html
    assert "Cell-voltage delta" in html
    assert "Temperature envelope" in html
    assert "<script" not in html.lower()
    assert "http://" not in html
    assert "https://" not in html


def test_plot_limits_are_sourced_from_analysis_result() -> None:
    result, series = _result_and_series()

    html = render_report_plots(result, series)

    assert 'data-limit="Cell min" data-value="2.8"' in html
    assert 'data-limit="Cell max" data-value="4.2"' in html
    assert 'data-limit="Delta max" data-value="0.08"' in html
    assert 'data-limit="Temp min" data-value="-20"' in html
    assert 'data-limit="Temp max" data-value="55"' in html


def test_plot_violation_markers_come_from_result_even_when_peak_row_is_not_retained() -> None:
    result, series = _downsampled_result_and_series()
    retained_rows = {point.row_index for point in series.points}

    assert 1 not in retained_rows
    assert 20 in retained_rows

    html = render_report_plots(result, series)

    for event in result["violations"]:
        assert f'data-code="{event["code"]}"' in html
        assert f'data-peak-time-s="{event["peak_time_s"]:.8g}"' in html
        assert f'data-measured-value="{event["measured_value"]:.8g}"' in html


def test_plot_rendering_is_deterministic() -> None:
    result, series = _result_and_series()

    first = render_report_plots(result, series)
    second = render_report_plots(result, series)

    assert second == first


def test_plot_renderer_rejects_series_from_different_result() -> None:
    result, series = _result_and_series()
    mismatched = replace(series, source_rows=series.source_rows + 1)

    with pytest.raises(ValueError, match="Report series/result row mismatch"):
        render_report_plots(result, mismatched)


def test_plot_renderer_rejects_same_length_series_with_mismatched_extrema() -> None:
    result, series = _result_and_series()
    bad_point = replace(series.points[1], cell_max_v=4.29)
    mismatched = replace(series, points=(series.points[0], bad_point, *series.points[2:]))

    with pytest.raises(ValueError, match="does not preserve AnalysisResult extrema"):
        render_report_plots(result, mismatched)


def test_plot_renderer_rejects_missing_points_for_non_empty_result() -> None:
    result, series = _result_and_series()
    malformed = replace(series, points=())

    with pytest.raises(ValueError, match="requires retained report-series points"):
        render_report_plots(result, malformed)


def test_plot_renderer_rejects_budget_overflow() -> None:
    result, series = _result_and_series()
    malformed = replace(series, max_points=len(series.points) - 1)

    with pytest.raises(ValueError, match="exceeds its declared max_points budget"):
        render_report_plots(result, malformed)


def test_plot_renderer_rejects_missing_boundary_rows() -> None:
    result, series = _result_and_series()
    malformed = replace(series, points=series.points[1:])

    with pytest.raises(ValueError, match="must retain the first and last source rows"):
        render_report_plots(result, malformed)


def test_plot_renderer_rejects_non_increasing_row_indexes() -> None:
    result, series = _result_and_series()
    malformed = replace(
        series,
        points=(series.points[0], series.points[2], series.points[1], series.points[-1]),
    )

    with pytest.raises(ValueError, match="row indexes must be strictly increasing"):
        render_report_plots(result, malformed)


def test_plot_renderer_rejects_non_finite_values() -> None:
    result, series = _result_and_series()
    bad_point = replace(series.points[1], cell_max_v=float("nan"))
    malformed = replace(series, points=(series.points[0], bad_point, *series.points[2:]))

    with pytest.raises(ValueError, match="plot values must be finite"):
        render_report_plots(result, malformed)


def test_plot_renderer_rejects_timestamp_regression() -> None:
    result, series = _result_and_series()
    bad_point = replace(series.points[2], timestamp_s=-1.0)
    malformed = replace(
        series, points=(series.points[0], series.points[1], bad_point, series.points[3])
    )

    with pytest.raises(ValueError, match="timestamps must be non-decreasing"):
        render_report_plots(result, malformed)


def test_plot_renderer_handles_empty_result_geometry_contract() -> None:
    result, series = _result_and_series()
    empty_result = result.copy()
    empty_result["rows_analyzed"] = 0
    empty_series = replace(series, points=(), source_rows=0)

    html = render_report_plots(empty_result, empty_series)

    assert "No plot data available" in html


def test_single_timestamp_and_constant_values_render_without_non_finite_geometry() -> None:
    source = BytesIO(b"timestamp_s,cell_1_v,cell_2_v,temp_c\n5,3.8,3.8,25\n")
    result, series = analyze_battery_file_with_report_series(
        source,
        source_name="single.csv",
        limits=ValidationLimits(cell_max_v=4.2),
        max_points=12,
    )

    html = render_report_plots(result, series)
    lowered = html.lower()

    assert "nan" not in lowered
    assert "infinity" not in lowered
    assert "Cell-voltage envelope" in html
    assert ">0.005 V</text>" in html
    assert ">-0.005 V</text>" in html


def test_plot_note_discloses_downsampling_strategy() -> None:
    result, series = _downsampled_result_and_series()

    html = render_report_plots(result, series)

    assert (
        f"Rendered {len(series.points)} retained points from {series.source_rows} source rows"
        in html
    )
    assert "extrema-preserving-v1" in html
    assert "Validation events remain sourced from AnalysisResult" in html
