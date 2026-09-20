from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile

from batterylog.analysis.report_series import ReportSeries
from batterylog.models import AnalysisResult

from .evidence import ReportMetadata
from .plots import render_report_plots


def _fmt_number(value: float | None) -> str:
    if value is None:
        return "Not configured"
    return f"{value:.12g}"


def _metric_row(label: str, value: str) -> str:
    return f'<tr><th scope="row">{escape(label)}</th><td>{escape(value)}</td></tr>'


def _limits_rows(result: AnalysisResult) -> str:
    limits = result["limits_applied"]
    items = [
        ("Cell minimum voltage", limits["cell_min_v"], "V"),
        ("Cell maximum voltage", limits["cell_max_v"], "V"),
        ("Maximum cell delta", limits["imbalance_max_v"], "V"),
        ("Minimum temperature", limits["temperature_min_c"], "degC"),
        ("Maximum temperature", limits["temperature_max_c"], "degC"),
    ]
    rows: list[str] = []
    for label, value, unit in items:
        rendered = _fmt_number(value)
        if value is not None:
            rendered = f"{rendered} {unit}"
        rows.append(_metric_row(label, rendered))
    return "".join(rows)


def _metadata_rows(
    result: AnalysisResult,
    metadata: ReportMetadata | None,
) -> str:
    if metadata is None:
        items = [
            ("BatteryLog version", "Not specified"),
            ("Result schema", str(result["schema_version"])),
            ("Generated UTC", "Not specified"),
            ("Source", "Not specified"),
            ("Source SHA-256", "Not specified"),
            ("Validation config", "Not specified"),
            ("Config SHA-256", "Not specified"),
        ]
    else:
        config_name = metadata.config.name if metadata.config else "Not provided"
        config_sha256 = metadata.config.sha256 if metadata.config else "Not applicable"
        items = [
            ("BatteryLog version", metadata.batterylog_version),
            ("Result schema", str(result["schema_version"])),
            ("Generated UTC", metadata.generated_at_utc),
            ("Source", metadata.source.name),
            ("Source SHA-256", metadata.source.sha256),
            ("Validation config", config_name),
            ("Config SHA-256", config_sha256),
        ]

    return "".join(_metric_row(label, value) for label, value in items)


def _analysis_options_rows(result: AnalysisResult) -> str:
    max_gap_s = result["analysis_options"]["max_event_gap_s"]
    if max_gap_s is None:
        rendered = "Row contiguity only"
    else:
        rendered = f"{max_gap_s:.12g} s"
    return _metric_row("Maximum event gap", rendered)


def _comparison_policy_rows(result: AnalysisResult) -> str:
    policy = result["comparison_policy"]
    items = [
        ("Comparison mode", "Strict > / < with binary64 boundary guard"),
        (
            "Relative float tolerance",
            f"{policy['relative_tolerance']:.12g}",
        ),
        (
            "Absolute float tolerance",
            f"{policy['absolute_tolerance']:.12g}",
        ),
    ]
    return "".join(_metric_row(label, value) for label, value in items)


def _signal_mapping_rows(result: AnalysisResult) -> str:
    mapping = result["signal_mapping"]

    if mapping["mode"] == "canonical":
        items = [
            ("Signal mapping mode", "Canonical schema"),
            ("Timestamp source", mapping["timestamp_source"]),
            ("Cell voltage mapping", "Canonical cell_<n>_v"),
            ("Temperature mapping", "Canonical temp_<n>_c or temp_c"),
        ]
    else:
        items = [
            ("Signal mapping mode", "Explicit"),
            ("Timestamp source", mapping["timestamp_source"]),
            (
                "Cell voltage pattern",
                mapping["cell_voltage_pattern"] or "Not specified",
            ),
            (
                "Temperature pattern",
                mapping["temperature_pattern"] or "Not specified",
            ),
        ]

    return "".join(_metric_row(label, value) for label, value in items)


def _violation_rows(result: AnalysisResult) -> str:
    rows: list[str] = []
    for event in result["violations"]:
        signals = ", ".join(event["signals"])
        rows.append(
            "<tr>"
            f"<td><code>{escape(event['code'])}</code></td>"
            f"<td>{event['start_time_s']:.12g}</td>"
            f"<td>{event['end_time_s']:.12g}</td>"
            f"<td>{event['peak_time_s']:.12g}</td>"
            f"<td>{event['measured_value']:.12g} {escape(event['unit'])}</td>"
            f"<td>{event['limit_value']:.12g} {escape(event['unit'])}</td>"
            f"<td>{escape(signals)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _status_message(result: AnalysisResult) -> str:
    status = result["validation_status"]
    if status == "NOT_EVALUATED":
        return "No engineering rules were evaluated. This report contains metrics only."
    if status == "PASS":
        return "All evaluated engineering rules passed."
    return "One or more evaluated engineering rules failed."


def _measured_metric_rows(result: AnalysisResult) -> str:
    return "".join(
        [
            _metric_row(
                "Maximum cell voltage",
                f"{result['max_cell_voltage_v']:.12g} V",
            ),
            _metric_row(
                "Minimum cell voltage",
                f"{result['min_cell_voltage_v']:.12g} V",
            ),
            _metric_row(
                "Maximum cell delta",
                f"{result['max_delta_v']:.12g} V",
            ),
            _metric_row(
                "Maximum temperature",
                f"{result['max_temperature_c']:.12g} degC",
            ),
            _metric_row(
                "Minimum temperature",
                f"{result['min_temperature_c']:.12g} degC",
            ),
        ]
    )


def render_html_report(
    result: AnalysisResult,
    *,
    metadata: ReportMetadata | None = None,
    series: ReportSeries | None = None,
) -> str:
    status = result["validation_status"]
    rules = ", ".join(result["rules_evaluated"]) or "None"
    violations = _violation_rows(result)
    violation_section = (
        f"<table><thead><tr><th>Code</th><th>Start (s)</th><th>End (s)</th>"
        f"<th>Worst (s)</th><th>Measured</th><th>Limit</th><th>Signals</th>"
        f"</tr></thead><tbody>{violations}</tbody></table>"
        if violations
        else "<p>No violation events were recorded.</p>"
    )
    plot_section = render_report_plots(result, series) if series is not None else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BatteryLog Validation Report</title>
<style>
:root {{ color-scheme: light dark; font-family: Inter, Segoe UI, Arial, sans-serif; }}
body {{ max-width: 1100px; margin: 0 auto; padding: 32px; line-height: 1.45; }}
header, section {{ margin-bottom: 28px; }}
.status {{ border: 2px solid currentColor; border-radius: 10px; padding: 16px; }}
.status strong {{ font-size: 1.5rem; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
.card {{ border: 1px solid #8886; border-radius: 8px; padding: 14px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border-bottom: 1px solid #8886; padding: 9px; text-align: left; vertical-align: top; }}
code {{ font-family: ui-monospace, Consolas, monospace; }}
.small {{ opacity: 0.8; }}
.plot-card {{ border: 1px solid #8886; border-radius: 8px; padding: 12px; margin: 16px 0; overflow-x: auto; }}
.plot-card figcaption {{ display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }}
.plot-legend {{ font-size: 0.85rem; opacity: 0.85; }}
.legend-primary::before, .legend-secondary::before {{ content: ""; display: inline-block; width: 18px; height: 3px; margin: 0 5px 3px 10px; vertical-align: middle; }}
.legend-primary::before {{ background: #2563eb; }}
.legend-secondary::before {{ background: #16a34a; }}
.timeseries-chart {{ width: 100%; min-width: 680px; height: auto; display: block; }}
.chart-grid {{ stroke: currentColor; stroke-opacity: 0.12; stroke-width: 1; }}
.chart-axis {{ stroke: currentColor; stroke-opacity: 0.55; stroke-width: 1.2; }}
.chart-tick {{ fill: currentColor; opacity: 0.72; font-size: 11px; }}
.chart-envelope {{ fill: #3b82f6; fill-opacity: 0.12; stroke: none; }}
.series-primary, .series-secondary {{ fill: none; stroke-width: 1.7; vector-effect: non-scaling-stroke; }}
.series-primary {{ stroke: #2563eb; }}
.series-secondary {{ stroke: #16a34a; }}
.limit-line {{ stroke: #d97706; stroke-width: 1.4; stroke-dasharray: 7 5; vector-effect: non-scaling-stroke; }}
.limit-label {{ fill: #d97706; font-size: 11px; }}
.violation-window {{ fill: #dc2626; fill-opacity: 0.10; }}
.violation-peak {{ fill: #dc2626; stroke: white; stroke-width: 1.5; vector-effect: non-scaling-stroke; }}
.plot-note {{ margin-top: -4px; }}
</style>
</head>
<body>
<header>
<h1>Battery Validation Report</h1>
<p class="small">Generated by BatteryLog.</p>
</header>
<section class="status">
<strong>{escape(status)}</strong>
<p>{escape(_status_message(result))}</p>
</section>
<section>
<h2>Evidence</h2>
<table><tbody>{_metadata_rows(result, metadata)}</tbody></table>
</section>
<section>
<h2>Dataset summary</h2>
<div class="grid">
<div class="card"><strong>Rows analyzed</strong><br>{result["rows_analyzed"]}</div>
<div class="card"><strong>Cells detected</strong><br>{result["cells_detected"]}</div>
<div class="card"><strong>Temperature sensors</strong><br>{result["temperature_sensors_detected"]}</div>
<div class="card"><strong>Violation events</strong><br>{len(result["violations"])}</div>
</div>
</section>
<section>
<h2>Measured extrema</h2>
<table><tbody>{_measured_metric_rows(result)}</tbody></table>
</section>
{plot_section}
<section>
<h2>Validation configuration</h2>
<p>Rules evaluated: <code>{escape(rules)}</code></p>
<table><tbody>{_limits_rows(result)}{_analysis_options_rows(result)}{_comparison_policy_rows(result)}{_signal_mapping_rows(result)}</tbody></table>
</section>
<section>
<h2>Violation events</h2>
{violation_section}
</section>
</body>
</html>
"""


def write_html_report(
    result: AnalysisResult,
    output_path: str | Path,
    *,
    metadata: ReportMetadata | None = None,
    series: ReportSeries | None = None,
) -> Path:
    path = Path(output_path)
    content = render_html_report(result, metadata=metadata, series=series)

    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)

        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise

    return path
