"""Attribute report wall time; run each invocation in a fresh process.

This diagnostic excludes workload imports and RSS sampling. It does not measure
peak memory or establish uninstrumented performance thresholds.
"""

import argparse
import importlib
import json
import runpy
from pathlib import Path
from time import perf_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.report.resolve():
        parser.error("report must not overwrite the source")

    benchmark = runpy.run_path(str(Path(__file__).with_name("benchmark_mf4_analysis.py")))
    cli = importlib.import_module("batterylog.__main__")
    html = importlib.import_module("batterylog.reporting.html")
    plots = importlib.import_module("batterylog.reporting.plots")
    timings: dict[str, float] = {}

    def instrument(owner, name: str, label: str) -> None:
        original = getattr(owner, name)

        def measured(*args, **kwargs):
            started = perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                timings[label] = timings.get(label, 0.0) + perf_counter() - started

        setattr(owner, name, measured)

    # The combined 0.10 review tree uses AnalysisService; main still exposes the
    # previous internal CLI call. Keep both review trees measurable.
    if hasattr(cli, "AnalysisService"):
        instrument(cli.AnalysisService, "analyze_file", "analysis_and_series")
    else:
        instrument(cli, "analyze_battery_file_with_report_series", "analysis_and_series")
    instrument(cli, "render_json_result", "json_render")
    instrument(cli, "write_html_report", "html_render_and_write")
    if hasattr(html, "_iter_html_report"):
        original_sections = html._iter_html_report

        def measured_sections(*args, **kwargs):
            sections = iter(original_sections(*args, **kwargs))
            while True:
                started = perf_counter()
                try:
                    section = next(sections)
                except StopIteration:
                    return
                finally:
                    timings["html_render"] = (
                        timings.get("html_render", 0.0) + perf_counter() - started
                    )
                yield section

        html._iter_html_report = measured_sections
    else:
        instrument(html, "render_html_report", "html_render")
    instrument(html, "_violation_rows", "violation_table")
    instrument(html, "render_report_plots", "plots")
    instrument(plots, "_event_windows", "plot_event_windows")
    instrument(plots, "_event_peaks", "plot_event_peaks")
    instrument(benchmark["json"], "loads", "benchmark_json_decode")
    started = perf_counter()
    result = benchmark["_run_batterylog_workload"](
        args.source, mode="report", report_path=args.report
    )
    timings["workload_total"] = perf_counter() - started
    print(
        json.dumps(
            {
                "environment": benchmark["_environment_metadata"](
                    cells=result["cells_detected"],
                    temperatures=result["temperature_sensors_detected"],
                ),
                "rows_analyzed": result["rows_analyzed"],
                "rows_excluded": result["rows_excluded"],
                "events": len(result["violations"]),
                "report_bytes": args.report.stat().st_size,
                "timings_s": timings,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
