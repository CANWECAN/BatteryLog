import copy
import json
from html import escape
from html.parser import HTMLParser

import pytest

from batterylog import DataQualityConfig, ValidationConfig, ValidationLimits
from batterylog.failure_config import FailureModelConfig, SustainedImbalanceConfig
from batterylog.interpretation_review import review_measurement
from batterylog.reporting.interpretation import render_interpretation_report


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.links = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.links.extend(value for key, value in attrs if key == "href")
        assert not any(key.startswith("on") for key, _ in attrs)

    def handle_data(self, data):
        self.text.append(data)


def create(tmp_path, *, context=True, config=None, bad_temperature=False):
    source = tmp_path / "capture & 'quoted'.csv"
    source.write_text(
        "timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.8,3.6,25\n1,3.8,3.6,"
        + ("bad" if bad_temperature else "25")
        + "\n"
    )
    declaration = tmp_path / "context.json"
    declaration.write_text(
        json.dumps(
            {
                "measurement_context_schema_version": 1,
                "chemistry": '<script>alert("chemistry")</script>',
                "soc": {"value_percent": 0, "source": '<img src=x onerror="attack">'},
                "operating_state": "rest",
                "topology": {"kind": "parallel", "branch_ids": ["left<&", "right"]},
                "channels": [
                    {
                        "source": '<a href="javascript:attack">',
                        "role": "cell_voltage",
                        "branch_id": "left<&",
                        "cell_id": "physical cell",
                        "unit": "mV",
                        "time_basis": "clock",
                        "acquisition": "previous_sample_hold",
                    }
                ],
            }
        )
    )
    bundle = review_measurement(
        source, tmp_path / "review", config=config, context_path=declaration if context else None
    )
    return bundle, Elements()


@pytest.mark.parametrize("limit,status", [(None, "NOT_EVALUATED"), (0.5, "PASS"), (0.05, "FAIL")])
@pytest.mark.parametrize("context", [False, True])
def test_html_and_json_agree_on_status_every_physical_reason_and_real_artifact_links(
    tmp_path, limit, status, context
):
    bundle, elements = create(
        tmp_path,
        context=context,
        config=ValidationConfig(limits=ValidationLimits(imbalance_max_v=limit)),
    )
    payload = bundle.to_dict()
    html = (bundle.output_directory / "interpretation.html").read_text()
    assert html == render_interpretation_report(payload)
    assert f"Engineering: <strong>{status}</strong>" in html
    assert "Physical interpretation: <strong>NOT_EVALUATED</strong>" in html
    assert "No SOC difference, faulty branch or sensor/cell cause is estimated" in html
    elements.feed(html)
    assert "script" not in elements.tags
    assert "img" not in elements.tags
    assert "iframe" not in elements.tags
    text = "".join(elements.text)
    for claim in payload["claims"]:
        assert all(reason in text for reason in claim["reason_codes"])
        for issue in claim.get("issues", []):
            assert issue["detail"] in text
    for key in ("source", "result", "context", "effective_config"):
        artifact = payload["binding"][key]
        if artifact is not None:
            assert artifact["sha256"] in text
    assert all((bundle.output_directory / link).is_file() for link in elements.links)
    assert all(
        link in {"result.json", "interpretation.json", "context.json", "effective-config.json"}
        for link in elements.links
    )
    assert ("context.json" in elements.links) is context
    assert escape(payload["binding"]["source"]["name"]) in html
    if context:
        assert escape(payload["claims"][0]["declared_chemistry"]) in html
        assert payload["claims"][0]["declared_soc"]["value_percent"] == 0
        assert "<td>SOC (%)</td><td>0</td>" in html
        assert "REST_EQUILIBRATION_NOT_VERIFIED" in text
        assert "PREVIOUS_SAMPLE_HOLD_DECLARED" in text


def test_temporal_model_failure_is_displayed_alongside_zero_ordinary_threshold_events(tmp_path):
    config = ValidationConfig(
        failure_models=FailureModelConfig(2, sustained_imbalance=SustainedImbalanceConfig(0.05, 1))
    )
    bundle, elements = create(tmp_path, config=config)
    html = (bundle.output_directory / "interpretation.html").read_text()
    elements.feed(html)
    assert bundle.engineering_status == "FAIL"
    assert bundle.to_dict()["observations"]["violations"] == []
    model = bundle.to_dict()["observations"]["failure_models"]["evaluations"][0]
    assert model["code"] in "".join(elements.text)
    assert "Configured temporal/model checks" in html
    assert "Engineering: <strong>FAIL</strong>" in html


def test_data_quality_failure_is_visible_and_never_becomes_a_sensor_diagnosis(tmp_path):
    bundle, elements = create(
        tmp_path,
        config=ValidationConfig(data_quality=DataQualityConfig(mode="exclude_invalid_rows")),
        bad_temperature=True,
    )
    html = (bundle.output_directory / "interpretation.html").read_text()
    elements.feed(html)
    assert bundle.engineering_status == "FAIL"
    assert bundle.to_dict()["observations"]["data_quality_events"]
    assert "Data-quality events" in html
    assert "FAULT_ISOLATION_MODEL_NOT_AVAILABLE" in "".join(elements.text)


def test_large_event_preview_is_bounded_and_discloses_the_complete_event_count(tmp_path):
    bundle, _ = create(
        tmp_path, config=ValidationConfig(limits=ValidationLimits(imbalance_max_v=0.05))
    )
    payload = bundle.to_dict()
    event = payload["observations"]["violations"][0]
    payload["observations"]["violations"] = [copy.deepcopy(event) for _ in range(51)]
    before = copy.deepcopy(payload)
    html = render_interpretation_report(payload)
    assert "Showing up to 50 of 51 threshold events" in html
    assert html.count(f"<td>{event['code']}</td>") == 50
    assert payload == before


@pytest.mark.parametrize("failure", ["render", "write", "tamper", "source"])
def test_html_failure_or_late_input_change_publishes_no_bundle(tmp_path, monkeypatch, failure):
    import batterylog.interpretation_review as module

    original = module.render_interpretation_report
    original_write = module.Path.write_text

    def render(review):
        if failure == "render":
            raise OSError("HTML render stopped")
        if failure == "source":
            (tmp_path / "capture & 'quoted'.csv").write_text("source changed")
        return original(review)

    def write(path, data, *args, **kwargs):
        if path.name == "interpretation.html":
            if failure == "write":
                raise OSError("HTML write stopped")
            if failure == "tamper":
                data += "changed"
        return original_write(path, data, *args, **kwargs)

    monkeypatch.setattr(module, "render_interpretation_report", render)
    monkeypatch.setattr(module.Path, "write_text", write)
    with pytest.raises((OSError, ValueError)):
        create(tmp_path)
    assert not (tmp_path / "review").exists()
    assert not list(tmp_path.glob(".batterylog-interpret-*"))
