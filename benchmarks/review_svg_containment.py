"""Compare native offscreen containment on retained 100k-event SVG evidence; Windows Edge only."""

import hashlib
import json
import threading
from pathlib import Path
from time import perf_counter

import psutil
from playwright.sync_api import sync_playwright

root = Path.cwd()
out = root / "dist" / "retrospective-review"
out.mkdir(parents=True, exist_ok=True)
source = (
    root.parent
    / "BatteryLog-report-review"
    / "dist"
    / "report-review"
    / "pressure-100000-after.html"
)
baseline = source.read_text(encoding="utf-8")
candidate_css = """
.plot-card { content-visibility: auto; contain-intrinsic-size: auto 400px; }
@media print { .plot-card { content-visibility: visible; contain-intrinsic-size: none; } }
"""
paths = {}
for mode in ["baseline", "containment"]:
    report = out / ("svg-" + mode + ".html")
    html = (
        baseline if mode == "baseline" else baseline.replace("</style>", candidate_css + "</style>")
    )
    report.write_text(html, encoding="utf-8")
    assert html.count('class="violation-peak"') == baseline.count('class="violation-peak"')
    paths[mode] = report
cases = []
with sync_playwright() as pw:
    for repeat in range(1, 4):
        for mode in ["baseline", "containment"]:
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
                        route.continue_()
                        if route.request.url.startswith("file:")
                        else route.abort()
                    ),
                )
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                started = perf_counter()
                page.goto(paths[mode].as_uri(), wait_until="load", timeout=60000)
                load = perf_counter() - started
                initial_height = page.evaluate("document.documentElement.scrollHeight")
                assert (
                    page.locator("#event-data").evaluate("(e)=>JSON.parse(e.textContent).length")
                    == 100000
                )
                nodes = page.locator("*").count()
                chart_checks = []
                for index in range(page.locator(".plot-card").count()):
                    card = page.locator(".plot-card").nth(index)
                    started = perf_counter()
                    card.scroll_into_view_if_needed()
                    screenshot = card.screenshot()
                    elapsed = perf_counter() - started
                    chart_checks.append(
                        {
                            "chart": index,
                            "scroll_and_capture_s": elapsed,
                            "height_px": card.bounding_box()["height"],
                            "screenshot_sha256": hashlib.sha256(screenshot).hexdigest(),
                        }
                    )
                started = perf_counter()
                page.locator("#event-pages [data-page=last]").click()
                last_page = perf_counter() - started
                assert "99901–100000" in page.locator("#event-count").inner_text()
                assert (
                    page.get_by_role("region", name="Violation events")
                    .locator("tbody tr")
                    .last.locator("td")
                    .nth(1)
                    .inner_text()
                    == "9999.8"
                )
                assert page.locator(".status strong").inner_text() == "FAIL"
                visited_height = page.evaluate("document.documentElement.scrollHeight")
                page.emulate_media(media="print")
                assert all(
                    page.locator(".plot-card")
                    .nth(i)
                    .evaluate("(e)=>getComputedStyle(e).contentVisibility")
                    == "visible"
                    for i in range(len(chart_checks))
                )
                assert not errors and not resources["aborted"]
                case = {
                    "mode": mode,
                    "repeat": repeat,
                    "load_s": load,
                    "dom_nodes": nodes,
                    "last_page_s": last_page,
                    "initial_height_px": initial_height,
                    "visited_height_px": visited_height,
                    "charts": chart_checks,
                    "all_events_retained": True,
                    "print_visible": True,
                    "page_errors": errors,
                    "browser_version": browser.version,
                    **resources,
                }
                cases.append(case)
                print(json.dumps(case), flush=True)
            finally:
                stop.set()
                sampler.join()
                browser.close()
payload = {
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "source_bytes": source.stat().st_size,
    "source_checkpoint": "0a15b328b4244f47e7d03527dcf08575375f55f5",
    "candidate_css": candidate_css,
    "method": "3 alternating fresh offline headless Edge loads at 1440x1000; no concurrent analysis or builds; all charts visited and captured; RSS is summed owned-process working set, includes shared pages, 200 ms sampling; stop at 4 GiB sum or <1 GiB global available RAM",
    "cases": cases,
}
(out / "0.10-svg-containment-experiment.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
