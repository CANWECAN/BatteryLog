import copy
import hashlib
import json
from fractions import Fraction

import pytest

from batterylog import AnalysisService, ValidationConfig, ValidationLimits
from batterylog.recording_audit import audit_recordings


def _recording(path="run.csv", recording_id="run-1", **updates):
    record = {
        "id": recording_id,
        "path": path,
        "expected_channels": ["cell_1_v", "temp_c"],
        "time": {
            "column": "timestamp_s",
            "unit": "s",
            "start_s": "0",
            "end_s": "2",
            "max_gap_s": "1",
            "boundary_tolerance_s": "0",
        },
    }
    record.update(updates)
    return record


def _plan(tmp_path, records=None):
    path = tmp_path / "recording-plan.json"
    path.write_text(
        json.dumps(
            {
                "recording_plan_schema_version": 1,
                "recordings": records if records is not None else [_recording()],
            }
        ),
        encoding="utf-8",
    )
    return path


def _csv(tmp_path, times=("0", "1", "2"), voltage="3.7", name="run.csv"):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "timestamp_s,cell_1_v,temp_c\n" + "".join(f"{time},{voltage},25\n" for time in times),
        encoding="utf-8",
    )
    return path


def _codes(record):
    return {issue["code"] for issue in record["issues"]}


def test_complete_audit_preserves_inputs_and_provenance(tmp_path):
    source = _csv(tmp_path)
    plan = _plan(tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    result = audit_recordings(tmp_path, plan=plan)
    assert result["coverage_status"] == "COMPLETE"
    assert result["engineering_analysis_performed"] is False
    assert result["sensor_acquisition_freshness"] == "NOT_EVALUATED"
    assert result["plan_sha256"] == hashlib.sha256(plan.read_bytes()).hexdigest()
    record = result["recordings"][0]
    assert record["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert record["valid_samples"] == {"cell_1_v": 3, "temp_c": 3}
    assert record["observed_time"] == {
        "first_s": "0",
        "last_s": "2",
        "valid_timestamps": 3,
        "largest_gap_s": "1",
    }
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    json.dumps(result, allow_nan=False)


def test_missing_twelfth_record_is_not_hidden_by_eleven_valid_files(tmp_path):
    records = []
    for index in range(12):
        name = f"run-{index:02}.csv"
        records.append(_recording(name, str(index)))
        if index < 11:
            _csv(tmp_path, name=name)
    result = audit_recordings(tmp_path, plan=_plan(tmp_path, records))
    assert result["coverage_status"] == "INCOMPLETE"
    assert [item["coverage_status"] for item in result["recordings"]] == ["COMPLETE"] * 11 + [
        "INCOMPLETE"
    ]
    assert result["recordings"][-1]["id"] == "11"
    assert _codes(result["recordings"][-1]) == {"MISSING_FILE"}


def test_missing_channel_is_named_even_when_core_metadata_is_ok(tmp_path):
    _csv(tmp_path)
    record = _recording(expected_channels=["cell_1_v", "cell_2_v", "temp_c"])
    result = audit_recordings(tmp_path, plan=_plan(tmp_path, [record]))["recordings"][0]
    assert result["inspection_metadata_status"] == "OK"
    assert result["missing_channels"] == ["cell_2_v"]
    assert result["channel_status"] == result["coverage_status"] == "INCOMPLETE"


@pytest.mark.parametrize(
    "times,code",
    [
        (("0", "30"), "WINDOW_NOT_COVERED"),
        (("0", "1", "599", "600"), "TIME_GAP"),
    ],
)
def test_short_record_and_internal_gap_are_distinct(tmp_path, times, code):
    _csv(tmp_path, times=times)
    record = _recording()
    record["time"].update(end_s="600", max_gap_s="30")
    result = audit_recordings(tmp_path, plan=_plan(tmp_path, [record]))["recordings"][0]
    assert result["coverage_status"] == "INCOMPLETE"
    assert code in _codes(result)


@pytest.mark.parametrize("missing", ["expected_channels", "time"])
def test_partial_expectations_cannot_establish_complete_coverage(tmp_path, missing):
    _csv(tmp_path)
    record = _recording()
    del record[missing]
    result = audit_recordings(tmp_path, plan=_plan(tmp_path, [record]))
    assert result["coverage_status"] == "NOT_EVALUATED"
    assert result["recordings"][0]["file_status"] == "COMPLETE"


def test_no_plan_is_not_evaluated(tmp_path):
    _csv(tmp_path)
    result = audit_recordings(tmp_path)
    assert result["coverage_status"] == "NOT_EVALUATED"
    assert result["recordings"] == []
    assert result["issues"][0]["code"] == "PLAN_UNDECLARED"


@pytest.mark.parametrize("voltage,engineering_status", [("4.3", "FAIL"), ("3.7", "PASS")])
def test_recording_coverage_does_not_overwrite_engineering_result(
    tmp_path, voltage, engineering_status
):
    source = _csv(tmp_path, voltage=voltage)
    service = AnalysisService(ValidationConfig(limits=ValidationLimits(cell_max_v=4.2)))
    before = service.analyze_path(source).result
    untouched = copy.deepcopy(before)
    audit = audit_recordings(tmp_path, plan=_plan(tmp_path))
    after = service.analyze_path(source).result
    assert before["validation_status"] == engineering_status
    assert before == untouched == after
    assert audit["coverage_status"] == "COMPLETE"
    assert "validation_status" not in audit
    assert audit["engineering_analysis_performed"] is False


def test_vendor_headers_use_raw_names_without_inferred_mapping(tmp_path):
    (tmp_path / "run.csv").write_text("clock,U_A,T_A\n0,3.7,25\n1,3.7,25\n2,3.7,25\n")
    record = _recording(expected_channels=["U_A", "T_A"])
    record["time"]["column"] = "clock"
    item = audit_recordings(tmp_path, plan=_plan(tmp_path, [record]))["recordings"][0]
    assert item["coverage_status"] == "COMPLETE"
    assert item["inspection_metadata_status"] == "ISSUES"
    assert item["inspection_issues"]


@pytest.mark.parametrize("origin", [0, 1700000000])
def test_exact_decimal_clock_keeps_boundary_decision_at_epoch_origin(tmp_path, origin):
    # Independent rational construction; every interval is exactly 1/10 s.
    times = [str(origin) if index == 0 else f"{origin}.{index}" for index in range(6)]
    _csv(tmp_path, times=times)
    record = _recording()
    record["time"].update(start_s=str(origin), end_s=f"{origin}.5", max_gap_s="0.1")
    item = audit_recordings(tmp_path, plan=_plan(tmp_path, [record]))["recordings"][0]
    assert item["coverage_status"] == "COMPLETE"
    assert Fraction(item["observed_time"]["largest_gap_s"]) == Fraction(1, 10)
    assert item["observed_time"]["valid_timestamps"] == 6


@pytest.mark.parametrize(
    "times,code",
    [
        (("0", "1", "1", "2"), "CLOCK_NOT_INCREASING"),
        (("0", "1", "0.5", "2"), "CLOCK_NOT_INCREASING"),
        (("0", "NaN", "2"), "INVALID_TIMESTAMP"),
        (("0", "1e9999999999999999999999999", "2"), "INVALID_TIMESTAMP"),
    ],
)
def test_bad_clock_is_not_sorted_repaired_or_silently_accepted(tmp_path, times, code):
    _csv(tmp_path, times=times)
    item = audit_recordings(tmp_path, plan=_plan(tmp_path))["recordings"][0]
    assert item["coverage_status"] == "INCOMPLETE"
    assert code in _codes(item)


@pytest.mark.parametrize("value", ["", "NaN", "inf", "broken", "1_000"])
def test_expected_channel_requires_finite_numeric_samples(tmp_path, value):
    _csv(tmp_path, voltage=value)
    item = audit_recordings(tmp_path, plan=_plan(tmp_path))["recordings"][0]
    assert item["channel_status"] == "INCOMPLETE"
    assert item["valid_samples"]["cell_1_v"] == 0
    assert {"INVALID_CHANNEL_SAMPLE", "NO_VALID_SAMPLES"} <= _codes(item)


@pytest.mark.parametrize(
    "data",
    [
        "timestamp_s,cell_1_v,temp_c\n0,3.7,25,extra\n",
        "timestamp_s,cell_1_v,temp_c\n0,3.7\n",
        "timestamp_s,cell_1_v,temp_c\n\n",
        'timestamp_s,cell_1_v,temp_c\n0,"3.7,25\n',
        "timestamp_s,cell_1_v,cell_1_v,temp_c\n0,3.7,3.7,25\n",
    ],
)
def test_malformed_csv_is_error(tmp_path, data):
    (tmp_path / "run.csv").write_text(data, encoding="utf-8")
    result = audit_recordings(tmp_path, plan=_plan(tmp_path))
    assert result["coverage_status"] == "ERROR"
    assert "SOURCE_ERROR" in _codes(result["recordings"][0])


def test_header_only_is_not_a_complete_recording(tmp_path):
    _csv(tmp_path, times=())
    item = audit_recordings(tmp_path, plan=_plan(tmp_path))["recordings"][0]
    assert item["file_status"] == item["channel_status"] == item["time_status"] == "INCOMPLETE"


def test_two_independent_files_with_equal_bytes_are_not_assumed_same_run(tmp_path):
    _csv(tmp_path)
    _csv(tmp_path, name="other.csv")
    result = audit_recordings(
        tmp_path, plan=_plan(tmp_path, [_recording(), _recording("other.csv", "run-2")])
    )
    assert result["coverage_status"] == "COMPLETE"
    assert result["recordings"][0]["source_sha256"] == result["recordings"][1]["source_sha256"]


def test_hardlink_alias_cannot_fulfil_two_recording_ids(tmp_path):
    source = _csv(tmp_path)
    (tmp_path / "alias.csv").hardlink_to(source)
    result = audit_recordings(
        tmp_path, plan=_plan(tmp_path, [_recording(), _recording("alias.csv", "run-2")])
    )
    assert result["coverage_status"] == "ERROR"
    assert all("AMBIGUOUS_FILE_IDENTITY" in _codes(item) for item in result["recordings"])


@pytest.mark.parametrize(
    "path",
    [
        "../run.csv",
        "/run.csv",
        "C:/run.csv",
        "a\\run.csv",
        "a/./run.csv",
        "a//run.csv",
        "run.csv:stream",
        "run.mf4",
    ],
)
def test_nonportable_or_outside_paths_are_rejected_before_input_scan(tmp_path, path):
    with pytest.raises(ValueError, match="path"):
        audit_recordings(tmp_path, plan=_plan(tmp_path, [_recording(path)]))


@pytest.mark.parametrize(
    "change",
    [
        {"extra": True},
        {"expected_channels": []},
        {"expected_channels": ["temp_c", "temp_c"]},
        {"id": ""},
        {"time": {"column": "timestamp_s"}},
    ],
)
def test_incomplete_or_misspelled_plan_is_rejected(tmp_path, change):
    with pytest.raises(ValueError):
        audit_recordings(tmp_path, plan=_plan(tmp_path, [_recording(**change)]))


@pytest.mark.parametrize(
    "change",
    [
        {"start_s": "2"},
        {"end_s": "0"},
        {"max_gap_s": "0"},
        {"boundary_tolerance_s": "-1"},
        {"boundary_tolerance_s": "1"},
        {"unit": "ms"},
        {"start_s": 0},
        {"max_gap_s": "NaN"},
    ],
)
def test_time_expectations_require_explicit_consistent_decimal_seconds(tmp_path, change):
    record = _recording()
    record["time"].update(change)
    with pytest.raises(ValueError):
        audit_recordings(tmp_path, plan=_plan(tmp_path, [record]))


@pytest.mark.parametrize(
    "records",
    [
        [],
        [_recording(), _recording(recording_id="run-2")],
        [_recording(), _recording("RUN.csv", "run-2")],
    ],
)
def test_empty_or_ambiguous_recording_inventory_is_rejected(tmp_path, records):
    with pytest.raises(ValueError):
        audit_recordings(tmp_path, plan=_plan(tmp_path, records))


def test_duplicate_json_key_is_rejected(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(
        '{"recording_plan_schema_version":1,"recording_plan_schema_version":1,"recordings":[]}'
    )
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        audit_recordings(tmp_path, plan=plan)


def test_declared_boundary_tolerance_is_applied_exactly(tmp_path):
    _csv(tmp_path, times=("0.1", "1.0", "1.9"))
    record = _recording()
    record["time"]["boundary_tolerance_s"] = "0.1"
    assert (
        audit_recordings(tmp_path, plan=_plan(tmp_path, [record]))["coverage_status"] == "COMPLETE"
    )
    record["time"]["boundary_tolerance_s"] = "0.099999999999999999999"
    assert (
        audit_recordings(tmp_path, plan=_plan(tmp_path, [record]))["coverage_status"]
        == "INCOMPLETE"
    )


def test_missing_time_column_is_incomplete(tmp_path):
    _csv(tmp_path)
    record = _recording()
    record["time"]["column"] = "other_clock"
    item = audit_recordings(tmp_path, plan=_plan(tmp_path, [record]))["recordings"][0]
    assert item["time_status"] == "INCOMPLETE"
    assert "MISSING_TIME_COLUMN" in _codes(item)


def test_48_channel_plan_reports_the_missing_48th_channel(tmp_path):
    names = [f"cell_{index}_v" for index in range(1, 49)]
    header = ["timestamp_s", *names[:-1], "temp_c"]
    data = ",".join(header) + "\n"
    data += "".join(",".join([str(t), *(["3.7"] * 47), "25"]) + "\n" for t in range(3))
    (tmp_path / "run.csv").write_text(data, encoding="utf-8")
    record = _recording(expected_channels=[*names, "temp_c"])
    item = audit_recordings(tmp_path, plan=_plan(tmp_path, [record]))["recordings"][0]
    assert item["missing_channels"] == ["cell_48_v"]
    assert item["coverage_status"] == "INCOMPLETE"


def test_physical_file_replacement_after_assignment_is_error(tmp_path, monkeypatch):
    import batterylog.recording_audit as audit_module

    _csv(tmp_path)
    inspect = audit_module.inspect_measurement

    def replace_after_inspection(path):
        result = inspect(path)
        replacement = _csv(tmp_path, name="replacement.csv", voltage="3.8")
        replacement.replace(path)
        return result

    monkeypatch.setattr(audit_module, "inspect_measurement", replace_after_inspection)
    item = audit_recordings(tmp_path, plan=_plan(tmp_path))["recordings"][0]
    assert item["coverage_status"] == "ERROR"
    assert "Physical recording file changed" in item["issues"][-1]["detail"]


@pytest.mark.parametrize("tiny", [False, True])
def test_supported_clock_is_independent_of_ambient_decimal_context(tmp_path, tiny):
    from decimal import Subnormal, localcontext

    times = (
        ("0", "0.00000001", "0.00000002")
        if tiny
        else ("1700000000", "1700000000.1", "1700000000.2")
    )
    _csv(tmp_path, times=times)
    record = _recording()
    record["time"].update(
        start_s=times[0], end_s=times[-1], max_gap_s="0.00000001" if tiny else "0.1"
    )
    plan = _plan(tmp_path, [record])
    with localcontext() as context:
        context.Emax = 6
        context.Emin = -2
        context.traps[Subnormal] = True
        before = context.copy()
        result = audit_recordings(tmp_path, plan=plan)
        assert result["coverage_status"] == "COMPLETE"
        assert context.Emax == before.Emax
        assert context.Emin == before.Emin
        assert context.traps == before.traps
