"""Regenerate the README screenshot (requires Playwright and Chromium)."""

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

from batterylog.analysis.streaming import analyze_battery_file_with_report_series
from batterylog.config import load_validation_config_bytes
from batterylog.reporting import (
    build_report_metadata,
    capture_file_snapshot,
    write_html_report,
)

ROOT = Path(__file__).resolve().parents[1]
source = capture_file_snapshot(ROOT / "examples/vendor_battery_log.csv")
config = capture_file_snapshot(ROOT / "examples/vendor_mapping.example.yaml")
settings = load_validation_config_bytes(config.data)
result, series = analyze_battery_file_with_report_series(
    BytesIO(source.data),
    source_name=source.evidence.name,
    limits=settings.limits,
    event_detection=settings.event_detection,
    data_quality=settings.data_quality,
    signal_mapping=settings.signals,
)
metadata = build_report_metadata(
    source.evidence, config.evidence, generated_at=datetime(2026, 9, 20, tzinfo=UTC)
)
with TemporaryDirectory() as directory, sync_playwright() as playwright:
    report = Path(directory) / "report.html"
    write_html_report(result, report, metadata=metadata, series=series)
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 2600}, device_scale_factor=1)
    page.goto(report.as_uri())
    page.screenshot(path=str(ROOT / "docs/assets/report-preview.png"))
    browser.close()
