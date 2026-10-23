"""Precharge report geometry and provenance from independently authored captures."""

import copy
import hashlib
import json
import re
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import pytest

from batterylog_research import operator, precharge_file_review, precharge_html

FIXTURES = Path(__file__).resolve().parents[1] / "batterylog_research" / "fixtures"


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def build(tmp_path, rows=None, *, envelope=None, gap=0.2, max_examples=5):
    if rows is None:
        rows = [
            ("-0.1", 0, 0, 400, 0),
            ("0", 1, 8, 400, 0),
            ("0.1", 1, -50, 400, 100),
            ("0.2", 1, 4, 400, 200),
        ]
    raw = (
        ",".join(precharge_file_review.COLUMNS)
        + "\n"
        + "\n".join(",".join(map(str, row)) for row in rows)
        + "\n"
    ).encode()
    capture = tmp_path / "capture.csv"
    capture.write_bytes(raw)
    context = json.loads((FIXTURES / "precharge_aligned_example.context.json").read_text())
    context["capture_sha256"] = hashlib.sha256(raw).hexdigest()
    context["envelope"] = envelope or [[0, 7, 9, 0.9, 1.1], [0.2, 3, 5, 0.4, 0.6]]
    context["max_gap_s"] = gap
    context["max_examples"] = max_examples
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    report_path = tmp_path / "direct.json"
    report = precharge_file_review.review_paths(capture, context_path, report_path)
    return capture, context_path, report, raw, report_path


def circles(html, kind=None):
    return [
        attrs
        for tag, attrs in Document(html).tags
        if tag == "circle" and (kind is None or attrs.get("class") == kind)
    ]


def test_exact_raw_values_band_geometry_and_source_examples(tmp_path):
    _, _, report, raw, report_path = build(tmp_path)
    before = copy.deepcopy(report)
    html = precharge_html.render_precharge_html(report, raw)
    assert report == before
    assert report["review"]["outside_envelope_samples"] == 1
    assert (
        len(circles(html, "departure")) == 1
    )  # Current departs; voltage gap stays within its band.
    points = {p["id"]: p for p in circles(html) if "id" in p}
    # -50 A is plotted as magnitude50; .1s is halfway across the .2s window.
    assert float(points["sample-0-2-0"]["cx"]) == 403
    assert float(points["sample-0-2-0"]["cy"]) == 30
    # Relative gap=(400-100)/400=.75; declared gap axis ranges .4..1.1.
    assert float(points["sample-0-2-1"]["cy"]) == pytest.approx(121.5)
    assert 'href="#sample-0-2-0">4–4</a>' in html
    assert "<td>-50.0</td>" in html
    assert hashlib.sha256(report_path.read_bytes()).hexdigest() in html
    polygons = [a for tag, a in Document(html).tags if tag == "polygon"]
    assert len(polygons) == 2
    # Reference knot0 at x88, knot1 at x718; lower/upper order closes the band.
    assert [float(p.split(",")[0]) for p in polygons[0]["points"].split()] == [88, 718, 718, 88]
    for svg in re.findall(r"<svg\b.*?</svg>", html):
        ElementTree.fromstring(svg)


@pytest.mark.parametrize(
    "failure", ["gap", "duplicate", "missing", "unknown", "unobserved", "short"]
)
def test_incomplete_observations_never_become_covered_or_restore_qualification(tmp_path, failure):
    rows = {
        "gap": [
            ("-0.1", 0, 0, 400, 0),
            ("0", 1, 8, 400, 0),
            ("0.4", 1, 7, 400, 40),
            ("0.5", 1, 6, 400, 80),
        ],
        "duplicate": [
            ("-0.1", 0, 0, 400, 0),
            ("0", 1, 8, 400, 0),
            ("0", 1, 7, 400, 40),
            ("0.1", 1, 6, 400, 80),
        ],
        "missing": [
            ("-0.1", 0, 0, 400, 0),
            ("0", 1, 8, 400, 0),
            ("0.1", 1, "", 400, 40),
            ("0.2", 1, 6, 400, 80),
        ],
        "unknown": [
            ("-0.1", 0, 0, 400, 0),
            ("0", 1, 8, 400, 0),
            ("0.1", "", 7, 400, 40),
            ("0.2", 1, 6, 400, 80),
        ],
        "unobserved": [("0", 1, 8, 400, 0), ("0.1", 1, 7, 400, 40)],
        "short": [("-0.1", 0, 0, 400, 0), ("0", 1, 8, 400, 0), ("0.1", 1, 7, 400, 40)],
    }[failure]
    _, _, report, raw, _ = build(tmp_path, rows, envelope=[[0, 0, 10, 0, 1], [1, 0, 10, 0, 1]])
    html = precharge_html.render_precharge_html(report, raw)
    assert report["review"]["covered_reference_intervals"] == 0
    assert "Incomplete coverage" in html
    assert any(a.get("class") == "uncovered" for _, a in Document(html).tags)
    if failure in ("gap", "duplicate", "missing"):
        assert len(circles(html, "qualified")) == 2  # One qualified row in two panels.
        assert circles(html, "raw")
    if failure == "gap":
        assert any(a.get("class") == "gap" for _, a in Document(html).tags)
    if failure == "duplicate":
        assert any(a.get("class") == "duplicate" for _, a in Document(html).tags)
    if failure == "missing":
        assert any(a.get("class") == "missing" for _, a in Document(html).tags)
    if failure == "unobserved":
        assert not circles(html, "qualified")
    assert "PASS" not in html


def test_horizon_bracketing_is_not_displayed_as_an_interpolated_measurement(tmp_path):
    rows = [
        ("-.1", 0, 0, 400, 0),
        ("0", 1, 8, 400, 0),
        (".1", 1, 7, 400, 40),
        (".25", 1, 6, 400, 80),
    ]
    _, _, report, raw, _ = build(tmp_path, rows, envelope=[[0, 0, 10, 0, 1], [0.2, 0, 10, 0, 1]])
    html = precharge_html.render_precharge_html(report, raw)
    assert report["review"]["covered_reference_intervals"] == 1
    assert len(circles(html, "qualified")) == 4
    assert not any(a.get("class") == "uncovered" for _, a in Document(html).tags)
    assert not any("sample-0-3" in p.get("id", "") for p in circles(html))
    assert "measurement values are not interpolated" in html


def test_decimal_elapsed_geometry_survives_a_large_epoch(tmp_path):
    epoch = Decimal(1000000000000000000000000)
    offsets = [Decimal("-.1"), Decimal(0), Decimal(".1"), Decimal(".2")]
    rows = [
        (str(epoch + d), p, i, 400, v)
        for d, p, i, v in zip(offsets, [0, 1, 1, 1], [0, 8, -50, 4], [0, 0, 100, 200], strict=True)
    ]
    _, _, report, raw, _ = build(tmp_path, rows)
    html = precharge_html.render_precharge_html(report, raw)
    point = next(p for p in circles(html) if p.get("id") == "sample-0-2-0")
    assert float(point["cx"]) == 403
    assert "1000000000000000000000000.2" in html


def test_display_sampling_preserves_an_unlisted_peak_and_all_report_counts(tmp_path):
    rows = [("-0.0001", 0, 0, 400, 0)]
    rows += [(str(Decimal(i) / 10000), 1, -100 if i == 1234 else 5, 400, 200) for i in range(5001)]
    _, _, report, raw, _ = build(
        tmp_path, rows, envelope=[[0, 0, 10, 0, 1], [0.5, 0, 10, 0, 1]], gap=0.001, max_examples=0
    )
    html = precharge_html.render_precharge_html(report, raw)
    assert report["review"]["outside_envelope_samples"] == 1
    assert "observed departures: 1" in html
    assert any(p.get("id") == "sample-0-1235-0" for p in circles(html))
    assert not circles(html, "departure")
    assert len(circles(html)) < 1300
    assert len(html) < 1_000_000


@pytest.mark.parametrize("overflow", ["spans", "reference"])
def test_chart_limits_leave_every_span_and_counts_visible(tmp_path, overflow):
    rows = [("-0.1", 0, 0, 400, 0)]
    for i in range(13):
        rows.extend([(str(i), 1, 8, 400, 0), (str(Decimal(i) + Decimal(".1")), 0, 0, 400, 0)])
    envelope = [[0, 0, 10, 0, 1], [0.2, 0, 10, 0, 1]]
    if overflow == "reference":
        envelope = [[i / 20480, 0, 10, 0, 1] for i in range(4097)]
    _, _, report, raw, _ = build(tmp_path, rows, envelope=envelope, gap=2)
    html = precharge_html.render_precharge_html(report, raw)
    assert "Span 13:" in html
    assert html.count("<svg ") == (24 if overflow == "spans" else 0)
    assert "Charts omitted by display limits" in html
    assert report["review"]["known_active_samples"] == 13


def test_zero_active_capture_does_not_imply_a_successful_comparison(tmp_path):
    _, _, report, raw, _ = build(tmp_path, [("0", 0, 0, 400, 0)])
    html = precharge_html.render_precharge_html(report, raw)
    assert "No active spans recorded" in html
    assert not circles(html)


def test_untrusted_context_is_escaped_and_report_needs_no_network_or_script(tmp_path):
    _, _, report, raw, _ = build(tmp_path)
    report["context"]["declaration"]["measurement_context"]["procedure"] = (
        '</style><script src="https://example.invalid/a"></script><img src=x onerror=alert(1)>'
    )
    html = precharge_html.render_precharge_html(report, raw)
    assert "&lt;script" in html
    tags = Document(html).tags
    assert not any(tag in ("script", "img", "iframe", "link") for tag, _ in tags)
    assert not any(k.lower().startswith("on") for _, attrs in tags for k in attrs)
    assert all(not a.get("href", "").startswith(("http", "javascript:")) for _, a in tags)


@pytest.mark.parametrize("change", ["bytes", "row-count"])
def test_html_rejects_a_different_capture_or_row_count(tmp_path, change):
    _, _, report, raw, _ = build(tmp_path)
    if change == "bytes":
        raw += b"\n"
    else:
        report["capture"]["data_records"] += 1
    with pytest.raises(ValueError, match="match"):
        precharge_html.render_precharge_html(report, raw)


def test_operator_adds_html_without_changing_the_review_and_hashes_it(tmp_path):
    capture, context, report, _, direct = build(tmp_path)
    output = tmp_path / "completed"
    manifest = operator.review_precharge(capture, context, output)
    assert (output / "review.json").read_bytes() == direct.read_bytes()
    assert (
        hashlib.sha256((output / "report.html").read_bytes()).hexdigest()
        == manifest["outputs_sha256"]["report.html"]
    )
    assert 'href="report.html"' in (output / "index.html").read_text()
    assert json.loads((output / "review.json").read_bytes()) == report
    assert "precharge_html.py" in manifest["implementation_sha256"]


@pytest.mark.parametrize("fault", ["render", "mutation", "interrupt"])
def test_html_failure_or_changed_source_never_publishes_a_partial_review(
    tmp_path, monkeypatch, fault
):
    capture, context, _, _, _ = build(tmp_path)
    original = operator.precharge_html.render_precharge_html

    def fail(report, raw):
        if fault == "render":
            raise OSError("injected renderer failure")
        if fault == "interrupt":
            raise KeyboardInterrupt
        html = original(report, raw)
        with context.open("a") as handle:
            handle.write("\n")
        return html

    monkeypatch.setattr(operator.precharge_html, "render_precharge_html", fail)
    with pytest.raises(KeyboardInterrupt if fault == "interrupt" else (OSError, ValueError)):
        operator.review_precharge(capture, context, tmp_path / "completed")
    assert not (tmp_path / "completed").exists()
    assert not list(tmp_path.glob(".research-operator-*"))


def test_extreme_unqualified_values_keep_finite_display_geometry(tmp_path):
    rows = [
        ("-.1", 0, 0, 400, 0),
        ("0", 1, 8, 400, 0),
        (".1", 1, "1e308", -1, "1e308"),
        (".2", 1, "-1e308", "1e-308", "1e308"),
    ]
    _, _, report, raw, _ = build(tmp_path, rows)
    html = precharge_html.render_precharge_html(report, raw)
    assert "Incomplete coverage" in html
    for _, attrs in Document(html).tags:
        for key in ("cx", "cy", "points", "d", "width", "height"):
            if key in attrs:
                assert "nan" not in attrs[key].lower()
                assert "inf" not in attrs[key].lower()
