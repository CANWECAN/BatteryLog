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
    if window.job is not None:
        window.job.cancel()
        deadline = time.monotonic() + 5
        while window.job.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.mark.parametrize("limit,status", [(None, "NOT_EVALUATED"), (50, "PASS"), (40, "FAIL")])
def test_real_analysis_ui_stays_responsive_and_opens_report(
    ui, tmp_path, monkeypatch, limit, status
):
    from batterylog import desktop_ui

    sample = Path(__file__).parents[1] / "examples/sample_battery_log.csv"
    ui.measurement.set(str(sample))
    ui.output.set(str(tmp_path))
    if limit is not None:
        config = tmp_path / "validation.yaml"
        config.write_text(f"limits:\n  temperature:\n    max_c: {limit}\n")
        ui.config.set(str(config))
    ui.run_button.invoke()
    assert ui.run_button.instate(["disabled"])
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
    assert ui.cancel_button.instate(["disabled"])
    assert ui.open_button.instate(["!disabled"])
    opened = []
    monkeypatch.setattr(desktop_ui.webbrowser, "open", lambda uri: opened.append(uri) or True)
    ui.open_button.invoke()
    assert opened == [ui.report.as_uri()]
    ui.report.unlink()
    ui.open_button.invoke()
    assert "no longer available" in ui.status.get()


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
    ui.root.deiconify()
    ui.root.update_idletasks()
    ui.browse(1)
    ui.root.update_idletasks()
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
