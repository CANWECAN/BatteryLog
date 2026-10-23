"""End-to-end operator results, source binding and failed-publication behavior."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from batterylog import AnalysisService, load_validation_config
from batterylog_research import operator, precharge_file_review

pytest.importorskip("cantools")

DBC = """VERSION ""
NS_ :
BS_:
BU_: Test
BO_ 256 Brick: 4 Test
 SG_ V0 : 0|16@1+ (0.001,0) [0|65.535] "V" Test
 SG_ V1 : 16|16@1+ (0.001,0) [0|65.535] "V" Test
BO_ 512 Context: 1 Test
 SG_ T : 0|8@1+ (1,-40) [-40|215] "C" Test
"""
FIXTURES = Path(__file__).resolve().parents[1] / "batterylog_research" / "fixtures"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def inputs(tmp_path):
    dbc = tmp_path / "authored.dbc"
    dbc.write_text(DBC, encoding="utf-8")
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "bus": "can0",
                "dbc_sha256": digest(dbc),
                "anchor": {
                    "frame_id": 256,
                    "extended": False,
                    "multiplexer_signal": None,
                    "multiplexer_value": None,
                },
                "signals": [
                    {
                        "column": column,
                        "frame_id": frame_id,
                        "extended": False,
                        "signal": signal,
                        "max_age_s": age,
                    }
                    for column, frame_id, signal, age in (
                        ("cell_1_v", 256, "V0", 0),
                        ("cell_2_v", 256, "V1", 0),
                        ("temp_1_c", 512, "T", 0.1),
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    log = tmp_path / "authored.log"
    # 3500 / 3550 mV and 20 C, independent raw-byte expectations.
    log.write_text(
        "(0) can0 200#3C\n(0) can0 100#AC0DDE0D\n(0.1) can0 100#AC0DDE0D\n",
        encoding="utf-8",
    )
    config = tmp_path / "limits.yaml"
    config.write_text(
        "schema_version: 5\nlimits:\n  temperature:\n    max_c: 55\n", encoding="utf-8"
    )
    return {"log": log, "dbc": dbc, "profile": profile, "config": config}


def assert_manifest(output, manifest):
    assert manifest == read(output / "manifest.json")
    assert set(manifest["outputs_sha256"]) == {
        p.relative_to(output).as_posix()
        for p in output.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    for name, expected in manifest["outputs_sha256"].items():
        assert digest(output / name) == expected
    assert 'href="manifest.json"' in (output / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "maximum,status,code", [(55, "PASS", 0), (10, "FAIL", 1), (None, "NOT_EVALUATED", 3)]
)
def test_can_matches_direct_core_with_exact_sources_and_age(
    inputs, tmp_path, maximum, status, code
):
    inputs["config"].write_text(
        f"schema_version: 5\nlimits:\n  temperature:\n    max_c: {maximum if maximum is not None else 'null'}\n",
        encoding="utf-8",
    )
    output = tmp_path / "review"
    manifest = operator.review_can(**inputs, output_dir=output)
    result = read(output / "result.json")
    direct = (
        AnalysisService(load_validation_config(inputs["config"]))
        .analyze_path(output / "prepared" / "canonical.csv")
        .result
    )
    assert result == direct
    assert result["validation_status"] == status
    assert result["max_temperature_c"] == 20
    assert result["min_cell_voltage_v"] == 3.5
    assert result["max_cell_voltage_v"] == pytest.approx(3.55)
    assert manifest["exit_code"] == code
    assert manifest["effective_config"]["limits"]["temperature_max_c"] == maximum
    for role, path in inputs.items():
        assert manifest["sources"][role]["sha256"] == digest(path)
    alignment = [
        json.loads(line)
        for line in (output / "prepared" / "alignment.jsonl").read_text().splitlines()
    ]
    assert alignment[1]["measurements"]["temp_1_c"]["age_s"] == 0.1
    assert alignment[1]["measurements"]["temp_1_c"]["source_line"] == 1
    html = (output / "report.html").read_text(encoding="utf-8")
    assert digest(output / "prepared" / "canonical.csv") in html
    assert digest(inputs["config"]) in html
    assert "failure_models" not in result
    assert_manifest(output, manifest)


def test_missing_age_stays_missing_and_explicit_exclusion_is_visible(inputs, tmp_path):
    with inputs["log"].open("a", encoding="utf-8") as handle:
        handle.write("(0.100000001) can0 100#AC0DDE0D\n")
    inputs["config"].write_text(
        inputs["config"].read_text() + "data_quality:\n  mode: exclude_invalid_rows\n",
        encoding="utf-8",
    )
    output = tmp_path / "review"
    operator.review_can(**inputs, output_dir=output)
    result = read(output / "result.json")
    preparation = read(output / "prepared" / "preparation.json")
    assert result["rows_input"] == 3
    assert result["rows_analyzed"] == 2
    assert result["rows_excluded"] == 1
    assert result["data_quality"]["events"][0]["code"] == "MISSING_REQUIRED_VALUE"
    assert preparation["missing_or_expired_values_by_column"] == {"temp_1_c": 1}
    assert (output / "prepared" / "canonical.csv").read_text().splitlines()[-1].endswith(",")
    assert "not simultaneous" in (output / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", ["temporal", "remapping", "stack"])
def test_can_rejects_unqualified_derived_models(inputs, tmp_path, kind):
    extra = {
        "temporal": (
            "schema_version: 7\nfailure_models:\n  max_gap_s: 1\n"
            "  temperature_rise:\n    max_c_per_min: 10\n    min_interval_s: 0.1\n"
        ),
        "remapping": (
            "schema_version: 5\nsignals:\n  timestamp: timestamp_s\n"
            "  cell_voltage:\n    pattern: '^cell_(?P<index>\\d+)_v$'\n"
            "  temperature:\n    pattern: '^temp_(?P<index>\\d+)_c$'\n"
        ),
        "stack": "schema_version: 7\nlimits:\n  pack_voltage:\n    cell_sum_max_delta_v: 1\n",
    }[kind]
    inputs["config"].write_text(extra, encoding="utf-8")
    output = tmp_path / "review"
    with pytest.raises(ValueError, match="unsupported|complete stack"):
        operator.review_can(**inputs, output_dir=output)
    assert not output.exists()


def test_precharge_matches_existing_review_without_inventing_acceptance(tmp_path):
    capture = FIXTURES / "precharge_aligned_example.csv"
    context = FIXTURES / "precharge_aligned_example.context.json"
    direct = precharge_file_review.review_paths(capture, context, tmp_path / "direct.json")
    output = tmp_path / "review"
    manifest = operator.review_precharge(capture, context, output)
    assert read(output / "review.json") == direct
    assert manifest["status"] == "OBSERVATIONS_RECORDED"
    assert manifest["exit_code"] == 0
    assert "not a physical acceptance" in (output / "index.html").read_text(encoding="utf-8")
    assert_manifest(output, manifest)


@pytest.mark.parametrize("stage", ["prepare", "analysis", "html", "manifest", "interrupt"])
def test_failure_never_exposes_completed_or_partial_output(inputs, tmp_path, monkeypatch, stage):
    def fail(*args, **kwargs):
        raise KeyboardInterrupt() if stage == "interrupt" else OSError("injected write/read error")

    if stage == "prepare":
        monkeypatch.setattr(operator.can_prepare, "prepare_paths", fail)
    elif stage == "analysis":
        monkeypatch.setattr(operator.AnalysisService, "analyze_path", fail)
    elif stage in ("html", "interrupt"):
        monkeypatch.setattr(operator, "write_html_report", fail)
    else:
        monkeypatch.setattr(operator, "_json", fail)
    with pytest.raises(KeyboardInterrupt if stage == "interrupt" else OSError):
        operator.review_can(**inputs, output_dir=tmp_path / "review")
    assert not (tmp_path / "review").exists()
    assert not list(tmp_path.glob(".research-operator-*"))


@pytest.mark.parametrize("role", ["log", "dbc", "profile", "config"])
def test_sources_changed_after_analysis_are_rejected(inputs, tmp_path, monkeypatch, role):
    original = operator.write_html_report

    def mutate(*args, **kwargs):
        original(*args, **kwargs)
        with inputs[role].open("a", encoding="utf-8") as handle:
            handle.write("\n")

    monkeypatch.setattr(operator, "write_html_report", mutate)
    with pytest.raises(ValueError, match="changed during analysis"):
        operator.review_can(**inputs, output_dir=tmp_path / "review")
    assert not (tmp_path / "review").exists()


@pytest.mark.parametrize("workflow", ["can", "precharge"])
def test_existing_output_and_concurrent_created_output_are_preserved(
    inputs, tmp_path, monkeypatch, workflow
):
    output = tmp_path / "review"

    def call():
        if workflow == "can":
            return operator.review_can(**inputs, output_dir=output)
        return operator.review_precharge(
            FIXTURES / "precharge_aligned_example.csv",
            FIXTURES / "precharge_aligned_example.context.json",
            output,
        )

    original = operator._verify_sources

    def create(*args, **kwargs):
        original(*args, **kwargs)
        output.mkdir(exist_ok=True)
        (output / "owned.txt").write_bytes(b"other writer")

    monkeypatch.setattr(operator, "_verify_sources", create)
    with pytest.raises(ValueError, match="already exists"):
        call()
    assert sorted(p.name for p in output.iterdir()) == ["owned.txt"]
    assert (output / "owned.txt").read_bytes() == b"other writer"
    with pytest.raises(ValueError, match="already exists"):
        call()


def test_actual_can_cli_exit_codes_and_no_overwrite(inputs, tmp_path):
    def command():
        return [
            sys.executable,
            "-m",
            "batterylog_research.operator",
            "can",
            *[token for name, path in inputs.items() for token in (f"--{name}", str(path))],
            "--output-dir",
            str(tmp_path / "review"),
        ]

    for maximum, status, expected in [(55, "PASS", 0), (10, "FAIL", 1), (None, "NOT_EVALUATED", 3)]:
        inputs["config"].write_text(
            f"schema_version: 5\nlimits:\n  temperature:\n    max_c: {maximum if maximum is not None else 'null'}\n",
            encoding="utf-8",
        )
        output = tmp_path / "review"
        if output.exists():
            # Preserve completed products and use a new destination on each run.
            output.rename(tmp_path / f"saved-{maximum}")
        done = subprocess.run(command(), check=False, capture_output=True, text=True)
        assert done.returncode == expected, done.stderr
        assert json.loads(done.stdout)["status"] == status
        before = {p.name: digest(p) for p in output.iterdir() if p.is_file()}
        repeated = subprocess.run(command(), check=False, capture_output=True, text=True)
        assert repeated.returncode == 4
        assert "already exists" in repeated.stderr
        assert before == {p.name: digest(p) for p in output.iterdir() if p.is_file()}


def test_actual_precharge_cli_and_bad_input(tmp_path):
    command = [
        sys.executable,
        "-m",
        "batterylog_research.operator",
        "precharge",
        "--csv",
        str(FIXTURES / "precharge_aligned_example.csv"),
        "--context",
        str(FIXTURES / "precharge_aligned_example.context.json"),
        "--output-dir",
        str(tmp_path / "review"),
    ]
    done = subprocess.run(command, check=False, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["status"] == "OBSERVATIONS_RECORDED"
    command[command.index("--csv") + 1] = str(tmp_path / "absent.csv")
    command[-1] = str(tmp_path / "bad")
    failed = subprocess.run(command, check=False, capture_output=True, text=True)
    assert failed.returncode == 4
    assert not (tmp_path / "bad").exists()
    usage = subprocess.run(
        [sys.executable, "-m", "batterylog_research.operator", "can"],
        check=False,
        capture_output=True,
    )
    assert usage.returncode == 2


def test_can_hashes_bind_the_consumed_sources_not_only_the_final_paths(
    inputs, tmp_path, monkeypatch
):
    original = operator.can_prepare.prepare_paths

    def change_before_preparation(log, *args):
        with log.open("a", encoding="utf-8") as handle:
            handle.write("(0.1) can0 100#AC0DDE0D\n")
        return original(log, *args)

    monkeypatch.setattr(operator.can_prepare, "prepare_paths", change_before_preparation)
    with pytest.raises(ValueError, match="log changed before preparation"):
        operator.review_can(**inputs, output_dir=tmp_path / "review")
    assert not (tmp_path / "review").exists()


def test_precharge_hashes_bind_the_consumed_context(tmp_path, monkeypatch):
    capture = FIXTURES / "precharge_aligned_example.csv"
    context = tmp_path / "context.json"
    context.write_bytes((FIXTURES / "precharge_aligned_example.context.json").read_bytes())
    original = operator.precharge_file_review.review_paths

    def change_before_review(capture, context, output):
        declaration = read(context)
        declaration["measurement_context"]["time_basis"] += " changed"
        context.write_text(json.dumps(declaration), encoding="utf-8")
        return original(capture, context, output)

    monkeypatch.setattr(operator.precharge_file_review, "review_paths", change_before_review)
    with pytest.raises(ValueError, match="context changed before precharge review"):
        operator.review_precharge(capture, context, tmp_path / "review")
    assert not (tmp_path / "review").exists()
