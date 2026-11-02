"""Check installed recording review and relative-clock workflows outside checkout."""

import hashlib
import json
import subprocess
import sys
import sysconfig
from html.parser import HTMLParser
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit

import batterylog
from batterylog import AnalysisService, load_validation_config, validate_result_semantics
from batterylog.loaders.csv import CsvPathLoader


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.paths.extend(value for key, value in attrs if key == "href" and value)


def verify(cli: list[str], work: Path) -> dict:
    """Exercise one authored source through preparation, streaming and reports."""

    def command(*args, expected=0):
        completed = subprocess.run(
            [*cli, *map(str, args)], check=False, capture_output=True, text=True, timeout=60
        )
        assert completed.returncode == expected, completed.stdout + completed.stderr
        return json.loads(completed.stdout)

    raw = work / "epoch.csv"
    raw.write_text(
        "timestamp_s,cell_1_v,temp_c\n"
        + "".join(f"1700000000.{i},3.7,{25 + i / 8}\n" for i in range(6)),
        encoding="utf-8",
    )
    original = raw.read_bytes()
    prepared = work / "prepared"
    conversion = command(
        raw,
        "--normalize",
        "--relative-time",
        "--time-unit",
        "s",
        "--cell-voltage-unit",
        "V",
        "--temperature-unit",
        "degC",
        "--output-dir",
        prepared,
    )
    normalized = prepared / "normalized.csv"
    normalized_hash = hashlib.sha256(normalized.read_bytes()).hexdigest()
    assert conversion["normalization_schema_version"] == 2
    assert conversion["time_basis"]["source_origin"] == "1700000000.0"
    assert conversion["source"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert conversion["normalized_sha256"] == normalized_hash
    assert raw.read_bytes() == original
    assert json.loads((prepared / "conversion.json").read_text()) == conversion

    config_path = work / "temperature.yaml"

    def configure(limit):
        config_path.write_text(
            "schema_version: 7\nfailure_models:\n  max_gap_s: 1\n"
            f"  temperature_rise:\n    max_c_per_min: {limit}\n    min_interval_s: 0.1\n",
            encoding="utf-8",
        )
        return load_validation_config(config_path)

    configure(75)
    hashes = {}
    for limit, expected_status, code in [(75, "PASS", 0), (74, "FAIL", 1)]:
        config = configure(limit)
        service = AnalysisService(config)
        whole = service.analyze_path(normalized, report_max_points=14)
        for chunk_rows in (1, 2, 100):
            streamed = service.analyze_loader(
                CsvPathLoader(normalized, chunk_rows=chunk_rows), report_max_points=14
            )
            assert streamed == whole
        validate_result_semantics(whole.result)
        report = work / f"temperature-{limit}.html"
        json_out = work / f"temperature-{limit}.json"
        result = command(
            normalized,
            "--config",
            config_path,
            "--report",
            report,
            "--json-out",
            json_out,
            expected=code,
        )
        assert result == whole.result == json.loads(json_out.read_text())
        model = result["failure_models"]["evaluations"][0]
        assert model["status"] == result["validation_status"] == expected_status
        assert model["evaluated_samples"] == 5
        if expected_status == "FAIL":
            assert len(model["events"]) == 1
            event = model["events"][0]
            assert event["start_time_s"] == 0.1 and event["end_time_s"] == 0.5
            assert 0.1 <= event["peak_time_s"] <= 0.5
            assert 0 <= event["evidence"]["previous_time_s"] <= 0.4
        else:
            assert not model["events"]
        html = report.read_text(encoding="utf-8")
        config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
        assert normalized_hash in html and config_hash in html
        assert html.count('class="timeseries-chart"') == 3
        hashes[expected_status] = config_hash

    plan = work / "plan.json"
    record = {
        "id": "elapsed-run",
        "path": "normalized.csv",
        "expected_channels": ["cell_1_v", "temp_c"],
        "time": {
            "column": "timestamp_s",
            "unit": "s",
            "start_s": "0",
            "end_s": "0.5",
            "max_gap_s": "0.1",
            "boundary_tolerance_s": "0",
        },
    }
    outcomes = []
    for label, limit, end, coverage, engineering, code in [
        ("complete-pass", 75, "0.5", "COMPLETE", "PASS", 0),
        ("complete-fail", 74, "0.5", "COMPLETE", "FAIL", 1),
        ("incomplete-pass", 75, "0.6", "INCOMPLETE", "PASS", 1),
    ]:
        configure(limit)
        record["time"]["end_s"] = end
        plan.write_text(
            json.dumps({"recording_plan_schema_version": 1, "recordings": [record]}),
            encoding="utf-8",
        )
        target = work / label
        review = command(
            prepared,
            "--audit-recordings",
            plan,
            "--config",
            config_path,
            "--output-dir",
            target,
            expected=code,
        )
        assert review["audit"]["coverage_status"] == coverage
        assert review["engineering_status"] == engineering
        assert review["audit"]["sensor_acquisition_freshness"] == "NOT_EVALUATED"
        assert json.loads((target / "review.json").read_text()) == review
        item = review["recordings"][0]
        assert item["recording"]["source_sha256"] == normalized_hash
        assert item["engineering"]["source_sha256"] == normalized_hash
        engineering_result = json.loads((target / item["engineering"]["result_json"]).read_text())
        assert engineering_result["validation_status"] == engineering
        validate_result_semantics(engineering_result)
        html = (target / "review.html").read_text(encoding="utf-8")
        assert normalized_hash in html
        assert hashlib.sha256(plan.read_bytes()).hexdigest() in html
        assert hashlib.sha256(config_path.read_bytes()).hexdigest() in html
        links = _Links()
        links.feed(html)
        assert len(links.paths) == 3
        for href in links.paths:
            assert not urlsplit(href).scheme
            linked = (target / unquote(href)).resolve()
            assert linked.is_relative_to(target) and linked.is_file()
        outcomes.append({"coverage": coverage, "engineering": engineering, "exit_code": code})
    return {
        "relative_time": True,
        "stream_chunk_sizes": [1, 2, 100],
        "temperature_statuses": ["PASS", "FAIL"],
        "reviews": outcomes,
        "source_sha256": conversion["source"]["sha256"],
        "prepared_sha256": normalized_hash,
        "config_hashes": hashes,
    }


def main():
    expected_version = sys.argv[1]
    assert version("batterylog") == expected_version
    installed = Path(batterylog.__file__).resolve()
    assert installed.is_relative_to(Path(sys.prefix).resolve()), installed
    cli = Path(sysconfig.get_path("scripts")) / (
        "batterylog.exe" if sys.platform == "win32" else "batterylog"
    )
    with TemporaryDirectory() as directory:
        result = verify([str(cli)], Path(directory))
    print(
        json.dumps({"version": expected_version, "installed": str(installed), **result}, indent=2)
    )


if __name__ == "__main__":
    main()
