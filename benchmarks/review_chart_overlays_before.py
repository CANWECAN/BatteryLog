import hashlib
import json
import runpy
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path.cwd()
out = root / "dist/chart-review"
out.mkdir(parents=True, exist_ok=True)
bench = runpy.run_path(str(root / "benchmarks/benchmark_mf4_analysis.py"))
source = root.parent / "BatteryLog-report-review/dist/report-review/pressure-100000.mf4"
result = bench["_run_batterylog_workload"](
    source, mode="report", report_path=out / "pressure-before.html"
)
assert len(result["violations"]) == 100000
(out / "result-before.json").write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True)
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith("file:") else route.abort()
            ),
        )
        page.goto((out / "pressure-before.html").as_uri(), timeout=60000)
        assert page.locator("#plot-overlays").count() == 0
        page.locator(".plot-card").first.screenshot(path=str(out / "pressure-before.png"))
        payload = {
            "events": 100000,
            "overlay_control_present": False,
            "windows": page.locator(".violation-instant, .violation-window").count(),
            "peaks": page.locator(".violation-peak").count(),
            "dom_nodes": page.locator("*").count(),
            "source_checkpoint": "5dde0781adbf941aac63d605dc88e0f7ab55d193",
            "mf4_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "report_bytes": (out / "pressure-before.html").stat().st_size,
        }
    finally:
        browser.close()
(root / "docs/benchmarks/0.10-chart-overlay-before.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(payload), flush=True)
