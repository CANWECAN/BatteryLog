"""Offline Edge checks for native overlay visibility; see the chart review."""

import hashlib
import json
import runpy
import threading
from io import BytesIO
from pathlib import Path
from time import perf_counter

import psutil
from playwright.sync_api import sync_playwright

from batterylog import ValidationLimits
from batterylog.analysis.streaming import analyze_battery_file_with_report_series
from batterylog.reporting import render_html_report

root = Path.cwd()
out = root / "dist" / "chart-review"
out.mkdir(parents=True, exist_ok=True)
bench = runpy.run_path(str(root / "benchmarks" / "benchmark_mf4_analysis.py"))
source = root.parent / "BatteryLog-report-review/dist/report-review/pressure-100000.mf4"
report = out / "pressure-after.html"
result = bench["_run_batterylog_workload"](source, mode="report", report_path=report)
assert result == json.loads((out / "result-before.json").read_text(encoding="utf-8"))
before = (out / "pressure-before.html").read_text(encoding="utf-8")
after = report.read_text(encoding="utf-8")


# Compare all serialized chart geometry, limits and event metadata, not screenshots.
def svg_text(html):
    return [part.split("</svg>", 1)[0] for part in html.split('<svg class="timeseries-chart"')[1:]]


assert svg_text(before) == svg_text(after)
small_source = BytesIO(
    b"timestamp_s,cell_1_v,cell_2_v,temp_1_c,temp_2_c,pack_current_a,pack_voltage_v\n"
    b"0,3.8,3.8,25,25,0,7.6\n1,4.5,3.6,60,-25,6,8.6\n"
    b"2,2.6,3.5,60,-25,-6,7.0\n3,3.8,3.8,25,25,0,7.6\n"
)
small_result, small_series = analyze_battery_file_with_report_series(
    small_source,
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
small_report = out / "all-charts.html"
small_report.write_text(render_html_report(small_result, series=small_series), encoding="utf-8")
selector = ".violation-window, .violation-instant, .violation-peak"
cases = []
with sync_playwright() as pw:
    workloads = [(small_report, True, 7), (small_report, False, 7)]
    workloads += [(report, True, 3)] * 3
    for repeat, (path, javascript, charts) in enumerate(workloads, 1):
        browser = pw.chromium.launch(channel="msedge", headless=True)
        stop = threading.Event()
        resources = {"owned_edge_rss_sum_peak_bytes": 0, "aborted": False}

        def monitor(stop=stop, resources=resources):
            while not stop.wait(0.2):
                try:
                    owned = [
                        p
                        for p in psutil.Process().children(recursive=True)
                        if p.name().lower() == "msedge.exe"
                    ]
                    memory = sum(p.memory_info().rss for p in owned)
                    resources["owned_edge_rss_sum_peak_bytes"] = max(
                        resources["owned_edge_rss_sum_peak_bytes"], memory
                    )
                    if memory > 4 * 1024**3 or psutil.virtual_memory().available < 1024**3:
                        resources["aborted"] = True
                        for process in reversed(owned):
                            try:
                                process.kill()
                            except psutil.NoSuchProcess:
                                pass
                        break
                except psutil.NoSuchProcess:
                    pass

        sampler = threading.Thread(target=monitor, daemon=True)
        sampler.start()
        try:
            page = browser.new_page(
                viewport={"width": 1440, "height": 1000}, java_script_enabled=javascript
            )
            page.route(
                "**/*",
                lambda route: (
                    route.continue_() if route.request.url.startswith("file:") else route.abort()
                ),
            )
            errors = []
            page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
            page.goto(path.as_uri(), wait_until="load", timeout=60000)
            assert page.locator("svg.timeseries-chart").count() == charts
            control = page.get_by_role("checkbox", name="Show violation overlays")
            assert control.is_checked()
            overlays = page.locator(selector)
            count = overlays.count()
            assert count > 0
            assert overlays.evaluate_all("(es)=>es.every(e=>getComputedStyle(e).display!=='none')")
            svg_hash = page.locator("svg.timeseries-chart").evaluate_all(
                "(es)=>es.map(e=>e.outerHTML).join('')"
            )
            table_state = None
            if path == report:
                assert count == 200000
                assert (
                    page.locator("#event-data").evaluate("(e)=>JSON.parse(e.textContent).length")
                    == 100000
                )
                page.locator("#event-pages [data-page=last]").click()
                table_state = page.locator("#event-count").inner_text()
                assert "99901–100000" in table_state
            table_snapshot = page.locator("#event-table, #quality-table").all_text_contents()
            control.focus()
            started = perf_counter()
            page.keyboard.press("Space")
            assert not control.is_checked()
            assert control.evaluate("(e)=>document.activeElement===e")
            assert overlays.evaluate_all("(es)=>es.every(e=>getComputedStyle(e).display==='none')")
            hide_s = perf_counter() - started
            assert page.locator(".plot-overlay-warning").is_visible()
            assert overlays.count() == count
            assert page.locator(".series-primary, .series-secondary, .limit-line").evaluate_all(
                "(es)=>es.every(e=>getComputedStyle(e).display!=='none')"
            )
            assert page.locator(".status strong").inner_text() == "FAIL"
            assert (
                page.locator("#event-table, #quality-table").all_text_contents() == table_snapshot
            )
            if table_state:
                assert page.locator("#event-count").inner_text() == table_state
            assert (
                page.locator("svg.timeseries-chart").evaluate_all(
                    "(es)=>es.map(e=>e.outerHTML).join('')"
                )
                == svg_hash
            )
            if path == report and repeat == 3:
                page.locator(".timeseries").screenshot(path=str(out / "pressure-hidden.png"))
            page.emulate_media(media="print")
            assert overlays.evaluate_all("(es)=>es.every(e=>getComputedStyle(e).display!=='none')")
            assert (
                not control.is_visible() and not page.locator(".plot-overlay-warning").is_visible()
            )
            page.emulate_media(media="screen")
            assert overlays.evaluate_all("(es)=>es.every(e=>getComputedStyle(e).display==='none')")
            page.locator('label[for="plot-overlays"]').click()
            assert control.is_checked()
            assert overlays.evaluate_all("(es)=>es.every(e=>getComputedStyle(e).display!=='none')")
            assert not page.locator(".plot-overlay-warning").is_visible()
            assert not errors and not resources["aborted"]
            cases.append(
                {
                    "workload": "100k-mf4" if path == report else "all-seven-charts",
                    "repeat": repeat,
                    "javascript": javascript,
                    "chart_count": charts,
                    "overlays_retained": count,
                    "hide_and_verify_s": hide_s,
                    "native_keyboard": True,
                    "label_restores": True,
                    "print_restores": True,
                    "svg_dom_unchanged": True,
                    "table_state_unchanged": True,
                    "browser_version": browser.version,
                    "page_errors": errors,
                    **resources,
                }
            )
            print(json.dumps(cases[-1]), flush=True)
        finally:
            stop.set()
            sampler.join()
            browser.close()
payload = {
    "source_checkpoint": "5dde0781adbf941aac63d605dc88e0f7ab55d193",
    "mf4_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "report_bytes": report.stat().st_size,
    "serialized_svgs_equal_parent": True,
    "complete_analysis_equal_parent": True,
    "method": "Fresh offline headless Edge; 1440x1000; all-seven-chart CSV with/without JS plus three 100k-MF4 runs; hide timing includes native input and computed-style verification of every overlay; working-set sum includes shared pages, 200 ms samples, not unique physical memory; stop at 4 GiB sum or <1 GiB globally available",
    "cases": cases,
}
(root / "docs/benchmarks/0.10-chart-overlay-after.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
