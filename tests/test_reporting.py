import hashlib
import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

import batterylog.reporting.evidence as evidence_module
from batterylog import (
    DataQualityConfig,
    EventDetectionConfig,
    SignalMapping,
    SignalPattern,
    ValidationLimits,
    analyze_battery_log,
)
from batterylog.analysis.core import analyze_battery_bytes
from batterylog.analysis.report_series import ReportSeriesCollector
from batterylog.analysis.streaming import analyze_battery_file_with_report_series
from batterylog.reporting import (
    FileEvidence,
    ReportMetadata,
    build_report_metadata,
    capture_file_evidence,
    capture_file_snapshot,
    render_html_report,
    render_json_result,
    sha256_file,
    verify_file_unchanged,
    write_html_report,
    write_json_result,
)
from batterylog.reporting.evidence import capture_file_backed_snapshot

SAMPLE = Path(__file__).parents[1] / "examples" / "sample_battery_log.csv"


def _metadata() -> ReportMetadata:
    return ReportMetadata(
        batterylog_version="0.4.0",
        generated_at_utc="2026-09-18T18:00:00Z",
        source=FileEvidence(
            name='sample<script>alert("x")</script>.csv',
            sha256="source-digest",
            size_bytes=123,
            mtime_ns=1,
        ),
        config=FileEvidence(
            name="limits<unsafe>.yaml",
            sha256="config-digest",
            size_bytes=45,
            mtime_ns=2,
        ),
    )


def test_render_html_report_contains_validation_evidence() -> None:
    result = analyze_battery_log(
        SAMPLE,
        limits=ValidationLimits(
            imbalance_max_v=0.08,
            temperature_max_c=45.0,
        ),
    )

    html = render_html_report(result, metadata=_metadata())

    assert "<!doctype html>" in html
    assert "<strong>FAIL</strong>" in html
    assert "CELL_IMBALANCE_HIGH" in html
    assert "TEMPERATURE_HIGH" in html
    assert "0.08 V" in html
    assert "45 degC" in html
    assert "0.4.0" in html
    assert "source-digest" in html
    assert "config-digest" in html
    assert "Result schema" in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "limits&lt;unsafe&gt;.yaml" in html
    assert 'class="timeseries-chart"' not in html


def test_full_html_report_with_plots_is_deterministic_for_fixed_inputs() -> None:
    with SAMPLE.open("rb") as handle:
        result, series = analyze_battery_file_with_report_series(
            handle,
            source_name=SAMPLE.name,
            limits=ValidationLimits(
                imbalance_max_v=0.08,
                temperature_max_c=45.0,
            ),
        )

    first = render_html_report(result, metadata=_metadata(), series=series)
    second = render_html_report(result, metadata=_metadata(), series=series)

    assert first == second
    assert first.count('class="timeseries-chart"') == 3


def test_not_evaluated_report_is_not_presented_as_pass() -> None:
    result = analyze_battery_log(SAMPLE)

    html = render_html_report(result)

    assert "<strong>NOT_EVALUATED</strong>" in html
    assert "No engineering rules were evaluated" in html
    assert "No violation events were recorded." in html


def test_pass_report_states_that_evaluated_rules_passed() -> None:
    result = analyze_battery_log(
        SAMPLE,
        limits=ValidationLimits(
            imbalance_max_v=0.11,
            temperature_max_c=50.0,
        ),
    )

    html = render_html_report(result)

    assert "<strong>PASS</strong>" in html
    assert "All evaluated engineering rules passed." in html


def test_write_html_report_writes_utf8_file_atomically(tmp_path: Path) -> None:
    result = analyze_battery_log(SAMPLE)
    output = tmp_path / "report.html"

    returned = write_html_report(
        result,
        output,
        metadata=_metadata(),
    )

    assert returned == output
    text = output.read_text(encoding="utf-8")
    assert "Battery Validation Report" in text
    assert "source-digest" in text
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_atomic_write_cleans_temporary_file_on_replace_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    result = analyze_battery_log(SAMPLE)
    output = tmp_path / "report.html"

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        write_html_report(result, output, metadata=_metadata())

    assert not output.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_sha256_file_returns_stable_digest(tmp_path: Path) -> None:
    path = tmp_path / "evidence.bin"
    path.write_bytes(b"batterylog")

    assert sha256_file(path) == ("748d20e2f610be9cf9249ecfb5cdb8fb697be29bcd1c113544b363ec02ccb403")


def test_capture_and_verify_file_evidence(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_bytes(b"abc")

    evidence = capture_file_evidence(path)

    assert evidence.name == "input.csv"
    assert evidence.size_bytes == 3
    assert evidence.sha256 == sha256_file(path)
    verify_file_unchanged(path, evidence)


def test_verify_file_unchanged_rejects_modified_file(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_bytes(b"abc")
    evidence = capture_file_evidence(path)

    path.write_bytes(b"changed")

    with pytest.raises(ValueError, match="changed during analysis"):
        verify_file_unchanged(path, evidence)


def test_snapshot_evidence_hashes_the_exact_captured_bytes(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_bytes(b"abc")

    snapshot = capture_file_snapshot(path)

    assert snapshot.data == b"abc"
    assert snapshot.evidence.sha256 == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert snapshot.evidence.size_bytes == len(snapshot.data)


def test_file_backed_snapshot_hashes_the_exact_captured_bytes(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    data = b"timestamp_s,temp_c,cell_1_v\n0,25,3.8\n"
    path.write_bytes(data)

    with capture_file_backed_snapshot(path) as snapshot:
        handle = snapshot.handle
        assert handle.read() == data
        assert snapshot.evidence.sha256 == hashlib.sha256(data).hexdigest()
        assert snapshot.evidence.size_bytes == len(data)
        assert not handle.closed

    assert handle.closed


def test_capture_rejects_file_changed_while_snapshotting(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "input.csv"
    path.write_bytes(b"abc")
    original_read_bytes = Path.read_bytes

    def read_then_mutate(value: Path) -> bytes:
        data = original_read_bytes(value)
        if value == path:
            value.write_bytes(b"changed-size")
        return data

    monkeypatch.setattr(Path, "read_bytes", read_then_mutate)

    with pytest.raises(ValueError, match="changed while snapshotting"):
        capture_file_snapshot(path)


def test_build_report_metadata_normalizes_time_to_utc(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_bytes(b"abc")
    source = capture_file_evidence(path)
    local_time = datetime(
        2026,
        9,
        18,
        21,
        0,
        tzinfo=timezone(timedelta(hours=3)),
    )

    metadata = build_report_metadata(source, generated_at=local_time)

    assert metadata.generated_at_utc == "2026-09-18T18:00:00Z"
    assert metadata.source == source
    assert metadata.config is None
    assert metadata.batterylog_version


def test_build_report_metadata_rejects_naive_datetime(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_bytes(b"abc")
    source = capture_file_evidence(path)

    with pytest.raises(ValueError, match="timezone-aware"):
        build_report_metadata(
            source,
            generated_at=datetime(
                2026,
                9,
                18,
                18,
                0,
                tzinfo=UTC,
            ).replace(tzinfo=None),
        )


def test_report_metadata_falls_back_when_distribution_is_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "input.csv"
    path.write_bytes(b"abc")
    source = capture_file_evidence(path)

    def missing_distribution(name: str) -> str:
        raise evidence_module.PackageNotFoundError(name)

    monkeypatch.setattr(evidence_module, "version", missing_distribution)

    metadata = build_report_metadata(
        source,
        generated_at=datetime(2026, 9, 18, 18, 0, tzinfo=UTC),
    )

    assert metadata.batterylog_version == "unknown"


def test_report_displays_event_grouping_semantics() -> None:
    result = analyze_battery_log(
        SAMPLE,
        limits=ValidationLimits(imbalance_max_v=0.08),
        event_detection=EventDetectionConfig(max_gap_s=0.5),
    )

    html = render_html_report(result)

    assert "Maximum event gap" in html
    assert "0.5 s" in html


def test_report_labels_default_grouping_as_row_contiguity() -> None:
    result = analyze_battery_log(SAMPLE)

    html = render_html_report(result)

    assert "Maximum event gap" in html
    assert "Row contiguity only" in html


def test_report_displays_canonical_signal_mapping_mode() -> None:
    result = analyze_battery_log(SAMPLE)

    html = render_html_report(result)

    assert "Signal mapping mode" in html
    assert "Canonical schema" in html
    assert "Canonical cell_&lt;n&gt;_v" in html


def test_report_displays_explicit_signal_mapping_provenance(tmp_path: Path) -> None:
    path = tmp_path / "vendor.csv"
    path.write_text(
        "Time_s,CellV_2,CellV_1,Temp_1\n0.0,3.9,3.8,25\n",
        encoding="utf-8",
    )
    mapping = SignalMapping(
        timestamp="Time_s",
        cell_voltage=SignalPattern(r"CellV_(?P<index>\d+)"),
        temperature=SignalPattern(r"Temp_(?P<index>\d+)"),
    )
    result = analyze_battery_log(
        path,
        signal_mapping=mapping,
    )

    html = render_html_report(result)

    assert "Signal mapping mode" in html
    assert "Explicit" in html
    assert "Time_s" in html
    assert r"CellV_(?P&lt;index&gt;\d+)" in html
    assert r"Temp_(?P&lt;index&gt;\d+)" in html


def test_verify_file_unchanged_rehashes_content_even_if_metadata_is_restored(
    tmp_path: Path,
) -> None:
    path = tmp_path / "input.csv"
    path.write_bytes(b"abc")
    evidence = capture_file_evidence(path)
    original_stat = path.stat()

    path.write_bytes(b"xyz")
    os.utime(
        path,
        ns=(original_stat.st_atime_ns, evidence.mtime_ns),
    )

    restored_stat = path.stat()
    assert restored_stat.st_size == evidence.size_bytes
    assert restored_stat.st_mtime_ns == evidence.mtime_ns

    with pytest.raises(ValueError, match="changed during analysis"):
        verify_file_unchanged(path, evidence)


def test_verify_file_unchanged_accepts_metadata_only_change_when_hash_matches(
    tmp_path: Path,
) -> None:
    path = tmp_path / "input.csv"
    path.write_bytes(b"abc")
    evidence = capture_file_evidence(path)
    original_stat = path.stat()

    os.utime(
        path,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1_000_000),
    )

    verify_file_unchanged(path, evidence)


def test_verify_file_unchanged_streams_without_read_bytes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "input.csv"
    path.write_bytes(b"abc")
    evidence = capture_file_evidence(path)

    def fail_read_bytes(candidate: Path) -> bytes:
        raise AssertionError(f"unexpected read_bytes for {candidate}")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    verify_file_unchanged(path, evidence)


def test_report_displays_comparison_semantics() -> None:
    result = analyze_battery_log(SAMPLE)

    html = render_html_report(result)

    assert "Comparison mode" in html
    assert "binary64 boundary guard" in html
    assert "Relative float tolerance" in html
    assert "Absolute float tolerance" in html


def test_json_result_writer_matches_canonical_renderer(tmp_path: Path) -> None:
    result = analyze_battery_log(
        SAMPLE,
        limits=ValidationLimits(imbalance_max_v=0.11),
    )
    output = tmp_path / "result.json"

    returned = write_json_result(result, output)

    assert returned == output
    expected = render_json_result(result)
    assert output.read_text(encoding="utf-8") == expected
    assert output.read_bytes() == expected.encode("utf-8")
    assert list(tmp_path.glob(".*.tmp")) == []


def test_json_result_writer_cleans_temp_file_on_replace_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    result = analyze_battery_log(SAMPLE)
    output = tmp_path / "result.json"

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("simulated JSON replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated JSON replace failure"):
        write_json_result(result, output)

    assert not output.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_json_renderer_rejects_non_finite_result_values() -> None:
    result = analyze_battery_log(SAMPLE)
    result["max_cell_voltage_v"] = float("nan")

    with pytest.raises(ValueError, match="Out of range float values"):
        render_json_result(result)


def test_capture_rejects_snapshot_length_that_disagrees_with_file_size(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "input.csv"
    path.write_bytes(b"abc")
    original_read_bytes = Path.read_bytes

    def return_truncated_snapshot(value: Path) -> bytes:
        data = original_read_bytes(value)
        if value == path:
            return data[:-1]
        return data

    monkeypatch.setattr(Path, "read_bytes", return_truncated_snapshot)

    with pytest.raises(ValueError, match="size changed while snapshotting"):
        capture_file_snapshot(path)


def test_html_report_renders_structured_data_quality_evidence() -> None:
    result = analyze_battery_bytes(
        (b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,3.8,3.79,25\n1,bad,3.79,25\n"),
        limits=ValidationLimits(),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )

    html = render_html_report(result)

    assert "<strong>FAIL</strong>" in html
    assert "Required-data quality defects were recorded." in html
    assert "Input rows</strong><br>2" in html
    assert "Rows analyzed</strong><br>1" in html
    assert "Rows excluded</strong><br>1" in html
    assert "NON_NUMERIC_REQUIRED_VALUE" in html
    assert "<th>Start row</th>" in html
    assert "<td>2</td>" in html
    assert "cell_1_v" in html


def test_all_invalid_data_quality_report_uses_null_safe_extrema_and_empty_plots() -> None:
    result = analyze_battery_bytes(
        (b"timestamp_s,cell_1_v,cell_2_v,temp_c\n0,bad,3.79,25\n1,inf,3.79,25\n"),
        limits=ValidationLimits(cell_max_v=4.2),
        data_quality=DataQualityConfig(mode="exclude_invalid_rows"),
    )
    empty_series = ReportSeriesCollector(max_points=12).finish()

    html = render_html_report(result, series=empty_series)

    assert result["rows_analyzed"] == 0
    assert html.count("N/A") == 5
    assert "No plot data available." in html
    assert "Rows excluded</strong><br>2" in html
    assert "NON_NUMERIC_REQUIRED_VALUE" in html
    assert "NON_FINITE_REQUIRED_VALUE" in html
