"""File-boundary regressions for the explicitly aligned precharge observer."""

import hashlib
import json
import subprocess
import sys

import pytest

from batterylog_research import precharge_file_review as review

HEADER = ",".join(review.COLUMNS) + "\n"
NORMAL = HEADER + "-0.1,0,0,400,0\n0,1,8,400,0\n0.1,1,7,400,40\n0.2,1,6,400,80\n0.3,0,0,400,80\n"


def files(tmp_path, text=NORMAL, **updates):
    capture = tmp_path / "aligned.csv"
    capture.write_bytes(text.encode("utf-8"))
    context = tmp_path / "context.json"
    declaration = {
        "format": "batterylog-precharge-aligned-v1",
        "capture_sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
        "input_kind": "authored_fixture",
        "measurement_context": dict.fromkeys(
            review.CONTEXT_FIELDS, "Authored aligned software fixture; no physical claim"
        ),
        "same_reference_for_all_spans": True,
        "max_gap_s": 0.2,
        "envelope": [[0, 0, 10, -0.1, 1.1], [0.2, 0, 10, -0.1, 1.1]],
    }
    declaration.update(updates)
    context.write_text(json.dumps(declaration), encoding="utf-8")
    return capture, context, tmp_path / "report.json"


def run(paths):
    return review.review_paths(*paths)


def test_normal_capture_and_provenance(tmp_path):
    paths = files(tmp_path)
    before = [p.read_bytes() for p in paths[:2]]
    result = run(paths)
    assert result["review"]["covered_reference_intervals"] == 1
    assert result["review"]["reviewed_samples"] == 3
    assert result["review"]["outside_envelope_samples"] == 0
    assert result["physical_measurement_acceptance"] == "caller_declarations_not_authenticated"
    assert result["capture"]["sha256"] == hashlib.sha256(before[0]).hexdigest()
    assert result["context"]["sha256"] == hashlib.sha256(before[1]).hexdigest()
    assert [p.read_bytes() for p in paths[:2]] == before
    assert json.loads(paths[2].read_text()) == result
    assert len(result["implementation_sha256"]) == 3
    assert not list(tmp_path.glob(".batterylog-precharge-*"))


def test_same_bytes_produce_identical_reports(tmp_path):
    paths = files(tmp_path)
    first = run(paths)
    second = review.review_paths(paths[0], paths[1], tmp_path / "second.json")
    assert first == second


@pytest.mark.parametrize(
    "text",
    [
        NORMAL.replace("current_a", "pack_current_a"),
        NORMAL.replace("current_a", "precharge_active"),
        NORMAL.replace("0.1,1,7,400,40", "0.1,1,7,400,40,extra"),
        NORMAL.replace("0.1,1,7,400,40", "0.1,1,7,400"),
        NORMAL.replace("0.1,1,7,400,40", ""),
        HEADER,
        "",
        HEADER + '0,1,"unterminated,400,40',
    ],
)
def test_malformed_csv_rejected_without_output(tmp_path, text):
    paths = files(tmp_path, text)
    with pytest.raises((ValueError, review.csv.Error)):
        run(paths)
    assert not paths[2].exists()


@pytest.mark.parametrize(
    "token", ["true", "NaN", "Infinity", "1_000", "1e-9999", "1e9999", "1e99999999999999999999999"]
)
def test_invalid_measurement_tokens_rejected(tmp_path, token):
    paths = files(tmp_path, NORMAL.replace("0.1,1,7,400,40", f"0.1,1,{token},400,40"))
    with pytest.raises(ValueError):
        run(paths)
    assert not paths[2].exists()


@pytest.mark.parametrize(
    "token", ["", "NaN", "Infinity", "true", "1e-9999", "1e9999", "1e99999999999999999999999"]
)
def test_invalid_time_rejected(tmp_path, token):
    paths = files(tmp_path, NORMAL.replace("0.1,1,7,400,40", f"{token},1,7,400,40"))
    with pytest.raises(ValueError):
        run(paths)
    assert not paths[2].exists()


def test_original_descending_clock_not_hidden_by_rounding(tmp_path):
    text = HEADER + "9007199254740993,0,0,400,0\n9007199254740992,1,8,400,0\n"
    paths = files(tmp_path, text)
    with pytest.raises(ValueError, match="before binary64"):
        run(paths)


def test_original_increasing_clock_collapse_cannot_complete(tmp_path):
    text = HEADER + "9007199254740992,0,0,400,0\n9007199254740993,1,8,400,0\n"
    result = run(files(tmp_path, text))["review"]
    assert result["covered_reference_intervals"] == 0
    assert result["observed_activations"] == 0


@pytest.mark.parametrize("phase", ["", "2", "1.00000000000000000000000000001"])
def test_unknown_phase_not_rounded_into_active(tmp_path, phase):
    paths = files(tmp_path, NORMAL.replace("0.1,1,7,400,40", f"0.1,{phase},7,400,40"))
    result = run(paths)["review"]
    assert result["unknown_phase_samples"] == 1
    assert result["covered_reference_intervals"] == 0
    assert result["unobserved_active_spans"] == 1


@pytest.mark.parametrize("column", [2, 3, 4])
def test_missing_active_measurement_breaks_coverage(tmp_path, column):
    row = ["0.1", "1", "7", "400", "40"]
    row[column] = ""
    result = run(files(tmp_path, NORMAL.replace("0.1,1,7,400,40", ",".join(row))))["review"]
    assert result["covered_reference_intervals"] == 0
    assert "invalid_active_measurement" in result["active_spans"][0]["incomplete_reasons"]


def test_gap_preserves_earlier_deviation_without_healing(tmp_path):
    text = (
        NORMAL.replace("0,1,8,400,0", "0,1,20,400,0")
        .replace("0.1,1,7,400,40", "0.5,1,7,400,40")
        .replace("0.2,1,6,400,80", "0.6,1,6,400,80")
        .replace("0.3,0", "0.7,0")
    )
    result = run(files(tmp_path, text))["review"]
    assert result["covered_reference_intervals"] == 0
    assert result["outside_envelope_samples"] == 1
    assert result["active_spans"][0]["examples"][0]["sample_index"] == 1


def test_multiline_record_keeps_physical_source_lines(tmp_path):
    text = NORMAL.replace("0.1,1,7,400,40", '"0.1\n",1,20,400,40')
    result = run(files(tmp_path, text))["review"]["active_spans"][0]
    assert result["source_active_csv_line_range_inclusive"] == [3, 6]
    example = result["examples"][0]
    assert example["sample_index"] == 2
    assert example["source_csv_line_range_inclusive"] == [4, 5]


def test_multiple_spans_and_explicit_output_bound(tmp_path):
    extra = "1,0,0,400,0\n1.1,1,8,400,0\n1.2,1,7,400,40\n1.3,1,6,400,80\n"
    result = run(files(tmp_path, NORMAL + extra))["review"]
    assert result["covered_reference_intervals"] == 2
    assert result["active_spans"][1]["source_active_start_index"] == 6
    other = tmp_path / "limited"
    other.mkdir()
    paths = files(other, NORMAL + extra, max_spans=1)
    with pytest.raises(ValueError, match="max_spans"):
        run(paths)
    assert not paths[2].exists()


@pytest.mark.parametrize(
    "updates",
    [
        {"format": "other"},
        {"capture_sha256": "0" * 64},
        {"input_kind": "raw_can"},
        {"measurement_context": {}},
        {"measurement_context": dict.fromkeys(review.CONTEXT_FIELDS, "")},
        {"same_reference_for_all_spans": False},
        {"same_reference_for_all_spans": 1},
        {"max_gap_s": True},
        {"max_gap_s": float("inf")},
        {"max_spans": True},
        {"max_examples": 101},
        {"envelope": [[0, 0, 1, 0, 1], [0, 0, 1, 0, 1]]},
        {"envelope": [[0, False, 1, 0, 1], [1, 0, 1, 0, 1]]},
        {"unexpected": "typo"},
    ],
)
def test_bad_context_rejected(tmp_path, updates):
    paths = files(tmp_path, **updates)
    with pytest.raises(ValueError):
        run(paths)
    assert not paths[2].exists()


@pytest.mark.parametrize("field", ["time_basis", "max_gap_s"])
def test_duplicate_json_key_rejected_at_any_depth(tmp_path, field):
    paths = files(tmp_path)
    raw = paths[1].read_text()
    value = (
        '"Authored aligned software fixture; no physical claim"' if field == "time_basis" else "0.2"
    )
    raw = raw.replace(f'"{field}": {value}', f'"{field}": {value}, "{field}": {value}')
    paths[1].write_text(raw)
    with pytest.raises(ValueError, match="Duplicate context key"):
        run(paths)
    assert not paths[2].exists()


def test_context_is_bound_to_snapshot_bytes(tmp_path):
    paths = files(tmp_path)
    paths[0].write_bytes(paths[0].read_bytes() + b"\n")
    with pytest.raises(ValueError, match="capture_sha256"):
        run(paths)


def test_input_byte_and_row_limits(tmp_path, monkeypatch):
    paths = files(tmp_path)
    monkeypatch.setattr(review, "MAX_CAPTURE_BYTES", 10)
    with pytest.raises(ValueError, match="byte input bound"):
        run(paths)
    monkeypatch.setattr(review, "MAX_CAPTURE_BYTES", 2**20)
    monkeypatch.setattr(review, "MAX_CONTEXT_BYTES", 10)
    with pytest.raises(ValueError, match="byte input bound"):
        run(paths)
    monkeypatch.setattr(review, "MAX_CONTEXT_BYTES", 2**20)
    monkeypatch.setattr(review, "MAX_ROWS", 2)
    with pytest.raises(ValueError, match="row input bound"):
        run(paths)
    assert not paths[2].exists()


def test_existing_output_and_input_alias_preserved(tmp_path):
    paths = files(tmp_path)
    paths[2].write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        run(paths)
    assert paths[2].read_bytes() == b"existing"
    before = paths[0].read_bytes()
    with pytest.raises(FileExistsError):
        review.review_paths(paths[0], paths[1], paths[0])
    assert paths[0].read_bytes() == before


def test_encoding_failure_leaves_no_output(tmp_path, monkeypatch):
    paths = files(tmp_path)

    def fail(*args, **kwargs):
        raise ValueError("strict encoding failed")

    monkeypatch.setattr(review.json, "dumps", fail)
    with pytest.raises(ValueError, match="strict encoding"):
        run(paths)
    assert not paths[2].exists()
    assert not list(tmp_path.glob(".batterylog-precharge-*"))


def test_competing_publisher_preserved(tmp_path, monkeypatch):
    paths = files(tmp_path)
    original = review.os.link

    def competing_link(source, destination):
        destination.write_bytes(b"other writer")
        original(source, destination)

    monkeypatch.setattr(review.os, "link", competing_link)
    with pytest.raises(FileExistsError):
        run(paths)
    assert paths[2].read_bytes() == b"other writer"
    assert not list(tmp_path.glob(".batterylog-precharge-*"))


def test_real_cli_and_refused_overwrite(tmp_path):
    paths = files(tmp_path)
    command = [
        sys.executable,
        "-m",
        "batterylog_research.precharge_file_review",
        "--csv",
        str(paths[0]),
        "--context",
        str(paths[1]),
        "--output",
        str(paths[2]),
    ]
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
    original = paths[2].read_bytes()
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    assert completed.returncode == 2
    assert "error:" in completed.stderr
    assert paths[2].read_bytes() == original


def test_excessively_nested_json_rejected_without_output(tmp_path):
    paths = files(tmp_path)
    paths[1].write_text("[" * 2000 + "0" + "]" * 2000)
    with pytest.raises(ValueError):
        run(paths)
    assert not paths[2].exists()


def test_producer_declaration_is_still_not_authentication(tmp_path):
    result = run(files(tmp_path, input_kind="producer_aligned_capture"))
    assert result["physical_measurement_acceptance"] == "caller_declarations_not_authenticated"
