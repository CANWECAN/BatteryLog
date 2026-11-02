# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Self-contained display of existing aligned precharge observations."""

from __future__ import annotations

import hashlib
import json
import math
from html import escape

from batterylog_research.precharge_curve_review import _above, _decimal_delta
from batterylog_research.precharge_file_review import _capture

MAX_CHART_SPANS = 12
MAX_CHART_SAMPLES = 600
MAX_REFERENCE_KNOTS = 4096
MAX_GAP_MARKERS = 50
MAX_EXAMPLES_SHOWN = 5
REASONS = {
    "source_interval_interrupted": "Source gap or duplicate timestamp",
    "unknown_phase_sample": "Unknown phase sample",
    "phase_ended_before_coverage_completed": "Active phase ended before reference coverage completed",
    "invalid_active_measurement": "Missing or invalid active measurement",
    "activation_not_observed": "Activation not observed",
    "no_observed_precharge_activation": "No observed inactive-to-active transition",
    "capture_ended_before_reference_horizon": "Capture ended before the reference horizon",
}


def _text(value):
    return escape(str(value))


def _number(value):
    return "unavailable" if value is None else f"{value:.6g}"


def _value(current, pack, bus):
    magnitude = abs(float(current)) if math.isfinite(current) else None
    gap = None
    if math.isfinite(pack) and pack > 0 and math.isfinite(bus):
        fraction = (float(pack) - float(bus)) / float(pack)
        if math.isfinite(fraction):
            gap = fraction
    return magnitude, gap


def _plot_rows(span, arrays, lines, horizon, max_gap):
    time, _, current, pack, bus = arrays
    start, stop = span["source_active_start_index"], span["source_active_stop_index_exclusive"]
    qualified_stop = start + span["reviewed_samples"]
    stride = max(1, math.ceil((stop - start) / MAX_CHART_SAMPLES))
    examples = {
        item["sample_index"]: (
            item["current_excess_a"] > 0,
            item["voltage_gap_fraction_excess"] > 0,
        )
        for item in span["examples"][:MAX_EXAMPLES_SHOWN]
    }
    retained, extrema, gaps = {}, {}, []
    count = gap_count = missing_count = 0
    last = None
    for i in range(start, stop):
        elapsed = float(_decimal_delta(time[i], time[start]))
        if not math.isfinite(elapsed) or _above(elapsed, horizon):
            break
        values = _value(current[i], pack[i], bus[i])
        row = (
            i,
            elapsed,
            *values,
            i < qualified_stop,
            tuple(lines[i]),
            examples.get(i, (False, False)),
        )
        count += 1
        if any(value is None for value in values):
            missing_count += 1
        if i > start:
            interval = float(_decimal_delta(time[i], time[i - 1]))
            if interval <= 0 or _above(interval, max_gap):
                gap_count += 1
                if len(gaps) < MAX_GAP_MARKERS:
                    gaps.append((last[1], elapsed, lines[i][0], interval == 0))
        for metric, value in enumerate(values):
            if value is not None:
                for kind in ("min", "max"):
                    key = (metric, kind)
                    if key not in extrema or (
                        value < extrema[key][metric + 2]
                        if kind == "min"
                        else value > extrema[key][metric + 2]
                    ):
                        extrema[key] = row
        if (
            (i - start) % stride == 0
            or i in examples
            or i in (qualified_stop - 1, qualified_stop)
            or (missing_count == 1 and any(value is None for value in values))
        ):
            retained[i] = row
        last = row
    for row in [*extrema.values(), *([last] if last else [])]:
        retained[row[0]] = row
    return sorted(retained.values()), gaps, count, gap_count, missing_count


def _chart(span, rows, gaps, envelope, metric):
    left, top, width, height = 88, 24, 630, 195
    horizon = envelope[-1][0]
    low_column = 1 if metric == 0 else 3
    values = [float(knot[column]) for knot in envelope for column in (low_column, low_column + 1)]
    values += [row[metric + 2] for row in rows if row[metric + 2] is not None]
    low, high = min(values), max(values)
    scale = max(abs(low), abs(high), 1)
    lower, upper = low / scale, high / scale

    def x(value):
        return left + width * (value / horizon)

    def y(value):
        fraction = ((value / scale) - lower) / (upper - lower) if high != low else 0.5
        return top + 6 + (height - 12) * (1 - fraction)

    name = "Current magnitude (A)" if metric == 0 else "Relative voltage gap (fraction)"
    chart_id = f"plot-{span['span_index']}-{metric}"
    out = [
        f'<svg viewBox="0 0 760 280" role="img" aria-labelledby="{chart_id}">',
        f'<title id="{chart_id}">{_text(name)}; recorded points and declared reference</title>',
        f'<text x="{left}" y="15" class="plot-title">{_text(name)}</text>',
    ]
    if not span["declared_interval_covered"]:
        end = span["last_qualified_elapsed_s"] or 0
        out.append(
            f'<rect class="uncovered" x="{x(end):.3f}" y="{top}" '
            f'width="{max(0, x(horizon) - x(end)):.3f}" height="{height}"/>'
        )
    for a, b, line, duplicate in gaps:
        if duplicate:
            out.append(
                f'<path class="duplicate" d="M{x(a):.3f},{top} v{height}">'
                f"<title>Duplicate source time at CSV line {line}</title></path>"
            )
        else:
            out.append(
                f'<rect class="gap" x="{x(a):.3f}" y="{top}" width="{x(b) - x(a):.3f}" '
                f'height="{height}"><title>Source gap before CSV line {line}</title></rect>'
            )
    for tick in range(5):
        ratio = tick / 4
        value = low * (1 - ratio) + high * ratio
        yy = y(value)
        out.append(
            f'<path class="grid" d="M{left},{yy:.3f} h{width}"/>'
            f'<text class="tick" x="{left - 8}" y="{yy + 4:.3f}" text-anchor="end">{value:.4g}</text>'
            f'<text class="tick" x="{x(horizon * ratio):.3f}" y="238" text-anchor="middle">'
            f"{horizon * ratio:.4g}</text>"
        )
    band = [(x(knot[0]), y(knot[low_column])) for knot in envelope]
    band += [(x(knot[0]), y(knot[low_column + 1])) for knot in reversed(envelope)]
    points = " ".join(f"{xx:.3f},{yy:.3f}" for xx, yy in band)
    out.append(f'<polygon class="band" points="{points}"/>')
    for row in rows:
        index, elapsed, current, gap, qualified, source_lines, example = row
        value = current if metric == 0 else gap
        title = _text(
            f"CSV lines {source_lines[0]}-{source_lines[1]}; source index {index}; "
            f"elapsed {elapsed:.17g} s; {name}: {_number(value)}; "
            + ("observer-qualified" if qualified else "not compared")
        )
        ident = f"sample-{span['span_index']}-{index}-{metric}"
        if value is None:
            out.append(
                f'<path id="{ident}" class="missing" data-source-index="{index}" '
                f'd="M{x(elapsed) - 3:.3f},{top + height - 3} l6,6 m-6,0 l6,-6">'
                f"<title>{title}; missing or invalid measurement</title></path>"
            )
        else:
            kind = "qualified" if qualified else "raw"
            out.append(
                f'<circle id="{ident}" class="{kind}" data-source-index="{index}" '
                f'cx="{x(elapsed):.3f}" cy="{y(value):.3f}" r="3"><title>{title}</title></circle>'
            )
            if example[metric]:
                out.append(
                    f'<circle class="departure" cx="{x(elapsed):.3f}" cy="{y(value):.3f}" '
                    f'r="5"><title>Recorded departure example: {title}</title></circle>'
                )
    out.append(
        f'<path class="axis" d="M{left},{top} v{height} h{width}"/>'
        '<text x="400" y="264" text-anchor="middle">Seconds from first recorded active sample</text>'
        "</svg>"
    )
    return "".join(out)


def _span(span, arrays, lines, envelope, max_gap, chart_enabled):
    ordinal = span["span_index"]
    covered = span["declared_interval_covered"]
    state = "Reference interval covered" if covered else "Incomplete coverage"
    reasons = (
        ", ".join(
            REASONS.get(reason, reason.replace("_", " ")) for reason in span["incomplete_reasons"]
        )
        or "none"
    )
    bracket = span["observed_start_bracket_s_decimal"]
    bracket_text = "not observed" if bracket is None else " to ".join(bracket) + " s"
    first, last = span["source_active_csv_line_range_inclusive"]
    out = [
        (
            f'<details id="span-{ordinal}" open><summary>Span {ordinal + 1}: {_text(state)}; '
            f"observed departures: {span['outside_envelope_samples']}</summary>"
        ),
        (
            f"<p>Active CSV lines {first}–{last}; exact source times "
            f"{_text(span['active_start_time_s_decimal'])} to {_text(span['active_end_time_s_decimal'])} s. "
            f"Observed start bracket: {_text(bracket_text)}.</p>"
        ),
        (
            f"<p>Compared samples: {span['reviewed_samples']}; last qualified elapsed time: "
            f"{_text(_number(span['last_qualified_elapsed_s']))} s. "
            f"Incomplete reasons: <strong>{_text(reasons)}</strong>.</p>"
        ),
    ]
    if chart_enabled:
        rows, gaps, count, gap_count, missing_count = _plot_rows(
            span, arrays, lines, envelope[-1][0], max_gap
        )
        out.append(
            f"<p>Display: {len(rows)} of {count} active rows inside the reference window; "
            f"Rows with a missing/invalid plotted measurement: {missing_count}. "
            f"Source interruptions: {gap_count}; {len(gaps)} marked. "
            "Display sampling retains metric extrema and the listed departure examples.</p>"
        )
        for metric in (0, 1):
            out.append(
                '<div class="chart" role="region" aria-label="Precharge plot" tabindex="0">'
                + _chart(span, rows, gaps, envelope, metric)
                + "</div>"
            )
    else:
        out.append(
            "<p>Charts omitted by display limits; complete observations remain in review.json.</p>"
        )
    examples = span["examples"][:MAX_EXAMPLES_SHOWN]
    out.append(
        "<table><caption>Recorded departure examples (up to five per span)</caption>"
        "<thead><tr><th>CSV lines</th><th>Elapsed (s)</th><th>Current (A)</th>"
        "<th>Voltage gap</th><th>Current bounds (A)</th><th>Gap bounds</th></tr></thead><tbody>"
    )
    for item in examples:
        line_range = "–".join(map(str, item["source_csv_line_range_inclusive"]))
        label = (
            f'<a href="#sample-{ordinal}-{item["sample_index"]}-0">{line_range}</a>'
            if chart_enabled
            else line_range
        )
        out.append(
            f"<tr><td>{label}</td>"
            + "".join(
                f"<td>{_text(item[key])}</td>"
                for key in (
                    "elapsed_s",
                    "current_a",
                    "voltage_gap_fraction",
                    "declared_current_bounds_a",
                    "declared_voltage_gap_bounds",
                )
            )
            + "</tr>"
        )
    if not examples:
        out.append(
            '<tr><td colspan="6">No examples recorded; inspect departure counts and coverage.</td></tr>'
        )
    out.append(
        f"</tbody></table><p>Stored examples: {len(span['examples'])}; "
        f"shown: {len(examples)}. Example counts may be capped.</p></details>"
    )
    return "".join(out)


STYLE = """
body{font:16px system-ui;color:#182b3a;background:#f5f7fa;margin:0}
main{max-width:1040px;margin:auto;padding:28px}h1{font-size:2rem}
header,section,details{background:white;padding:20px;margin:18px 0;border:1px solid #d5dfe7;border-radius:8px}
summary{cursor:pointer;font-weight:650}p{line-height:1.55}code,dd{overflow-wrap:anywhere}
dl{display:grid;grid-template-columns:14rem 1fr;gap:8px}dd{margin:0}
table{border-collapse:collapse;display:block;overflow:auto;width:100%;font-size:.9rem}
th,td{border-bottom:1px solid #d5dfe7;padding:9px;text-align:left}caption{text-align:left;font-weight:650}
.chart{overflow-x:auto}svg{width:100%;min-width:760px;height:auto;background:#fff}.tick{font:11px system-ui}.plot-title{font:bold 13px system-ui}
.grid{stroke:#dce3ea;stroke-width:1}.axis{fill:none;stroke:#496276}
.band{fill:#8fc6c0;fill-opacity:.28;stroke:#387e79;stroke-width:1}
.qualified{fill:#175ea8}.raw{fill:#647581;fill-opacity:.65}.departure{fill:none;stroke:#b02734;stroke-width:2}
.gap{fill:#f6b84e;fill-opacity:.22}.duplicate{fill:none;stroke:#a66700;stroke-dasharray:4 3}
.uncovered{fill:#747e8b;fill-opacity:.12}.missing{fill:none;stroke:#8a4b25;stroke-width:1.5}
.note{border-left:4px solid #a66700;padding-left:12px}a{color:#175ea8}
@media(max-width:650px){main{padding:10px}dl{grid-template-columns:1fr}dd{margin-bottom:10px}}
@media print{svg{min-width:0}body{background:white}details,section{break-inside:avoid}summary{list-style:none}}
"""


def render_precharge_html(report, capture_raw):
    """Display hash-bound source bytes; do not re-evaluate or alter the review."""
    if hashlib.sha256(capture_raw).hexdigest() != report["capture"]["sha256"]:
        raise ValueError("HTML capture bytes do not match the reviewed CSV")
    arrays, lines = _capture(capture_raw)
    if len(lines) != report["capture"]["data_records"]:
        raise ValueError("HTML source row count does not match the review")
    declaration = report["context"]["declaration"]
    envelope = declaration["envelope"]
    review = report["review"]
    charts_enabled = len(envelope) <= MAX_REFERENCE_KNOTS
    report_bytes = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    out = [
        (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>BatteryLog Research — Precharge observations</title><style>{STYLE}</style></head><body><main>"
        ),
        (
            "<header><h1>Precharge observations</h1>"
            '<p class="note">Recorded observations and caller-declared reference bands. '
            "This report does not establish physical acceptance or diagnose a fault.</p>"
        ),
        (
            f"<p>Input kind: <strong>{_text(declaration['input_kind'])}</strong>. "
            f"Source samples: {review['source_samples']}; unknown-phase samples: {review['unknown_phase_samples']}. "
            f"Active spans: {len(review['active_spans'])}; reference intervals covered: "
            f"{review['covered_reference_intervals']}; compared samples: {review['reviewed_samples']}; "
            f"observed departures: {review['outside_envelope_samples']}.</p></header>"
        ),
        (
            "<section><h2>Reading the plots</h2><p>Points are recorded samples; measurement values are not "
            "interpolated. The shaded reference band is piecewise linear between the declared knots. "
            "The voltage gap is (pack voltage − DC-link voltage) / pack voltage.</p>"
            "<p>Blue: observer-qualified sample. Gray: not compared. Red ring: a recorded departure example "
            "(examples may be capped). Cross: missing/invalid plotted measurement. Amber: source gap or "
            "duplicate timestamp. Gray background: reference tail not covered by the observer.</p>"
            "<p>Time zero is the first recorded active sample, not physical switch time. "
            "Coverage describes the observer's sampling rule; it does not reconstruct measurements "
            "between points. Later samples do not restore qualification after an interruption. "
            "Plots scroll horizontally on narrow screens.</p>"
            f"<p>Display limits: first {MAX_CHART_SPANS} spans; approximately {MAX_CHART_SAMPLES} source "
            f"points per span plus extrema/examples; at most {MAX_GAP_MARKERS} interruption markers. "
            f"All spans are summarized. Reference curves with more than {MAX_REFERENCE_KNOTS} knots "
            "are omitted rather than approximated. Points outside the declared reference window "
            "are not plotted. Complete observations and reference knots are in review.json.</p></section>"
        ),
        "<section><h2>Sources and measurement context</h2><dl>",
    ]
    metadata = [
        ("Capture", report["capture"]["name"]),
        ("Capture SHA-256", report["capture"]["sha256"]),
        ("Context", report["context"]["name"]),
        ("Context SHA-256", report["context"]["sha256"]),
        ("Review JSON SHA-256", hashlib.sha256(report_bytes).hexdigest()),
        ("Reference horizon (s)", envelope[-1][0]),
        ("Maximum source gap (s)", declaration["max_gap_s"]),
        *declaration["measurement_context"].items(),
    ]
    out.extend(f"<dt>{_text(key)}</dt><dd>{_text(value)}</dd>" for key, value in metadata)
    out.append(
        '</dl><p><a href="review.json">Complete review JSON</a> · <a href="index.html">Review index</a></p></section>'
    )
    for span in review["active_spans"]:
        out.append(
            _span(
                span,
                arrays,
                lines,
                envelope,
                declaration["max_gap_s"],
                charts_enabled and span["span_index"] < MAX_CHART_SPANS,
            )
        )
    if not review["active_spans"]:
        out.append(
            "<section><h2>No active spans recorded</h2><p>No precharge comparison was made.</p></section>"
        )
    out.append("</main></body></html>")
    return "".join(out)
