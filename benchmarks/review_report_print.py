"""Offline Edge/PDF regression review; needs retained inputs and optional dev tools."""

import hashlib
import importlib
import json
import os
import sys
import threading
from io import BytesIO
from pathlib import Path
from time import perf_counter

import psutil
from playwright.sync_api import sync_playwright

from batterylog import ValidationLimits
from batterylog.analysis.report_series import ReportSeries, ReportSeriesPoint
from batterylog.analysis.streaming import analyze_battery_file_with_report_series
from batterylog.reporting import write_html_report

root = Path(__file__).resolve().parents[1]
out = root / "dist" / "print-review"
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(out / "pdf-tools"))
pymupdf = importlib.import_module("pymupdf")


def prepare():
    import batterylog

    assert (
        Path(batterylog.__file__).resolve()
        == Path(os.environ["PYTHONPATH"]) / "batterylog/__init__.py"
    )
    small = BytesIO(
        b"timestamp_s,cell_1_v,cell_2_v,temp_1_c,temp_2_c,pack_current_a,pack_voltage_v\n"
        b"0,3.8,3.8,25,25,0,7.6\n1,4.5,3.6,60,-25,6,8.6\n"
        b"2,2.6,3.5,60,-25,-6,7.0\n3,3.8,3.8,25,25,0,7.6\n"
    )
    result, series = analyze_battery_file_with_report_series(
        small,
        source_name="all-charts.csv",
        limits=ValidationLimits(
            cell_min_v=2.8,
            cell_max_v=4.2,
            imbalance_max_v=0.08,
            temperature_min_c=-20,
            temperature_max_c=55,
            temperature_spread_max_c=10,
            pack_charge_max_a=5,
            pack_discharge_max_a=5,
            pack_current_positive_direction="charge",
            pack_voltage_cell_sum_max_delta_v=0.15,
        ),
    )
    workloads = [
        (
            "seven-charts",
            result,
            series,
            root.parent / "BatteryLog-chart-review/dist/chart-review/all-charts.html",
        )
    ]
    snapshot = json.loads(
        (
            root.parent
            / "BatteryLog-boundary-hunt/dist/boundary-hunt/real-inputs/mf4-100k-after-snapshot.json"
        ).read_text("utf-8")
    )
    spec = snapshot["series"]
    series = ReportSeries(
        points=tuple(ReportSeriesPoint(**p) for p in spec["points"]),
        source_rows=spec["source_rows"],
        max_points=spec["max_points"],
        strategy=spec["strategy"],
    )
    workloads.append(
        (
            "100k-mf4",
            snapshot["result"],
            series,
            root.parent
            / "BatteryLog-report-allocation/dist/allocation-review/after-rss-write-1.html",
        )
    )
    proof = []
    for name, result, series, baseline in workloads:
        target = out / f"{name}-after.html"
        write_html_report(result, target, series=series)
        before = baseline.read_text("utf-8")
        after = target.read_text("utf-8")
        removed = after.replace("  .plot-card { break-inside: avoid; }\n", "").replace(
            "  .timeseries-chart { min-width: 0; }\n", ""
        )
        assert before == removed
        proof.append(
            {
                "name": name,
                "html_equal_except_two_print_rules": True,
                "events": len(result["violations"]),
                "charts": after.count('<svg class="timeseries-chart"'),
            }
        )
    (out / "parity.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")


stage = sys.argv[1]
assert stage in {"before", "after"}
if stage == "after":
    prepare()
paths = {
    "seven-charts": root.parent / "BatteryLog-chart-review/dist/chart-review/all-charts.html",
    "100k-mf4": root.parent
    / "BatteryLog-report-allocation/dist/allocation-review/after-rss-write-1.html",
}
cases = []
with sync_playwright() as pw:
    for name, source in paths.items():
        path = out / f"{name}-{stage}.html" if stage == "after" else source
        browser = pw.chromium.launch(channel="msedge", headless=True)
        stop = threading.Event()
        guard = {"aborted": False, "owned_edge_rss_sum_peak_bytes": 0}
        started = perf_counter()

        def monitor(stop=stop, guard=guard, started=started):
            while not stop.wait(0.2):
                try:
                    owned = [
                        p
                        for p in psutil.Process().children(recursive=True)
                        if p.name().lower() == "msedge.exe"
                    ]
                    total = sum(p.memory_info().rss for p in owned)
                    guard["owned_edge_rss_sum_peak_bytes"] = max(
                        total, guard["owned_edge_rss_sum_peak_bytes"]
                    )
                    if (
                        total > 4 * 1024**3
                        or psutil.virtual_memory().available < 1024**3
                        or perf_counter() - started > 150
                    ):
                        guard["aborted"] = True
                        for p in reversed(owned):
                            try:
                                p.kill()
                            except psutil.NoSuchProcess:
                                pass
                        break
                except psutil.NoSuchProcess:
                    pass

        sampler = threading.Thread(target=monitor, daemon=True)
        sampler.start()
        try:
            page = browser.new_page(viewport={"width": 718, "height": 1000})
            page.route(
                "**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort()
            )
            errors = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            page.goto(path.as_uri(), wait_until="load", timeout=60000)
            overlays = page.get_by_role("checkbox", name="Show violation overlays")
            overlays.uncheck()
            if name == "100k-mf4":
                page.locator("#event-pages [data-page=last]").click()
            screen_min_widths = page.locator("svg.timeseries-chart").evaluate_all(
                "(es)=>es.map(e=>getComputedStyle(e).minWidth)"
            )
            assert set(screen_min_widths) == {"680px"}
            page.emulate_media(media="print")
            geometry = page.locator(".plot-card, .event-table, .quality-table").evaluate_all(
                "(es)=>es.map(e=>({kind:e.className,width:e.clientWidth,scroll:e.scrollWidth,"
                "overflow:getComputedStyle(e).overflowX}))"
            )
            chart_count = page.locator("svg.timeseries-chart").count()
            if stage == "after":
                assert all(g["width"] == g["scroll"] for g in geometry if g["kind"] == "plot-card")
                assert page.locator(".plot-card").evaluate_all(
                    "(es)=>es.every(e=>getComputedStyle(e).breakInside==='avoid')"
                )
                assert page.locator("svg.timeseries-chart").evaluate_all(
                    "(es)=>es.every(e=>getComputedStyle(e).minWidth==='0px')"
                )
            assert page.locator(
                ".violation-window, .violation-instant, .violation-peak"
            ).evaluate_all("(es)=>es.every(e=>getComputedStyle(e).display!=='none')")
            count_text = page.locator("#event-count").all_text_contents()
            pdf = out / f"{name}-{stage}.pdf"
            pdf_started = perf_counter()
            page.pdf(
                path=str(pdf),
                format="A4",
                print_background=True,
                margin={"top": "10mm", "bottom": "10mm", "left": "10mm", "right": "10mm"},
            )
            pdf_s = perf_counter() - pdf_started
            doc = pymupdf.open(pdf)
            text = "\n".join(p.get_text() for p in doc)
            chart_pages = [i for i, p in enumerate(doc) if "Time-series plots" in p.get_text()]
            caption_pages = [
                i + 1
                for i, p in enumerate(doc)
                if "Temperature spread" in p.get_text().splitlines()
            ]
            spread_tick_pages = [i + 1 for i, p in enumerate(doc) if p.search_for("91.8 degC")]
            if stage == "after" and name == "seven-charts":
                assert caption_pages == spread_tick_pages and len(caption_pages) == 1
            table_pages = [i for i, p in enumerate(doc) if "Violation events" in p.get_text()]
            selected = (
                list(range(len(doc)))
                if name == "seven-charts"
                else sorted(set(chart_pages + [1, 2] + table_pages + [len(doc) - 1]))
            )
            for index in selected:
                doc[index].get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).save(
                    str(out / f"{name}-{stage}-page-{index + 1}.png")
                )
            case = {
                "name": name,
                "stage": stage,
                "html_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "browser": browser.version,
                "pdf_bytes": pdf.stat().st_size,
                "pdf_pages": len(doc),
                "pdf_s": pdf_s,
                "chart_count": chart_count,
                "print_geometry": geometry,
                "event_count_text": count_text,
                "pdf_has_page_only_notice": "displayed page only" in text,
                "pdf_has_last_event": "99998" in text if name == "100k-mf4" else None,
                "selected_png_pages": [i + 1 for i in selected],
                "page_errors": errors,
                "spread_caption_pages": caption_pages,
                "spread_tick_pages": spread_tick_pages,
                "screen_chart_min_widths": screen_min_widths,
                **guard,
            }
            doc.close()
            cases.append(case)
            print(json.dumps(case), flush=True)
            assert not errors and not guard["aborted"]
            page.emulate_media(media="screen")
            assert not overlays.is_checked()
            assert page.locator(".plot-overlay-warning").is_visible()
        finally:
            stop.set()
            sampler.join()
            browser.close()
(out / f"{stage}.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
