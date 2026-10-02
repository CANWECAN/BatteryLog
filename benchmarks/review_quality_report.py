"""Offline Windows Edge diagnostic for the data-quality event table."""

import json
import subprocess
import sys
import threading
from io import BytesIO
from pathlib import Path
from time import perf_counter

import psutil
from playwright.sync_api import sync_playwright

from batterylog.analysis.streaming import analyze_battery_file_streaming
from batterylog.config import DataQualityConfig, ValidationLimits
from batterylog.reporting import render_html_report, render_json_result

stage = sys.argv[1]
root = Path.cwd()
out = root / "dist" / "quality-review"
out.mkdir(parents=True, exist_ok=True)
data = (
    "timestamp_s,cell_1_v,cell_2_v,temp_c\n"
    + "".join(f"{i},{'' if i % 2 == 0 else '3.7'},3.7,25\n" for i in range(200000))
).encode()
started = perf_counter()
result = analyze_battery_file_streaming(
    BytesIO(data),
    source_name="quality-pressure.csv",
    limits=ValidationLimits(cell_max_v=4.2),
    data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
)
assert len(result["data_quality"]["events"]) == 100000
assert result["rows_excluded"] == 100000
assert result["rows_analyzed"] == 100000
assert result["validation_status"] == "FAIL" and not result["violations"]
canonical = render_json_result(result)
baseline = out / "result-before.json"
if stage == "before":
    baseline.write_text(canonical, encoding="utf-8")
else:
    assert baseline.read_text(encoding="utf-8") == canonical
report = out / f"quality-{stage}.html"
report.write_text(render_html_report(result), encoding="utf-8")
generation = perf_counter() - started
cases = []
with sync_playwright() as pw:
    for repeat in range(1, 2 if stage == "before" else 4):
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
            nodes = page.locator("*").count()
            height = page.evaluate("document.documentElement.scrollHeight")
            rows = page.locator("#data-quality tbody tr").last
            if stage == "after":
                region = page.get_by_role("region", name="Data-quality events")
                live = region.locator("tbody tr")
                assert live.count() == 100
                assert (
                    page.locator("#quality-data").evaluate("(e)=>JSON.parse(e.textContent).length")
                    == 100000
                )
                started = perf_counter()
                page.locator("#quality-pages [data-page=last]").click()
                live.last.scroll_into_view_if_needed()
                last = perf_counter() - started
                assert live.last.locator("td").all_text_contents() == [
                    "MISSING_REQUIRED_VALUE",
                    "199999",
                    "199999",
                    "1",
                    "cell_1_v",
                ]
                assert "99901–100000" in page.locator("#quality-count").inner_text()
                header = region.locator("thead th").first.bounding_box()
                assert header["y"] >= 0 and header["y"] + header["height"] <= 1000
                page.locator("#quality-from").fill("199991")
                page.locator("#quality-to").fill("199999")
                started = perf_counter()
                page.locator("#quality-filters button[type=submit]").click()
                filtered = perf_counter() - started
                assert live.count() == 5
                assert [int(x) for x in live.locator("td:nth-child(2)").all_text_contents()] == [
                    199991,
                    199993,
                    199995,
                    199997,
                    199999,
                ]
                page.locator("#quality-from").fill("2")
                page.locator("#quality-to").fill("1")
                page.locator("#quality-filters button[type=submit]").click()
                assert page.locator("#quality-error").inner_text() == "From must not exceed To."
                assert live.count() == 5
                page.locator("#quality-filters button[type=reset]").click()
                assert live.count() == 100 and not page.locator("#quality-error").inner_text()
                assert page.locator(".status strong").inner_text() == "FAIL"
            else:
                started = perf_counter()
                rows.scroll_into_view_if_needed()
                last = perf_counter() - started
                live = page.locator("#data-quality tbody tr")
                filtered = None
            assert not errors and not resources["aborted"]
            cases.append(
                {
                    "repeat": repeat,
                    "load_s": load,
                    "last_page_or_scroll_s": last,
                    "range_filter_s": filtered,
                    "dom_nodes": nodes,
                    "document_height_px": height,
                    "live_quality_rows": live.count(),
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
    "code_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "code_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
    "stage": stage,
    "source_rows": 200000,
    "quality_events": 100000,
    "source_bytes": len(data),
    "report_bytes": report.stat().st_size,
    "generation_s": generation,
    "raw_result_unchanged": stage == "after",
    "method": "Offline fresh Edge; 1440x1000; 1 baseline and 3 after repeats; no plots to isolate table; 200 ms sampling; working-set sum is not unique RAM; stop at 4 GiB sum or <1 GiB available",
    "cases": cases,
}
(out / f"0.10-windows-quality-{stage}.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
