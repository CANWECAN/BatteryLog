"""Focused offline browser checks for two independent report tables."""

import json
import runpy
from pathlib import Path

from playwright.sync_api import sync_playwright

from batterylog.reporting import render_html_report


def check_keyboard_paging(page, prefix, total):
    """Keep focus usable when a keyboard-activated boundary button becomes disabled."""
    region = page.locator("#" + prefix + "-table")
    pages = page.locator("#" + prefix + "-pages")
    actions = ["last", "first"]
    actions += ["next"] * ((total - 1) // 100)
    actions += ["previous"] * ((total - 1) // 100)
    observations = []
    for action in actions:
        button = pages.locator("[data-page=" + action + "]")
        assert button.is_enabled()
        button.focus()
        page.keyboard.press("Enter")
        target = region if button.is_disabled() else button
        assert target.evaluate("(e)=>document.activeElement===e")
        if button.is_disabled():
            page.keyboard.press("Shift+Tab")
            assert pages.evaluate(
                "(e)=>e.contains(document.activeElement) && !document.activeElement.disabled"
            )
            region.focus()
        observations.append(
            {
                "action": action,
                "count": page.locator("#" + prefix + "-count").inner_text(),
            }
        )
    assert page.locator("#" + prefix + "-table tbody tr").count() == 100
    return observations


root = Path.cwd()
out = root / "dist" / "quality-review"
out.mkdir(parents=True, exist_ok=True)
fixture = runpy.run_path(str(root / "tests" / "test_event_browser.py"))["_result"]
cases = []
with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True)
    try:
        for count in [0, 100, 101, 201]:
            result = fixture(201)
            signal = '</script><p>sensor & "label"</p>'
            result["data_quality"]["events"] = [
                {
                    "code": [
                        "MISSING_REQUIRED_VALUE",
                        "NON_NUMERIC_REQUIRED_VALUE",
                        "NON_FINITE_REQUIRED_VALUE",
                    ][i % 3],
                    "start_row": i * 3 + 1,
                    "end_row": i * 3 + 3,
                    "affected_values": 3,
                    "signals": [signal if i % 2 else "temp_c"],
                }
                for i in range(count)
            ]
            report = out / f"focused-{count}.html"
            report.write_text(render_html_report(result), encoding="utf-8")
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
            page.goto(report.as_uri(), wait_until="load")
            quality = page.locator("#quality-table tbody tr")
            violations = page.locator("#event-table tbody tr")
            assert quality.count() == min(count, 100)
            assert violations.count() == 100
            keyboard_checks = {"event": check_keyboard_paging(page, "event", 201)}
            if count > 100:
                keyboard_checks["quality"] = check_keyboard_paging(page, "quality", count)
                payload = page.locator("#quality-data").evaluate("(e)=>JSON.parse(e.textContent)")
                observed = []
                while True:
                    observed.extend(
                        quality.evaluate_all(
                            "(rows)=>rows.map(r=>[...r.cells].map(c=>c.textContent))"
                        )
                    )
                    next_page = page.locator("#quality-pages [data-page=next]")
                    if next_page.is_disabled():
                        break
                    next_page.click()
                assert observed == [event["cells"] for event in payload]
                assert len(observed) == count
                page.locator("#quality-summary .rule-link").nth(1).click()
                selected = page.locator("#quality-rule").input_value()
                assert all(
                    code == selected
                    for code in quality.locator("td:first-child").all_text_contents()
                )
                assert "1–100 of 201 matching events" in page.locator("#event-count").inner_text()
                snapshot = page.locator("#quality-count").inner_text()
                page.locator("#violation-summary .rule-link").first.click()
                assert page.locator("#quality-count").inner_text() == snapshot
                page.locator("#quality-filters button[type=reset]").click()
                page.locator("#quality-from").fill("0")
                page.locator("#quality-to").fill("0")
                page.locator("#quality-filters button[type=submit]").click()
                assert quality.count() == 0
                assert (
                    "No matching data-quality events" in page.locator("#quality-count").inner_text()
                )
                page.locator("#quality-from").fill("1")
                page.locator("#quality-to").fill("1")
                page.locator("#quality-filters button[type=submit]").click()
                assert quality.count() == 1
                assert quality.first.locator("td").all_text_contents() == [
                    "MISSING_REQUIRED_VALUE",
                    "1",
                    "3",
                    "3",
                    "temp_c",
                ]
                page.locator("#quality-filters button[type=reset]").click()
                page.locator("#quality-from").fill("5")
                page.locator("#quality-to").fill("5")
                page.locator("#quality-filters button[type=submit]").click()
                assert (
                    quality.count() == 1 and quality.first.locator("td").nth(1).inner_text() == "4"
                )
                page.locator("#quality-filters button[type=reset]").click()
                page.locator("#quality-signal").select_option(signal)
                page.locator("#quality-filters button[type=submit]").click()
                assert quality.first.locator("td").last.inner_text() == signal
                assert page.locator("#quality-table p").count() == 0
                page.locator("#quality-filters button[type=reset]").click()
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.locator("#quality-table").evaluate("(e)=>e.scrollWidth>e.clientWidth")
                page.emulate_media(media="print")
                for table in ["quality", "event"]:
                    assert (
                        page.locator("#" + table + "-table").evaluate(
                            "(e)=>getComputedStyle(e).maxHeight"
                        )
                        == "none"
                    )
                    assert not page.locator("#" + table + "-filters").is_visible()
                disabled = browser.new_context(java_script_enabled=False)
                nojs = disabled.new_page()
                nojs.goto(report.as_uri())
                assert nojs.locator("#quality-table tbody tr").count() == 100
                assert nojs.locator("#data-quality noscript").is_visible()
                assert not nojs.locator("#quality-filters").is_visible()
                disabled.close()
            assert not errors
            cases.append(
                {
                    "quality_events": count,
                    "violation_events": 201,
                    "complete_page_order": count > 100,
                    "initial_row_count": True,
                    "isolated_filters": count > 100,
                    "zero_bound_first_row_and_overlap": count > 100,
                    "literal_text": count > 100,
                    "narrow_scroll_and_print": count > 100,
                    "nojs_notice": count > 100,
                    "keyboard_boundary_focus": keyboard_checks,
                    "page_errors": errors,
                }
            )
            context.close()
    finally:
        browser.close()
(out / "0.10-quality-focused-checks.json").write_text(
    json.dumps(
        {
            "fixture": "presentation-only custom rows, not an analysis workload",
            "cases": cases,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
print(json.dumps(cases), flush=True)
