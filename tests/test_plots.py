from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from typing import get_args

import pytest

from batterylog import ValidationLimits
from batterylog.analysis.streaming import analyze_battery_file_with_report_series
from batterylog.models import RuleCode
from batterylog.reporting import plots as plots_module
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
        max_points=14,
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
        max_points=14,
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


def test_delta_rounding_residue_does_not_trip_extrema_guard() -> None:
    source = BytesIO(
        b"timestamp_s,cell_1_v,cell_2_v,temp_c\n"
        b"0,3.7,3.6,25\n"
        b"1,3.8000000000005,3.7,25\n"
        b"2,3.7,3.6,25\n"
    )
    result, series = analyze_battery_file_with_report_series(
        source,
        source_name="rounding.csv",
        limits=ValidationLimits(imbalance_max_v=0.05),
        max_points=14,
    )

    retained_max = max(point.cell_delta_v for point in series.points)
    assert retained_max != result["max_delta_v"]
    assert abs(retained_max - result["max_delta_v"]) < 1e-12
    assert "Cell-voltage delta" in render_report_plots(result, series)


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
    bad_point = replace(series.points[1], cell_max_v=4.29, cell_delta_v=0.39)
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


def test_plot_renderer_rejects_inverted_cell_voltage_envelope() -> None:
    result, series = _result_and_series()
    bad_point = replace(series.points[0], cell_min_v=3.95, cell_max_v=3.80)
    malformed = replace(series, points=(bad_point, *series.points[1:]))

    with pytest.raises(ValueError, match="cell-voltage envelope is inverted"):
        render_report_plots(result, malformed)


def test_plot_renderer_rejects_inverted_temperature_envelope() -> None:
    result, series = _result_and_series()
    bad_point = replace(series.points[0], temperature_min_c=30.0, temperature_max_c=20.0)
    malformed = replace(series, points=(bad_point, *series.points[1:]))

    with pytest.raises(ValueError, match="temperature envelope is inverted"):
        render_report_plots(result, malformed)


def test_plot_renderer_rejects_delta_inconsistent_with_voltage_envelope() -> None:
    result, series = _result_and_series()
    bad_point = replace(series.points[0], cell_delta_v=0.02)
    malformed = replace(series, points=(bad_point, *series.points[1:]))

    with pytest.raises(ValueError, match="cell delta is inconsistent"):
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


def test_plot_renderer_rejects_non_finite_violation_evidence() -> None:
    result, series = _result_and_series()
    malformed = deepcopy(result)
    malformed["violations"][0]["peak_time_s"] = float("nan")

    with pytest.raises(ValueError, match="non-finite plot evidence"):
        render_report_plots(malformed, series)


def test_plot_renderer_rejects_violation_outside_series_time_domain() -> None:
    result, series = _result_and_series()
    malformed = deepcopy(result)
    malformed["violations"][0]["start_time_s"] = 999.0
    malformed["violations"][0]["end_time_s"] = 999.0
    malformed["violations"][0]["peak_time_s"] = 999.0

    with pytest.raises(ValueError, match="outside the report-series time domain"):
        render_report_plots(malformed, series)


def test_plot_renderer_rejects_peak_outside_event_interval() -> None:
    result, series = _result_and_series()
    malformed = deepcopy(result)
    event = malformed["violations"][0]
    event["peak_time_s"] = event["end_time_s"] + 0.5

    with pytest.raises(ValueError, match="peak time must lie inside"):
        render_report_plots(malformed, series)


def test_plot_renderer_rejects_event_with_reversed_time_interval() -> None:
    result, series = _result_and_series()
    malformed = deepcopy(result)
    event = malformed["violations"][0]
    event["start_time_s"], event["end_time_s"] = event["end_time_s"], event["start_time_s"]

    with pytest.raises(ValueError, match="start time must not exceed"):
        render_report_plots(malformed, series)


def test_plot_renderer_rejects_unmapped_violation_code() -> None:
    result, series = _result_and_series()
    malformed = deepcopy(result)
    malformed["violations"][0]["code"] = "FUTURE_RULE"  # type: ignore[typeddict-item]

    with pytest.raises(ValueError, match="has no report-plot mapping"):
        render_report_plots(malformed, series)


def test_all_current_rule_codes_have_plot_mapping() -> None:
    assert set(get_args(RuleCode)) == plots_module._ALL_PLOT_CODES


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
        max_points=14,
    )

    html = render_report_plots(result, series)
    lowered = html.lower()

    assert "nan" not in lowered
    assert "infinity" not in lowered
    assert "Cell-voltage envelope" in html
    assert ">0.005 V</text>" in html
    assert ">-0.005 V</text>" in html
    assert html.count('class="series-sample ') == 5


def test_instantaneous_violation_uses_vertical_marker_without_fake_duration() -> None:
    result, series = _result_and_series()
    html = render_report_plots(result, series)

    assert 'class="violation-instant"' in html
    assert 'data-start-time-s="1" data-end-time-s="1"' in html


def test_plot_note_discloses_downsampling_strategy() -> None:
    result, series = _downsampled_result_and_series()

    html = render_report_plots(result, series)

    assert (
        f"Rendered {len(series.points)} retained points from {series.source_rows} source rows"
        in html
    )
    assert "extrema-preserving-v1" in html
    assert "Validation events remain sourced from AnalysisResult" in html


def test_pack_current_rules_render_signed_limits_and_event_markers() -> None:
    source = BytesIO(
        b"timestamp_s,pack_current_a,cell_1_v,temp_c\n0,-60,3.8,25\n1,0,3.8,25\n2,130,3.8,25\n"
    )
    result, series = analyze_battery_file_with_report_series(
        source,
        source_name="pack-current.csv",
        limits=ValidationLimits(
            pack_charge_max_a=50.0,
            pack_discharge_max_a=100.0,
            pack_current_positive_direction="discharge",
        ),
        max_points=14,
    )

    html = render_report_plots(result, series)

    assert html.count('class="timeseries-chart"') == 4
    assert "Pack current" in html
    assert 'data-limit="Charge max" data-value="-50"' in html
    assert 'data-limit="Discharge max" data-value="100"' in html
    assert 'data-code="PACK_CHARGE_OVERCURRENT"' in html
    assert 'data-code="PACK_DISCHARGE_OVERCURRENT"' in html
    assert all(point.pack_current_a is not None for point in series.points)


def test_temperature_spread_rule_renders_dedicated_chart_and_exact_event_marker() -> None:
    source = BytesIO(
        b"timestamp_s,temp_1_c,temp_2_c,cell_1_v\n0,20,30,3.8\n1,22,34,3.8\n2,24,40,3.8\n"
    )
    result, series = analyze_battery_file_with_report_series(
        source,
        source_name="temperature-spread.csv",
        limits=ValidationLimits(temperature_spread_max_c=10.0),
        max_points=14,
    )
    html = render_report_plots(result, series)
    assert html.count('class="timeseries-chart"') == 4
    assert "Temperature spread" in html
    assert 'data-limit="Spread max" data-value="10"' in html
    assert 'data-code="TEMPERATURE_SPREAD_HIGH"' in html
