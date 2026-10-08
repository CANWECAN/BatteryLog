"""Real Tcl/Tk widget tests; use xvfb-run on Linux without a desktop session."""

import os
import time
from pathlib import Path

import pytest

if os.environ.get("BATTERYLOG_REQUIRE_DESKTOP_TESTS") == "1":
    import tkinter as tk
else:
    tk = pytest.importorskip("tkinter")


@pytest.fixture
def ui():
    from batterylog.desktop_ui import DesktopWindow

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        if os.environ.get("BATTERYLOG_REQUIRE_DESKTOP_TESTS") == "1":
            pytest.fail(f"Required desktop tests cannot open Tk: {exc}")
        pytest.skip(f"No graphical session: {exc}")
    root.withdraw()
    window = DesktopWindow(root)
    yield window
    active = window.job or window.inspection_job or window.batch_job
    if active is not None:
        active.cancel()
        deadline = time.monotonic() + 5
        while active.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.mark.parametrize(
    "config_text,status",
    [
        (None, "NOT_EVALUATED"),
        ("limits:\n  temperature:\n    max_c: 50\n", "PASS"),
        ("limits:\n  temperature:\n    max_c: 40\n", "FAIL"),
        (
            "schema_version: 7\nfailure_models:\n  max_gap_s: 2\n  sustained_imbalance:\n    max_delta_v: 1\n    duration_s: 2\n",
            "PASS",
        ),
        (
            "schema_version: 7\nfailure_models:\n  max_gap_s: 2\n  sustained_imbalance:\n    max_delta_v: 0\n    duration_s: 2\n",
            "FAIL",
        ),
        (
            "schema_version: 7\nfailure_models:\n  max_gap_s: 2\n  sustained_imbalance:\n    max_delta_v: 1\n    duration_s: 99\n",
            "NOT_EVALUATED",
        ),
    ],
)
def test_real_analysis_ui_stays_responsive_and_opens_report(
    ui, tmp_path, monkeypatch, config_text, status
):
    from batterylog import desktop_ui

    sample = Path(__file__).parents[1] / "examples/sample_battery_log.csv"
    ui.measurement.set(str(sample))
    ui.output.set(str(tmp_path))
    if config_text is not None:
        config = tmp_path / "validation.yaml"
        config.write_text(config_text, encoding="utf-8")
        ui.config.set(str(config))
    ui.run_button.invoke()
    assert ui.run_button.instate(["disabled"])
    assert ui.demo_button.instate(["disabled"])
    assert ui.open_button.instate(["disabled"])
    ticks = []
    ui.root.after(1, lambda: ticks.append(True))
    deadline = time.monotonic() + 30
    while ui.job is not None and time.monotonic() < deadline:
        ui.root.update()
        time.sleep(0.02)
    assert ui.job is None
    assert ticks
    assert ui.status.get().startswith(f"{status}\n")
    assert ui.run_button.instate(["!disabled"])
    assert ui.demo_button.instate(["!disabled"])
    assert ui.cancel_button.instate(["disabled"])
    assert ui.open_button.instate(["!disabled"])
    opened = []
    monkeypatch.setattr(desktop_ui.webbrowser, "open", lambda uri: opened.append(uri) or True)
    ui.open_button.invoke()
    assert opened == [ui.report.as_uri()]
    ui.report.unlink()
    ui.open_button.invoke()
    assert "no longer available" in ui.status.get()


def test_real_input_inspection_is_responsive_and_requires_no_output_folder(ui):
    sample = Path(__file__).parents[1] / "examples/sample_battery_log.csv"
    ui.measurement.set(str(sample))
    ticks = []
    ui.root.after(1, lambda: ticks.append(True))
    ui.inspect_button.invoke()
    assert ui.inspect_button.instate(["disabled"])
    assert ui.run_button.instate(["disabled"])
    deadline = time.monotonic() + 30
    while ui.inspection_job is not None and time.monotonic() < deadline:
        ui.root.update()
        time.sleep(0.02)
    assert ui.inspection_job is None
    assert ticks
    assert ui.status.get().startswith("INSPECTION OK\nCSV · 8 channels")
    assert "timestamp_s → timestamp_s" in ui.status.get()
    assert "current_a" in ui.status.get()
    assert "Metadata only" in ui.status.get()
    assert ui.inspect_button.instate(["!disabled"])
    assert ui.run_button.instate(["!disabled"])
    assert ui.cancel_button.instate(["disabled"])
    assert ui.open_button.instate(["disabled"])
    assert ui.report is None


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize(
    "mode,status", [("unexpected", "FAIL"), ("quiet", "PASS"), ("missing", "NOT_EVALUATED")]
)
def test_real_unloaded_current_ui_and_batch_keep_model_evidence(ui, tmp_path, batch, mode, status):
    import json

    root = Path(__file__).parents[1]
    text = (root / "examples/unloaded_current_demo.csv").read_text(encoding="utf-8")
    if mode == "quiet":
        text = text.replace(",1,1\n", ",0,1\n").replace(",-1.5,1\n", ",0,1\n")
    elif mode == "missing":
        text = "\n".join(line.rsplit(",", 1)[0] for line in text.splitlines()) + "\n"
    source = tmp_path / "inputs"
    source.mkdir()
    measurement = source / "measurement.csv"
    measurement.write_text(text, encoding="utf-8")
    output = tmp_path / "outputs"
    output.mkdir()
    if batch:
        ui.batch_mode_button.invoke()
    ui.measurement.set(str(source if batch else measurement))
    ui.config.set(str(root / "examples/unloaded_current.example.yaml"))
    ui.output.set(str(output))
    ui.run_button.invoke()
    ticks = []
    ui.root.after(1, lambda: ticks.append(True))
    deadline = time.monotonic() + 30
    while (ui.batch_job if batch else ui.job) is not None and time.monotonic() < deadline:
        ui.root.update()
        time.sleep(0.02)
    assert ui.batch_job is None and ui.job is None
    assert ticks and ui.status.get().startswith(f"{status}\n")
    results = list(output.rglob("result.json"))
    assert len(results) == 1
    result = json.loads(results[0].read_text(encoding="utf-8"))
    item = result["failure_models"]["evaluations"][0]
    assert item["code"] == "CURRENT_WHILE_UNLOADED" and item["status"] == status
    assert len(item["events"]) == (1 if mode == "unexpected" else 0)
    if batch:
        import csv

        summaries = list(output.rglob("summary.csv"))
        assert len(summaries) == 1
        with summaries[0].open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["status"] == status
        assert int(rows[0]["violation_events"]) == len(item["events"])


def test_input_inspection_surfaces_mapping_issue_without_running_analysis(ui, tmp_path):
    broken = tmp_path / "broken.csv"
    broken.write_text("timestamp_s,temp_c\n0,25\n", encoding="utf-8")
    ui.measurement.set(str(broken))
    ui.inspect_button.invoke()
    deadline = time.monotonic() + 30
    while ui.inspection_job is not None and time.monotonic() < deadline:
        ui.root.update()
        time.sleep(0.02)
    assert ui.inspection_job is None
    assert ui.status.get().startswith("INSPECTION ISSUES\n")
    assert "No cell voltage columns found" in ui.status.get()
    assert ui.open_button.instate(["disabled"])


def test_real_batch_ui_is_responsive_recursive_and_shows_summary(ui, tmp_path):
    sample = Path(__file__).parents[1] / "examples/sample_battery_log.csv"
    source = tmp_path / "measurements"
    nested = source / "nested"
    nested.mkdir(parents=True)
    (source / "a.csv").write_bytes(sample.read_bytes())
    (nested / "b.csv").write_bytes(sample.read_bytes())
    output = tmp_path / "results"
    output.mkdir()
    config = tmp_path / "validation.yaml"
    config.write_text("limits:\n  temperature:\n    max_c: 40\n", encoding="utf-8")

    ui.batch_mode_button.invoke()
    assert ui.batch_mode.get()
    assert ui.labels[0].cget("text") == "Input folder"
    assert ui.run_button.cget("text") == "Run batch"
    assert ui.inspect_button.instate(["disabled"])
    assert ui.recursive_button.instate(["!disabled"])
    ui.measurement.set(str(source))
    ui.config.set(str(config))
    ui.output.set(str(output))
    ui.recursive.set(True)

    ticks = []
    ui.root.after(1, lambda: ticks.append(True))
    ui.run_button.invoke()
    assert ui.batch_job is not None
    assert ui.batch_mode_button.instate(["disabled"])
    assert ui.recursive_button.instate(["disabled"])
    deadline = time.monotonic() + 30
    while ui.batch_job is not None and time.monotonic() < deadline:
        ui.root.update()
        time.sleep(0.02)
    assert ui.batch_job is None
    assert ticks
    assert ui.status.get().startswith("FAIL\nBatch completed: 2 files; 0 PASS, 2 FAIL")
    assert "summary.csv" in ui.status.get()
    assert len(list(output.glob("batterylog-batch-*"))) == 1
    assert ui.batch_mode_button.instate(["!disabled"])
    assert ui.recursive_button.instate(["!disabled"])
    assert ui.inspect_button.instate(["disabled"])
    assert ui.cancel_button.instate(["disabled"])
    assert ui.open_button.instate(["disabled"])

    ui.batch_mode_button.invoke()
    assert not ui.batch_mode.get()
    assert ui.labels[0].cget("text") == "Measurement"
    assert ui.run_button.cget("text") == "Run analysis"
    assert ui.inspect_button.instate(["!disabled"])
    assert ui.recursive_button.instate(["disabled"])


def test_invalid_input_can_be_corrected_and_stale_report_is_disabled(ui, tmp_path):
    ui.report = tmp_path / "old.html"
    ui.open_button.configure(state="normal")
    ui.start()
    assert ui.status.get().startswith("ERROR\n")
    assert ui.open_button.instate(["disabled"])
    assert ui.job is None
    ui.measurement.set(str(tmp_path / "missing.csv"))
    ui.output.set(str(tmp_path))
    ui.start()
    assert ui.status.get().startswith("ERROR\n")
    assert ui.run_button.instate(["!disabled"])


def test_browse_cancel_preserves_selection_and_each_picker_uses_correct_field(ui, monkeypatch):
    from batterylog import desktop_ui

    selected = iter(["", "/measurement.csv", "/validation.yaml"])
    monkeypatch.setattr(desktop_ui.filedialog, "askopenfilename", lambda **kwargs: next(selected))
    monkeypatch.setattr(desktop_ui.filedialog, "askdirectory", lambda **kwargs: "/results")
    ui.measurement.set("previous.csv")
    ui.browse(1)
    assert ui.measurement.get() == "previous.csv"
    ui.browse(1)
    ui.browse(2)
    ui.browse(3)
    assert (ui.measurement.get(), ui.config.get(), ui.output.get()) == (
        "/measurement.csv",
        "/validation.yaml",
        "/results",
    )


def test_close_with_active_job_can_be_declined_or_cancelled(ui, monkeypatch):
    from batterylog import desktop_ui
    from batterylog.desktop_job import DesktopOutcome

    class Job:
        cancelled = False

        def cancel(self):
            self.cancelled = True

        def poll(self):
            return DesktopOutcome("CANCELLED", "Cancelled") if self.cancelled else None

    job = Job()
    ui.job = job
    ui.start()  # A second run must not replace the active process.
    assert ui.job is job
    monkeypatch.setattr(desktop_ui.messagebox, "askyesno", lambda *a, **kw: False)
    ui.close()
    assert not job.cancelled and not ui.closing
    ui.poll()
    monkeypatch.setattr(desktop_ui.messagebox, "askyesno", lambda *a, **kw: True)
    ui.close()
    assert job.cancelled and ui.closing
    ui.poll()
    assert ui.job is None


def test_browser_failure_shows_manual_path(ui, tmp_path, monkeypatch):
    from batterylog import desktop_ui

    ui.report = tmp_path / "report.html"
    ui.report.touch()
    monkeypatch.setattr(desktop_ui.webbrowser, "open", lambda uri: False)
    ui.open_report()
    assert "manually" in ui.status.get()
    assert str(ui.report) in ui.status.get()
    ui.report = None
    ui.open_report()
    ui.close()


def test_launch_handles_headless_session(monkeypatch, capsys):
    from batterylog import desktop_ui

    def fail():
        raise desktop_ui.tk.TclError("no display")

    monkeypatch.setattr(desktop_ui.tk, "Tk", fail)
    assert desktop_ui.launch() == 4
    assert "graphical session" in capsys.readouterr().err


def test_launch_enters_real_event_loop(monkeypatch):
    from batterylog import desktop_ui

    tk = pytest.importorskip("tkinter")
    original = tk.Tk

    def closing_root():
        try:
            root = original()
        except tk.TclError as exc:
            pytest.skip(str(exc))
        root.after(10, root.destroy)
        return root

    monkeypatch.setattr(tk, "Tk", closing_root)
    assert desktop_ui.launch() == 0


def test_cancel_button_stops_real_process_and_restores_form(ui, tmp_path, monkeypatch):
    import subprocess
    import sys

    from batterylog import desktop_job

    original = subprocess.Popen

    def waiting_worker(command, **kwargs):
        return original([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)

    monkeypatch.setattr(desktop_job.subprocess, "Popen", waiting_worker)
    ui.measurement.set(str(Path(__file__).parents[1] / "examples/sample_battery_log.csv"))
    ui.output.set(str(tmp_path))
    ui.start()
    directory = ui.job.directory
    ui.cancel_button.invoke()
    deadline = time.monotonic() + 5
    while ui.job is not None and time.monotonic() < deadline:
        ui.root.update()
        time.sleep(0.02)
    assert ui.job is None
    assert ui.status.get().startswith("CANCELLED\n")
    assert ui.run_button.instate(["!disabled"])
    assert ui.open_button.instate(["disabled"])
    assert all(widget.instate(["!disabled"]) for widget in ui.inputs)
    assert not directory.exists()


def test_worker_error_allows_retry_with_corrected_measurement(ui, tmp_path):
    broken = tmp_path / "broken.csv"
    broken.write_text("timestamp_s,temp_c\n0,25\n")
    ui.measurement.set(str(broken))
    ui.output.set(str(tmp_path))
    for source, status in [
        (broken, "ERROR"),
        (Path(__file__).parents[1] / "examples/sample_battery_log.csv", "NOT_EVALUATED"),
    ]:
        ui.measurement.set(str(source))
        ui.run_button.invoke()
        deadline = time.monotonic() + 30
        while ui.job is not None and time.monotonic() < deadline:
            ui.root.update()
            time.sleep(0.02)
        assert ui.job is None
        assert ui.status.get().startswith(f"{status}\n")
        assert ui.run_button.instate(["!disabled"])
    assert ui.report and ui.report.is_file()
    assert len(list(tmp_path.glob("batterylog-*"))) == 1


def test_browsed_long_path_keeps_filename_visible(ui, monkeypatch):
    from batterylog import desktop_ui

    selected = "/" + "long-directory/" * 20 + "measurement.csv"
    monkeypatch.setattr(desktop_ui.filedialog, "askopenfilename", lambda **kwargs: selected)
    ui.root.geometry("860x420")
    ui.root.deiconify()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        ui.root.update()
        if ui.entries[0].winfo_ismapped() and ui.entries[0].winfo_width() > 1:
            break
        time.sleep(0.01)
    assert ui.entries[0].winfo_ismapped()
    assert ui.entries[0].winfo_width() > 1
    ui.browse(1)
    ui.root.update()
    entry = ui.entries[0]
    assert ui.measurement.get() == selected
    assert entry.index("insert") == len(selected)
    assert entry.xview()[1] == 1.0


def test_close_keeps_cleanup_error_visible(ui):
    from batterylog.desktop_job import DesktopOutcome

    class FailedCleanup:
        def poll(self):
            return DesktopOutcome("ERROR", "Cleanup failed for /output/run: access denied")

    ui.job = FailedCleanup()
    ui.closing = True
    ui.poll()
    assert ui.job is None
    assert not ui.closing
    assert ui.root.winfo_exists()
    assert "Cleanup failed for /output/run" in ui.status.get()
    assert ui.run_button.instate(["!disabled"])
    assert ui.open_button.instate(["disabled"])


def test_demo_load_runs_and_opens_real_report(ui, tmp_path, monkeypatch):
    import json

    from batterylog import desktop_ui

    monkeypatch.setattr(desktop_ui.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))
    ui.report = tmp_path / "old-report.html"
    ui.open_button.configure(state="normal")
    ui.demo_button.invoke()
    assert ui.status.get().startswith("DEMO READY")
    assert "FAIL is expected" in ui.status.get()
    assert "illustrative limits" in ui.status.get()
    assert ui.report is None
    assert ui.open_button.instate(["disabled"])
    source = Path(ui.measurement.get())
    assert source.is_file()
    assert source.parent == Path(ui.output.get())
    ui.run_button.invoke()
    ui.load_demo()  # Must not replace inputs while analysis owns the form.
    assert Path(ui.measurement.get()) == source
    deadline = time.monotonic() + 30
    while ui.job is not None and time.monotonic() < deadline:
        ui.root.update()
        time.sleep(0.02)
    assert ui.job is None
    assert ui.status.get().startswith("FAIL\n")
    result = json.loads(ui.report.with_name("result.json").read_text(encoding="utf-8"))
    assert len(result["violations"]) == 2
    opened = []
    monkeypatch.setattr(desktop_ui.webbrowser, "open", lambda uri: opened.append(uri) or True)
    ui.open_button.invoke()
    assert opened == [ui.report.as_uri()]
    assert ui.demo_button.instate(["!disabled"])


def test_cancelled_demo_picker_preserves_form_and_report(ui, tmp_path, monkeypatch):
    from batterylog import desktop_ui

    monkeypatch.setattr(desktop_ui.filedialog, "askdirectory", lambda **kwargs: "")
    ui.measurement.set("existing.csv")
    ui.config.set("existing.yaml")
    ui.output.set(str(tmp_path))
    ui.report = tmp_path / "report.html"
    ui.open_button.configure(state="normal")
    status = ui.status.get()
    ui.demo_button.invoke()
    assert (ui.measurement.get(), ui.config.get(), ui.output.get()) == (
        "existing.csv",
        "existing.yaml",
        str(tmp_path),
    )
    assert ui.report == tmp_path / "report.html"
    assert ui.open_button.instate(["!disabled"])
    assert ui.status.get() == status
    assert list(tmp_path.iterdir()) == []


def test_demo_creation_error_preserves_current_selection(ui, tmp_path, monkeypatch):
    from batterylog import desktop_ui

    monkeypatch.setattr(desktop_ui.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))

    def fail(*args):
        raise OSError("cannot create demo")

    monkeypatch.setattr(desktop_ui, "create_demo", fail)
    ui.measurement.set("existing.csv")
    ui.demo_button.invoke()
    assert ui.status.get() == "ERROR\ncannot create demo"
    assert ui.measurement.get() == "existing.csv"
    assert ui.run_button.instate(["!disabled"])
    assert ui.demo_button.instate(["!disabled"])


def wait_for_batch(ui):
    deadline = time.monotonic() + 30
    while (
        ui.batch_job is not None or ui._render_after is not None
    ) and time.monotonic() < deadline:
        ui.root.update()
        time.sleep(0.01)
    assert ui.batch_job is None and ui._render_after is None
    ui.root.update()


def select_batch_file(ui, source):
    selected = next(
        item
        for item in ui.batch_tree.get_children()
        if ui.batch_tree.item(item, "values")[0] == source
    )
    ui.batch_tree.selection_set(selected)
    ui.root.update()
    return selected


def test_batch_result_table_opens_report_shows_errors_and_clears_on_retry(
    ui, tmp_path, monkeypatch
):
    from batterylog import desktop_ui

    source = tmp_path / "input"
    source.mkdir()
    sample = Path(__file__).parents[1] / "examples/sample_battery_log.csv"
    good = source / "ölçüm, one.csv"
    good.write_bytes(sample.read_bytes())
    broken = source / "broken.csv"
    broken.write_text("timestamp_s,temp_c\n0,25\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    ui.batch_mode_button.invoke()
    ui.measurement.set(str(source))
    ui.output.set(str(output))
    ui.run_button.invoke()
    assert ui.open_folder_button.instate(["disabled"])
    wait_for_batch(ui)

    assert ui.status.get().startswith("ERROR\nBatch completed: 2 files")
    assert {row.source: row.status for row in ui.batch_rows} == {
        "broken.csv": "ERROR",
        "ölçüm, one.csv": "NOT_EVALUATED",
    }
    select_batch_file(ui, "broken.csv")
    assert "No cell voltage columns found" in ui.status.get()
    assert "Violation events: Unknown" in ui.status.get()
    assert ui.open_button.instate(["disabled"])
    select_batch_file(ui, "ölçüm, one.csv")
    assert ui.open_button.instate(["!disabled"])
    opened = []
    monkeypatch.setattr(desktop_ui.webbrowser, "open", lambda uri: opened.append(uri) or True)
    ui.open_button.invoke()
    assert opened == [ui.report.as_uri()]
    first_report = ui.report
    first_directory = ui.output_directory
    folders = []
    with monkeypatch.context() as opener:
        if os.name == "nt":
            opener.setattr(desktop_ui.os, "startfile", lambda path: folders.append(path))
        else:
            opener.setattr(
                desktop_ui.subprocess, "Popen", lambda command, **kw: folders.append(command[-1])
            )
        ui.open_folder_button.invoke()
    assert folders == [str(first_directory)]

    # A fresh invalid-config run must not retain rows or actions from the first run.
    config = tmp_path / "invalid.yaml"
    config.write_text("limits: [invalid]\n", encoding="utf-8")
    ui.config.set(str(config))
    ui.run_button.invoke()
    assert ui.batch_tree.get_children() == ()
    assert ui.report is None
    assert ui.open_button.instate(["disabled"])
    assert ui.open_folder_button.instate(["disabled"])
    wait_for_batch(ui)
    assert ui.status.get().startswith("ERROR\n")
    assert ui.batch_rows == []
    assert ui.open_folder_button.instate(["disabled"])
    assert first_report.is_file()
    assert first_directory.is_dir()


def test_cancelled_batch_table_uses_real_finalized_csv_and_preserves_report(
    ui, tmp_path, monkeypatch
):
    import subprocess
    import sys

    from batterylog import desktop_job

    source = tmp_path / "input"
    source.mkdir()
    sample = Path(__file__).parents[1] / "examples/sample_battery_log.csv"
    (source / "a.csv").write_bytes(sample.read_bytes())
    (source / "b.csv").write_bytes(sample.read_bytes())
    output = tmp_path / "output"
    output.mkdir()
    ready = tmp_path / "ready"
    original = subprocess.Popen

    def delayed_worker(command, **kwargs):
        child = (
            "import runpy,sys,time\nfrom pathlib import Path\n"
            "import batterylog.batch as batch\n"
            "original = batch._analyze_file\n"
            "def delayed(source, *args):\n"
            "    if source.name == 'b.csv':\n"
            f"        Path({str(ready)!r}).touch()\n"
            "        while True: time.sleep(0.01)\n"
            "    return original(source, *args)\n"
            "batch._analyze_file = delayed\n"
            f"sys.argv = ['batterylog', *{command[3:]!r}]\n"
            f"runpy.run_module({command[2]!r}, run_name='__main__')\n"
        )
        return original([sys.executable, "-c", child], **kwargs)

    monkeypatch.setattr(desktop_job.subprocess, "Popen", delayed_worker)
    ui.batch_mode_button.invoke()
    ui.measurement.set(str(source))
    ui.output.set(str(output))
    ui.run_button.invoke()
    deadline = time.monotonic() + 15
    while not ready.exists() and time.monotonic() < deadline:
        ui.root.update()
        time.sleep(0.01)
    assert ready.exists()
    directory = ui.batch_job.directory
    before = (directory / "files/a.csv/report.html").read_bytes()
    ui.cancel_button.invoke()
    wait_for_batch(ui)
    assert ui.status.get().startswith("CANCELLED\n")
    assert [(row.source, row.status) for row in ui.batch_rows] == [
        ("a.csv", "NOT_EVALUATED"),
        ("b.csv", "NOT_PROCESSED"),
    ]
    pending = select_batch_file(ui, "b.csv")
    assert ui.batch_tree.item(pending, "values")[2] == "—"
    assert ui.open_button.instate(["disabled"])
    select_batch_file(ui, "a.csv")
    assert ui.open_button.instate(["!disabled"])
    assert ui.report.read_bytes() == before
    assert ui.open_folder_button.instate(["!disabled"])
    ui.batch_mode_button.invoke()
    assert not ui.batch_tree.get_children()
    assert ui.report is None and ui.output_directory is None


def test_large_batch_table_yields_to_tk_and_pending_render_can_be_replaced(ui, tmp_path):
    from batterylog.batch import _pending_summary
    from batterylog.desktop_job import DesktopBatchOutcome

    files = [_pending_summary(f"file-{index:05}.csv") for index in range(10000)]
    outcome = DesktopBatchOutcome(
        "CANCELLED",
        "Retained summary",
        tmp_path,
        {
            "batch_schema_version": 1,
            "config_sha256": None,
            "summary_csv": "summary.csv",
            "files": files,
        },
    )
    ticks = []
    ui.root.after(0, lambda: ticks.append(len(ui.batch_tree.get_children())))
    ui._show_batch_results(outcome, "CANCELLED\n10000 files")
    assert 0 < len(ui.batch_tree.get_children()) < len(files)
    ui.root.update()
    assert ticks and ticks[0] < len(files)
    deadline = time.monotonic() + 10
    while ui._render_after is not None and time.monotonic() < deadline:
        ui.root.update()
        time.sleep(0.001)
    assert ui._render_after is None
    assert len(ui.batch_tree.get_children()) == len(files)
    assert ui.batch_tree.item("9999", "values") == ("file-09999.csv", "NOT_PROCESSED", "—")

    ui._show_batch_results(outcome, "CANCELLED\nold run")
    assert ui._render_after is not None
    ui._clear_results()
    assert ui._render_after is None
    ui.root.update()
    assert ui.batch_tree.get_children() == ()
    assert ui.report is None and ui.output_directory is None


def test_deleted_output_folder_shows_manual_path_and_disables_opener(ui, tmp_path):
    directory = tmp_path / "deleted-output"
    directory.mkdir()
    ui.output_directory = directory
    ui.open_folder_button.configure(state="normal")
    directory.rmdir()
    ui.open_folder_button.invoke()
    assert "no longer available" in ui.status.get()
    assert str(directory) in ui.status.get()
    assert ui.open_folder_button.instate(["disabled"])
