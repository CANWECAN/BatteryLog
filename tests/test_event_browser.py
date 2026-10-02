import copy
import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from batterylog import ValidationLimits
from batterylog.analysis.core import analyze_battery_bytes
from batterylog.reporting import render_html_report, render_json_result


class EventDocument(HTMLParser):
    def __init__(self, html, *, prefix="event", table_class="event-table"):
        super().__init__()
        self.prefix = prefix
        self.table_class = table_class
        self.payload = ""
        self.scripts = 0
        self.in_payload = False
        self.in_events = False
        self.rows = []
        self.current = None
        self.cell = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.scripts += 1
            self.in_payload = attrs.get("id") == self.prefix + "-data"
        if tag == "div" and attrs.get("class") == self.table_class:
            self.in_events = True
        if self.in_events and tag == "tr":
            self.current = []
        if self.current is not None and tag == "td":
            self.cell = ""

    def handle_data(self, data):
        if self.in_payload:
            self.payload += data
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_payload = False
        if tag == "td" and self.cell is not None:
            self.current.append(self.cell)
            self.cell = None
        if tag == "tr" and self.current is not None:
            if self.current:
                self.rows.append(self.current)
            self.current = None
        if tag == "div" and self.in_events:
            self.in_events = False


def _result(count):
    path = Path(__file__).parent / "golden" / "semantic_multi_rule_fail.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    template = result["violations"][0]
    result["violations"] = []
    for index in range(count):
        event = copy.deepcopy(template)
        event.update(start_time_s=index, end_time_s=index, peak_time_s=index)
        result["violations"].append(event)
    return result


@pytest.mark.parametrize("count", [0, 1, 100, 101, 201])
def test_event_pages_retain_every_record_in_order_without_mutating_results(count):
    result = _result(count)
    before = render_json_result(result)
    html = render_html_report(result)
    doc = EventDocument(html)
    assert len(doc.rows) == min(count, 100)
    assert render_json_result(result) == before
    if count <= 100:
        assert doc.scripts == 0
        assert not doc.payload
    else:
        payload = json.loads(doc.payload)
        assert len(payload) == count
        assert [event["start"] for event in payload] == list(range(count))
        assert [event["end"] for event in payload] == list(range(count))
        assert [event["cells"] for event in payload[:100]] == doc.rows
        assert payload[-1]["cells"][1:4] == [str(count - 1)] * 3
        assert all(event["signals"] == result["violations"][0]["signals"] for event in payload)
        assert "Printing includes the displayed page only." in html
        assert "JavaScript is disabled." in html


def test_embedded_strings_cannot_end_the_inert_json_element():
    result = _result(101)
    signal = '</script><p>sensor & "label"</p>'
    result["violations"][-1]["signals"] = [signal]
    html = render_html_report(result)
    doc = EventDocument(html)
    assert doc.scripts == 2
    payload = json.loads(doc.payload)
    assert payload[-1]["signals"] == [signal]
    assert payload[-1]["cells"][9] == signal
    assert signal not in html


def test_pack_chain_presentation_is_retained_in_embedded_events():
    result = analyze_battery_bytes(
        b"timestamp_s,cell_1_v,cell_2_v,temp_c,pack_voltage_v\n0,3.5,3.5,25,8\n",
        limits=ValidationLimits(pack_voltage_cell_sum_max_delta_v=0.1),
    )
    event = result["violations"][0]
    result["violations"] = [copy.deepcopy(event) for _ in range(101)]
    doc = EventDocument(render_html_report(result))
    payload = json.loads(doc.payload)
    assert payload[-1]["cells"] == doc.rows[0]
    assert payload[-1]["cells"][10] == "pack 8 V; cell sum 7 V; signed error 1 V"


@pytest.mark.parametrize("count", [0, 1, 100, 101, 201])
def test_quality_pages_retain_source_row_evidence_and_do_not_mutate_results(count):
    result = _result(101)
    result["data_quality"]["events"] = [
        {
            "code": "MISSING_REQUIRED_VALUE",
            "start_row": index * 3 + 1,
            "end_row": index * 3 + 2,
            "affected_values": 2,
            "signals": ["cell_2_v", "temp_c"],
        }
        for index in range(count)
    ]
    before = render_json_result(result)
    html = render_html_report(result)
    doc = EventDocument(html, prefix="quality", table_class="quality-table")
    assert len(doc.rows) == min(count, 100)
    assert render_json_result(result) == before
    assert doc.rows == [
        ["MISSING_REQUIRED_VALUE", str(index * 3 + 1), str(index * 3 + 2), "2", "cell_2_v, temp_c"]
        for index in range(min(count, 100))
    ]
    if count <= 100:
        assert not doc.payload
    else:
        payload = json.loads(doc.payload)
        assert len(payload) == count
        assert [event["start"] for event in payload] == [i * 3 + 1 for i in range(count)]
        assert [event["end"] for event in payload] == [i * 3 + 2 for i in range(count)]
        assert [event["cells"] for event in payload[:100]] == doc.rows
        assert all(event["signals"] == ["cell_2_v", "temp_c"] for event in payload)
        assert "one-based source data row numbers" in html
        assert doc.scripts == 4
        violation = EventDocument(html)
        assert len(json.loads(violation.payload)) == 101
        assert len(violation.rows) == 100


def test_quality_embedded_strings_and_initial_rows_remain_literal_text():
    result = _result(0)
    signal = '</script><p>sensor & "label"</p>'
    result["data_quality"]["events"] = [
        {
            "code": "NON_NUMERIC_REQUIRED_VALUE",
            "start_row": i + 1,
            "end_row": i + 1,
            "affected_values": 1,
            "signals": [signal],
        }
        for i in range(101)
    ]
    html = render_html_report(result)
    doc = EventDocument(html, prefix="quality", table_class="quality-table")
    assert doc.scripts == 2
    assert doc.rows[0][-1] == signal
    payload = json.loads(doc.payload)
    assert all(event["signals"] == [signal] for event in payload)
    assert all(event["cells"][-1] == signal for event in payload)
    assert signal not in html


def test_quality_presentation_uses_actual_one_based_csv_data_rows():
    from batterylog.config import DataQualityConfig

    data = (
        "timestamp_s,cell_1_v,temp_c\n"
        + "".join(f"{i},{'' if i % 2 == 0 else '3.7'},25\n" for i in range(202))
    ).encode()
    result = analyze_battery_bytes(
        data,
        limits=ValidationLimits(cell_max_v=4.2),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )
    assert result["validation_status"] == "FAIL"
    assert (result["rows_input"], result["rows_analyzed"], result["rows_excluded"]) == (
        202,
        101,
        101,
    )
    assert not result["violations"]
    events = result["data_quality"]["events"]
    assert [event["start_row"] for event in events] == list(range(1, 202, 2))
    assert [event["end_row"] for event in events] == list(range(1, 202, 2))
    html = render_html_report(result)
    doc = EventDocument(html, prefix="quality", table_class="quality-table")
    assert doc.rows[0] == ["MISSING_REQUIRED_VALUE", "1", "1", "1", "cell_1_v"]
    assert doc.rows[-1][1:3] == ["199", "199"]
    assert json.loads(doc.payload)[-1]["cells"][1:3] == ["201", "201"]
    assert "one-based source data row numbers" in html
