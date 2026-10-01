"""Windows-only offline Edge diagnostic; see docs/0.10_REPORT_NAVIGATION_REVIEW.md."""

import json
import runpy
import threading
from pathlib import Path
from time import perf_counter

import psutil
from playwright.sync_api import sync_playwright

root = Path.cwd()
out = root / "dist" / "report-review"
bench = runpy.run_path(str(root / "benchmarks" / "benchmark_mf4_analysis.py"))
out.mkdir(parents=True, exist_ok=True)
source = out / "pressure-100000.mf4"
if not source.exists():
    bench["_write_synthetic_mf4"](
        source,
        rows=100000,
        cells=4,
        temperatures=2,
        layout="multi-group",
        scenario="event-pressure",
    )
report = out / "pressure-100000-after.html"
started = perf_counter()
result = bench["_run_batterylog_workload"](source, mode="report", report_path=report)
generation = perf_counter() - started
assert len(result["violations"]) == 100000
before_path = out / "result-before.json"
unchanged = None
if before_path.exists():
    before = json.loads(before_path.read_text(encoding="utf-8"))
    assert before == result
    unchanged = True
print("100000 events; report generated; baseline equality: " + str(unchanged), flush=True)
cases = []
with sync_playwright() as playwright:
    for repeat in range(1, 4):
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        stop = threading.Event()
        resources = {"owned_edge_rss_sum_peak_bytes": 0, "aborted": False}

        def monitor(stop=stop, resources=resources):
            while not stop.wait(0.2):
                owned = [
                    p
                    for p in psutil.Process().children(recursive=True)
                    if p.name().lower() == "msedge.exe"
                ]
                try:
                    memory = sum(p.memory_info().rss for p in owned)
                    resources["owned_edge_rss_sum_peak_bytes"] = max(
                        resources["owned_edge_rss_sum_peak_bytes"], memory
                    )
                    if memory > 4 * 1024**3 or psutil.virtual_memory().available < 1024**3:
                        resources["aborted"] = True
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
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.route(
                "**/*",
                lambda route: (
                    route.continue_() if route.request.url.startswith("file:") else route.abort()
                ),
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
            started = perf_counter()
            page.goto(report.as_uri(), wait_until="load", timeout=60000)
            load = perf_counter() - started
            assert (
                page.locator("#event-data").evaluate("(e)=>JSON.parse(e.textContent).length")
                == 100000
            )
            region = page.get_by_role("region", name="Violation events")
            rows = region.locator("tbody tr")
            assert rows.count() == 100
            assert "1–100 of 100000" in page.locator("#event-count").inner_text()
            nodes = page.locator("*").count()
            height = page.evaluate("document.documentElement.scrollHeight")
            started = perf_counter()
            page.get_by_role("button", name="Last page", exact=True).click()
            rows.last.scroll_into_view_if_needed()
            last = perf_counter() - started
            assert "99901–100000" in page.locator("#event-count").inner_text()
            assert rows.last.locator("td").nth(1).inner_text() == "9999.8"
            header = region.locator("thead th").first.bounding_box()
            assert header["y"] >= 0 and header["y"] + header["height"] <= 1000
            region.focus()
            scroll_top = region.evaluate("(e)=>e.scrollTop")
            page.keyboard.press("ArrowUp")
            page.wait_for_timeout(200)
            assert region.evaluate("(e)=>e.scrollTop") < scroll_top
            if repeat == 1:
                page.screenshot(path=str(out / "after-last.png"))
            started = perf_counter()
            page.get_by_role("link", name="Show CELL_OVERVOLTAGE events", exact=True).click()
            rule_filter = perf_counter() - started
            assert "of 50000 matching events" in page.locator("#event-count").inner_text()
            assert rows.first.locator("td").first.inner_text() == "CELL_OVERVOLTAGE"
            page.locator("#event-from").fill("9000")
            page.locator("#event-to").fill("9001")
            page.get_by_role("button", name="Apply filters").click()
            assert rows.count() == 6
            assert rows.first.locator("td").nth(1).inner_text() == "9000"
            assert rows.last.locator("td").nth(1).inner_text() == "9001"
            assert rows.first.locator("td").all_text_contents()[4:] == [
                "4.5 V",
                "4.2 V",
                "1",
                "0",
                "0.3 V",
                "cell_1_v",
                "—",
            ]
            if repeat == 1:
                page.screenshot(path=str(out / "after-filter.png"))
            page.locator("#event-signal").select_option("cell_2_v")
            page.get_by_role("button", name="Apply filters").click()
            assert rows.count() == 0
            assert "No matching events" in page.locator("#event-count").inner_text()
            assert page.locator(".status strong").inner_text() == "FAIL"
            page.get_by_role("button", name="Reset filters").click()
            assert rows.count() == 100
            assert "1–100 of 100000" in page.locator("#event-count").inner_text()
            page.locator("#event-from").fill("2")
            page.locator("#event-to").fill("1")
            page.get_by_role("button", name="Apply filters").click()
            assert page.get_by_role("alert").inner_text() == "From must not exceed To."
            assert rows.count() == 100
            page.get_by_role("button", name="Reset filters").click()
            assert not page.get_by_role("alert").inner_text()
            page.emulate_media(media="print")
            assert region.evaluate("(e)=>getComputedStyle(e).maxHeight") == "none"
            assert not page.get_by_role("button", name="Apply filters").is_visible()
            assert "Printing includes the displayed page only." in page.locator("body").inner_text()
            assert not errors and not resources["aborted"]
            cases.append(
                {
                    "repeat": repeat,
                    "events": 100000,
                    "load_s": load,
                    "last_page_s": last,
                    "rule_filter_s": rule_filter,
                    "dom_nodes": nodes,
                    "document_height_px": height,
                    "live_event_rows": rows.count(),
                    "all_events_retained": True,
                    "raw_result_unchanged": unchanged,
                    "keyboard_scroll": True,
                    "range_matches": 6,
                    "no_match_status_preserved": True,
                    "invalid_range_rejected": True,
                    "print_current_page": True,
                    "page_errors": errors,
                    "browser_version": browser.version,
                    **resources,
                }
            )
            print(json.dumps(cases[-1]), flush=True)
        finally:
            stop.set()
            sampler.join()
            browser.close()
payload = {
    "environment": bench["_environment_metadata"](cells=4, temperatures=2),
    "source_bytes": source.stat().st_size,
    "report_bytes": report.stat().st_size,
    "generation_s": generation,
    "method": "Fresh offline headless Edge; 1440x1000; 3 repeats; RSS is summed owned-process working set, not unique physical memory; 200 ms samples; stop at 4 GiB sum or <1 GiB global available RAM",
    "cases": cases,
}
(root / "docs" / "benchmarks" / "0.10-windows-100k-after.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
