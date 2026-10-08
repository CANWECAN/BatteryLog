"""Native analysis launcher; measurement processing stays in the existing CLI."""

import os
import subprocess
import sys
import tkinter as tk
import webbrowser
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .desktop_batch_results import DesktopBatchRow, read_batch_rows
from .desktop_demo import create_demo
from .desktop_job import DesktopBatchJob, DesktopBatchOutcome, DesktopInspectionJob, DesktopJob
from .inspection import InspectionResult


class DesktopWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.job: DesktopJob | None = None
        self.inspection_job: DesktopInspectionJob | None = None
        self.batch_job: DesktopBatchJob | None = None
        self.report: Path | None = None
        self.output_directory: Path | None = None
        self.batch_rows: list[DesktopBatchRow] = []
        self._batch_message = ""
        self._render_after: str | None = None
        self._next_row = 0
        self.closing = False
        root.title("BatteryLog — analysis launcher")
        root.minsize(680, 390)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=20)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=2)
        frame.rowconfigure(7, weight=1)
        ttk.Label(frame, text="BatteryLog", font=("TkDefaultFont", 18, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 14)
        )
        self.demo_button = ttk.Button(frame, text="Try demo…", command=self.load_demo)
        self.demo_button.grid(row=0, column=2, sticky="e", pady=(0, 14))
        self.measurement = tk.StringVar(root)
        self.config = tk.StringVar(root)
        self.output = tk.StringVar(root)
        self.batch_mode = tk.BooleanVar(root, False)
        self.recursive = tk.BooleanVar(root, False)
        self.inputs: list[ttk.Entry | ttk.Button] = []
        self.entries: list[ttk.Entry] = []
        self.labels: list[ttk.Label] = []
        for row, (label, variable) in enumerate(
            [
                ("Measurement", self.measurement),
                ("YAML configuration (optional)", self.config),
                ("Output location", self.output),
            ],
            start=1,
        ):
            label_widget = ttk.Label(frame, text=label)
            label_widget.grid(row=row, column=0, sticky="w", padx=(0, 12))
            self.labels.append(label_widget)
            entry = ttk.Entry(frame, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            button = ttk.Button(frame, text="Browse…", command=partial(self.browse, row))
            button.grid(row=row, column=2, padx=(8, 0))
            self.inputs.extend([entry, button])
            self.entries.append(entry)
        ttk.Label(
            frame,
            text="Without configured validation rules, the result is NOT_EVALUATED. "
            "The launcher adds no validation rules.",
            wraplength=610,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 14))
        actions = ttk.Frame(frame)
        actions.grid(row=5, column=0, columnspan=3, sticky="w")
        self.batch_mode_button = ttk.Checkbutton(
            actions, text="Batch folder", variable=self.batch_mode, command=self._mode_changed
        )
        self.batch_mode_button.grid(row=0, column=0, sticky="w")
        self.recursive_button = ttk.Checkbutton(
            actions, text="Recursive", variable=self.recursive, state="disabled"
        )
        self.recursive_button.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.inspect_button = ttk.Button(actions, text="Inspect input", command=self.inspect_input)
        self.inspect_button.grid(row=1, column=0, pady=(8, 0))
        self.run_button = ttk.Button(actions, text="Run analysis", command=self.start)
        self.run_button.grid(row=1, column=1, padx=(8, 0), pady=(8, 0))
        self.cancel_button = ttk.Button(
            actions, text="Cancel", command=self.cancel, state="disabled"
        )
        self.cancel_button.grid(row=1, column=2, padx=8, pady=(8, 0))
        self.open_button = ttk.Button(
            actions, text="Open report", command=self.open_report, state="disabled"
        )
        self.open_button.grid(row=1, column=3, pady=(8, 0))
        self.open_folder_button = ttk.Button(
            actions, text="Open output folder", command=self.open_output_folder, state="disabled"
        )
        self.open_folder_button.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.batch_results_frame = ttk.Frame(frame)
        self.batch_results_frame.grid(row=6, column=0, columnspan=4, sticky="nsew", pady=(14, 0))
        self.batch_results_frame.columnconfigure(0, weight=1)
        self.batch_results_frame.rowconfigure(1, weight=1)
        ttk.Label(
            self.batch_results_frame,
            text="Select a file to view its details and open the completed report.",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.batch_tree = ttk.Treeview(
            self.batch_results_frame,
            columns=("source", "status", "events"),
            show="headings",
            selectmode="browse",
            height=8,
        )
        for name, title, width in [
            ("source", "File", 380),
            ("status", "Outcome", 155),
            ("events", "Violation events", 110),
        ]:
            self.batch_tree.heading(name, text=title)
            self.batch_tree.column(name, width=width, minwidth=80, stretch=name == "source")
        self.batch_tree.grid(row=1, column=0, sticky="nsew")
        batch_scroll = ttk.Scrollbar(
            self.batch_results_frame, orient="vertical", command=self.batch_tree.yview
        )
        batch_scroll.grid(row=1, column=1, sticky="ns")
        batch_horizontal = ttk.Scrollbar(
            self.batch_results_frame, orient="horizontal", command=self.batch_tree.xview
        )
        batch_horizontal.grid(row=2, column=0, sticky="ew")
        self.batch_tree.configure(
            yscrollcommand=batch_scroll.set, xscrollcommand=batch_horizontal.set
        )
        self.batch_tree.bind("<<TreeviewSelect>>", self.select_batch_row)
        self.batch_results_frame.grid_remove()
        self.status = tk.StringVar(
            root, "Ready — select a measurement and an existing output folder."
        )
        self.details = tk.Text(frame, height=6, wrap="word", state="disabled", takefocus=True)
        self.details.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(14, 0))
        scrollbar = ttk.Scrollbar(frame, command=self.details.yview)
        scrollbar.grid(row=7, column=3, sticky="ns", pady=(14, 0))
        self.details.configure(yscrollcommand=scrollbar.set)
        self.set_status(self.status.get())

    def _clear_results(self) -> None:
        if self._render_after is not None:
            self.root.after_cancel(self._render_after)
            self._render_after = None
        self.batch_rows = []
        self._next_row = 0
        self._batch_message = ""
        children = self.batch_tree.get_children()
        if children:
            self.batch_tree.delete(*children)
        self.batch_results_frame.grid_remove()
        self.root.minsize(680, 390)
        self.report = None
        self.output_directory = None
        self.open_button.configure(state="disabled")
        self.open_folder_button.configure(state="disabled")

    def _fill_batch_table(self) -> None:
        self._render_after = None
        end = min(self._next_row + 100, len(self.batch_rows))
        for index in range(self._next_row, end):
            row = self.batch_rows[index]
            self.batch_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    row.source,
                    row.status,
                    row.violation_events if row.violation_events is not None else "—",
                ),
            )
        self._next_row = end
        if end < len(self.batch_rows):
            self._render_after = self.root.after(1, self._fill_batch_table)

    def _show_batch_results(self, outcome: DesktopBatchOutcome, message: str) -> None:
        self._clear_results()
        if outcome.output_directory.is_dir():
            self.output_directory = outcome.output_directory
            self.open_folder_button.configure(state="normal")
        try:
            self.batch_rows = read_batch_rows(outcome)
        except OSError as exc:
            message = f"ERROR\nCannot display batch results: {exc}\n{message}"
        self._batch_message = message
        self.set_status(message)
        if self.batch_rows:
            self.batch_results_frame.grid()
            self.root.minsize(760, 620)
            self._fill_batch_table()

    def select_batch_row(self, event: tk.Event | None = None) -> None:
        if not self._batch_message or self.batch_job is not None:
            return
        self.report = None
        self.open_button.configure(state="disabled")
        selected = self.batch_tree.selection()
        if not selected:
            self.set_status(self._batch_message)
            return
        row = self.batch_rows[int(selected[0])]
        count = str(row.violation_events) if row.violation_events is not None else "Unknown"
        details = f"File: {row.source}\nOutcome: {row.status}\nViolation events: {count}"
        if row.error:
            details += f"\nError: {row.error}"
        if row.report is not None and row.report.is_file():
            self.report = row.report
            self.open_button.configure(state="normal")
            details += f"\nReport: {row.report}"
        else:
            details += "\nNo completed report is available for this file."
        self.set_status(f"{details}\n\n{self._batch_message}")

    def open_output_folder(self) -> None:
        if self.output_directory is None:
            return
        directory = self.output_directory
        try:
            if not directory.is_dir():
                self.open_folder_button.configure(state="disabled")
                raise OSError("The output folder is no longer available.")
            if sys.platform == "win32":
                os.startfile(str(directory))
            else:
                subprocess.Popen(
                    ["open" if sys.platform == "darwin" else "xdg-open", str(directory)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except OSError as exc:
            self.set_status(f"{exc}\nOpen this folder manually: {directory}")

    def _apply_mode(self, *, clear_measurement: bool) -> None:
        batch = self.batch_mode.get()
        if clear_measurement:
            self.measurement.set("")
        if not batch:
            self.recursive.set(False)
        self.labels[0].configure(text="Input folder" if batch else "Measurement")
        self.run_button.configure(text="Run batch" if batch else "Run analysis")
        self.inspect_button.configure(state="disabled" if batch else "normal")
        self.recursive_button.configure(state="normal" if batch else "disabled")
        self.open_button.configure(text="Open selected report" if batch else "Open report")
        self._clear_results()

    def _mode_changed(self) -> None:
        self._apply_mode(clear_measurement=True)
        self.set_status(
            "Batch mode — select an input folder and an output location."
            if self.batch_mode.get()
            else "Ready — select a measurement and an existing output folder."
        )

    def load_demo(self) -> None:
        if self.job is not None or self.inspection_job is not None or self.batch_job is not None:
            return
        selected = filedialog.askdirectory(
            parent=self.root, title="Choose where to save the demo", mustexist=True
        )
        if not selected:
            return
        try:
            directory = create_demo(Path(selected))
        except (OSError, ValueError) as exc:
            self.set_status(f"ERROR\n{exc}")
            return
        self.batch_mode.set(False)
        self._apply_mode(clear_measurement=False)
        self.measurement.set(str(directory / "synthetic_demo.csv"))
        self.config.set(str(directory / "validation.yaml"))
        self.output.set(str(directory))
        for entry in self.entries:
            entry.icursor(tk.END)
            entry.xview_moveto(1.0)
        self.report = None
        self.open_button.configure(state="disabled")
        self.set_status(
            "DEMO READY — synthetic data, illustrative limits only.\n"
            "Select Run analysis, then Open report. FAIL is expected: the final sample has "
            "48 °C above the 45 °C limit and a 100 mV cell spread above the 80 mV limit.\n"
            f"Demo files: {directory}"
        )

    def set_status(self, message: str) -> None:
        self.status.set(message)
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", message)
        self.details.configure(state="disabled")

    def browse(self, row: int) -> None:
        if row == 1 and self.batch_mode.get():
            selected = filedialog.askdirectory(
                parent=self.root, title="Select batch input folder", mustexist=True
            )
            variable = self.measurement
        elif row == 1:
            selected = filedialog.askopenfilename(
                parent=self.root,
                title="Select measurement",
                filetypes=[
                    ("Measurements", "*.csv *.CSV *.mdf *.MDF *.mf4 *.MF4"),
                    ("All files", "*"),
                ],
            )
            variable = self.measurement
        elif row == 2:
            selected = filedialog.askopenfilename(
                parent=self.root,
                title="Select YAML configuration",
                filetypes=[
                    ("YAML", "*.yaml *.yml *.YAML *.YML"),
                    ("All files", "*"),
                ],
            )
            variable = self.config
        else:
            selected = filedialog.askdirectory(
                parent=self.root, title="Select output location", mustexist=True
            )
            variable = self.output
        if selected:
            variable.set(selected)
            entry = self.entries[row - 1]
            entry.icursor(tk.END)
            entry.xview_moveto(1.0)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for widget in [
            *self.inputs,
            self.demo_button,
            self.batch_mode_button,
            self.run_button,
        ]:
            widget.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.inspect_button.configure(state="disabled")
            self.recursive_button.configure(state="disabled")
            self.open_button.configure(state="disabled")
            self.open_folder_button.configure(state="disabled")
        else:
            self.inspect_button.configure(state="disabled" if self.batch_mode.get() else "normal")
            self.recursive_button.configure(state="normal" if self.batch_mode.get() else "disabled")

    @staticmethod
    def _inspection_text(result: InspectionResult) -> str:
        channels = result["channels"]
        bindings = result["bindings"]
        lines = [
            f"INSPECTION {result['metadata_status']}",
            f"{result['source_format'].upper()} · {len(channels)} channels · time basis: {result['time_basis']}",
        ]
        if result["issues"]:
            lines.append("Issues:")
            lines.extend(f"- {issue}" for issue in result["issues"])
        if bindings:
            lines.append("Bindings:")
            lines.extend(f"- {item['source']} → {item['canonical']}" for item in bindings)
        lines.append(f"Channels ({len(channels)} total):")
        for channel in channels[:60]:
            suffix = []
            if channel["unit"]:
                suffix.append(channel["unit"])
            if channel["group"] is not None:
                suffix.append(f"group {channel['group']}, index {channel['index']}")
            extra = f" [{'; '.join(suffix)}]" if suffix else ""
            lines.append(f"- {channel['name']}{extra}")
        if len(channels) > 60:
            lines.append(f"… {len(channels) - 60} additional channels not shown")
        lines.append(
            "Metadata only — measurement samples and engineering rules were not evaluated."
        )
        return "\n".join(lines)

    def inspect_input(self) -> None:
        if (
            self.batch_mode.get()
            or self.job is not None
            or self.inspection_job is not None
            or self.batch_job is not None
        ):
            return
        self._clear_results()
        try:
            if not self.measurement.get().strip():
                raise ValueError("Select a measurement before inspection.")
            config = self.config.get().strip()
            self.inspection_job = DesktopInspectionJob(
                Path(self.measurement.get()),
                Path(config) if config else None,
            )
        except (OSError, ValueError) as exc:
            self.set_status(f"ERROR\n{exc}")
            return
        self._set_busy(True)
        self.set_status("Inspecting channel metadata… You can cancel this inspection.")
        self.root.after(100, self.poll_inspection)

    def poll_inspection(self) -> None:
        assert self.inspection_job is not None
        outcome = self.inspection_job.poll()
        if outcome is None:
            self.root.after(100, self.poll_inspection)
            return
        self.inspection_job = None
        if self.closing and outcome.status == "CANCELLED":
            self.root.destroy()
            return
        self.closing = False
        if outcome.inspection is not None:
            self.set_status(self._inspection_text(outcome.inspection))
        else:
            self.set_status(f"{outcome.status}\n{outcome.message}")
        self._set_busy(False)
        self.open_button.configure(state="disabled")

    def start(self) -> None:
        if self.job is not None or self.inspection_job is not None or self.batch_job is not None:
            return
        if self.batch_mode.get():
            self.start_batch()
            return
        self._clear_results()
        try:
            if not self.measurement.get().strip() or not self.output.get().strip():
                raise ValueError("Select a measurement and an existing output folder.")
            config = self.config.get().strip()
            self.job = DesktopJob(
                Path(self.measurement.get()),
                Path(self.output.get()),
                Path(config) if config else None,
            )
        except (OSError, ValueError) as exc:
            self.set_status(f"ERROR\n{exc}")
            return
        self._set_busy(True)
        self.set_status("Running analysis… You can cancel this run.")
        self.root.after(150, self.poll)

    def start_batch(self) -> None:
        if self.job is not None or self.inspection_job is not None or self.batch_job is not None:
            return
        self._clear_results()
        try:
            if not self.measurement.get().strip() or not self.output.get().strip():
                raise ValueError("Select an input folder and an existing output folder.")
            config = self.config.get().strip()
            self.batch_job = DesktopBatchJob(
                Path(self.measurement.get()),
                Path(self.output.get()),
                Path(config) if config else None,
                recursive=self.recursive.get(),
            )
        except (OSError, ValueError) as exc:
            self.set_status(f"ERROR\n{exc}")
            return
        self._set_busy(True)
        self.set_status(
            "Running batch analysis… Completed file reports will be preserved on cancel."
        )
        self.root.after(150, self.poll_batch)

    def poll_batch(self) -> None:
        assert self.batch_job is not None
        outcome = self.batch_job.poll()
        if outcome is None:
            self.root.after(150, self.poll_batch)
            return
        self.batch_job = None
        if self.closing and outcome.status == "CANCELLED":
            self.root.destroy()
            return
        self.closing = False
        message = f"{outcome.status}\n{outcome.message}\nOutput: {outcome.output_directory}"
        if outcome.summary_csv is not None:
            message += f"\nSummary: {outcome.summary_csv}"
        self._set_busy(False)
        self._show_batch_results(outcome, message)

    def poll(self) -> None:
        assert self.job is not None
        outcome = self.job.poll()
        if outcome is None:
            self.root.after(150, self.poll)
            return
        self.job = None
        if self.closing and outcome.status == "CANCELLED":
            self.root.destroy()
            return
        self.closing = False
        self.report = outcome.report
        self.output_directory = self.report.parent if self.report is not None else None
        self.open_folder_button.configure(state="normal" if self.output_directory else "disabled")
        self.set_status(
            f"{outcome.status}\n{outcome.message}" + (f"\n{self.report}" if self.report else "")
        )
        self._set_busy(False)
        self.open_button.configure(state="normal" if self.report else "disabled")

    def cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.cancel_button.configure(state="disabled")
            self.set_status("Cancelling analysis…")
        elif self.inspection_job is not None:
            self.inspection_job.cancel()
            self.cancel_button.configure(state="disabled")
            self.set_status("Cancelling inspection…")
        elif self.batch_job is not None:
            self.batch_job.cancel()
            self.cancel_button.configure(state="disabled")
            self.set_status("Cancelling batch… Completed reports will be preserved.")

    def open_report(self) -> None:
        if self.report is not None:
            try:
                if not self.report.is_file():
                    self.open_button.configure(state="disabled")
                    raise OSError("The report file is no longer available.")
                if self.output_directory is not None and not self.report.resolve().is_relative_to(
                    self.output_directory.resolve()
                ):
                    self.open_button.configure(state="disabled")
                    raise OSError("The report path leaves this output directory.")
                if not webbrowser.open(self.report.as_uri()):
                    raise OSError(
                        "No browser could be opened. Open the report path shown below manually."
                    )
            except (OSError, webbrowser.Error) as exc:
                self.set_status(f"{exc}\n{self.report}")

    def close(self) -> None:
        if self.job is not None or self.inspection_job is not None or self.batch_job is not None:
            if not messagebox.askyesno(
                "Cancel active task?",
                "Cancel the active BatteryLog task and close?",
                parent=self.root,
            ):
                return
            self.closing = True
            self.cancel()
        else:
            self._clear_results()
            self.root.destroy()


def launch() -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"error: Desktop mode requires a graphical session: {exc}", file=sys.stderr)
        return 4
    DesktopWindow(root)
    root.mainloop()
    return 0
