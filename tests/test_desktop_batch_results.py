import pytest

from batterylog.batch import _pending_summary, _write_summary
from batterylog.desktop_batch_results import read_batch_rows
from batterylog.desktop_job import DesktopBatchOutcome


def summary_outcome(directory, item):
    return DesktopBatchOutcome(
        "PASS",
        "Completed",
        directory,
        {
            "batch_schema_version": 1,
            "config_sha256": None,
            "summary_csv": "summary.csv",
            "files": [item],
        },
    )


def test_no_summary_does_not_infer_results_from_leftover_reports(tmp_path):
    (tmp_path / "report.html").write_text("completed file", encoding="utf-8")
    assert read_batch_rows(DesktopBatchOutcome("CANCELLED", "Cancelled", tmp_path)) == []


@pytest.mark.parametrize("source", ["ölçüm,quoted.csv", "=formula.csv", "'=literal.csv"])
def test_retained_csv_preserves_completed_names_diagnostics_and_unknown_counts(tmp_path, source):
    completed = _pending_summary(source)
    completed.update(
        status="NOT_EVALUATED",
        violation_events=2,
        report_html=f"files/{source}/report.html",
    )
    broken = _pending_summary("broken.csv")
    broken.update(status="ERROR", error="ValueError: first line,\nsecond line")
    pending = _pending_summary("pending.csv")
    path = tmp_path / "summary.csv"
    _write_summary([completed, broken, pending], path)
    outcome = DesktopBatchOutcome("CANCELLED", "Cancelled", tmp_path, summary_csv=path)

    rows = read_batch_rows(outcome)
    assert [row.source for row in rows] == [source, "broken.csv", "pending.csv"]
    assert [row.status for row in rows] == ["NOT_EVALUATED", "ERROR", "NOT_PROCESSED"]
    assert [row.violation_events for row in rows] == [2, None, None]
    assert rows[0].report == tmp_path / f"files/{source}/report.html"
    assert rows[1].error == "ValueError: first line,\nsecond line"
    assert rows[1].report is None and rows[2].report is None


@pytest.mark.parametrize("count", [-1, True, 1.5, "2", [], {}])
def test_invalid_json_counts_cannot_be_displayed_as_measurement_results(tmp_path, count):
    item = _pending_summary("a.csv")
    item.update(status="PASS", violation_events=count, report_html="files/a.csv/report.html")
    with pytest.raises(OSError, match="violation count"):
        read_batch_rows(summary_outcome(tmp_path, item))


@pytest.mark.parametrize(
    "report",
    [
        "/outside/report.html",
        "../report.html",
        "files/../outside/report.html",
        "C:/outside/report.html",
    ],
)
def test_summary_cannot_link_a_report_outside_its_batch(tmp_path, report):
    item = _pending_summary("a.csv")
    item.update(status="PASS", violation_events=0, report_html=report)
    with pytest.raises(OSError, match="report path"):
        read_batch_rows(summary_outcome(tmp_path, item))


def test_summary_cannot_link_another_measurements_report(tmp_path):
    item = _pending_summary("a.csv")
    item.update(status="PASS", violation_events=0, report_html="files/b.csv/report.html")
    with pytest.raises(OSError, match="disagrees"):
        read_batch_rows(summary_outcome(tmp_path, item))


@pytest.mark.parametrize(
    "text",
    [
        "source,status\na.csv,PASS\n",
        "source,status,violation_events,error,report_html,status\na.csv,PASS,0,,,ERROR\n",
        "source,status,violation_events,error,report_html\na.csv,PASS,0,,,extra\n",
        "source,status,violation_events,error,report_html\na.csv,NOT_PROCESSED,\n",
        "source,status,violation_events,error,report_html\na.csv,PASS,-1,,\n",
    ],
)
def test_malformed_retained_csv_fails_closed(tmp_path, text):
    path = tmp_path / "summary.csv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(OSError):
        read_batch_rows(DesktopBatchOutcome("CANCELLED", "Cancelled", tmp_path, summary_csv=path))
