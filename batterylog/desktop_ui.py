"""Small native single-file launcher; all analysis runs in the existing CLI."""

import sys
import tkinter as tk
import webbrowser
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .desktop_demo import create_demo
from .desktop_job import DesktopInspectionJob, DesktopJob
from .inspection import InspectionResult


class DesktopWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.job: DesktopJob | None = None
        self.inspection_job: DesktopInspectionJob | None = None
        self.report: Path | None = None
        self.closing = False
        root.title("BatteryLog — single-file analysis")
        root.minsize(680, 390)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=20)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=1)
        ttk.Label(frame, text="BatteryLog", font=("TkDefaultFont", 18, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 14)
        )
        self.demo_button = ttk.Button(frame, text="Try demo…", command=self.load_demo)
        self.demo_button.grid(row=0, column=2, sticky="e", pady=(0, 14))
        self.measurement = tk.StringVar(root)
        self.config = tk.StringVar(root)
        self.output = tk.StringVar(root)
        self.inputs: list[ttk.Entry | ttk.Button] = []
        self.entries: list[ttk.Entry] = []
        for row, (label, variable) in enumerate(
            [
                ("Measurement", self.measurement),
                ("YAML configuration (optional)", self.config),
                ("Output location", self.output),
            ],
            start=1,
        ):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12))
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
        self.inspect_button = ttk.Button(actions, text="Inspect input", command=self.inspect_input)
        self.inspect_button.grid(row=0, column=0)
        self.run_button = ttk.Button(actions, text="Run analysis", command=self.start)
        self.run_button.grid(row=0, column=1, padx=(8, 0))
        self.cancel_button = ttk.Button(
            actions, text="Cancel", command=self.cancel, state="disabled"
        )
        self.cancel_button.grid(row=0, column=2, padx=8)
        self.open_button = ttk.Button(
            actions, text="Open report", command=self.open_report, state="disabled"
        )
        self.open_button.grid(row=0, column=3)
        self.status = tk.StringVar(
            root, "Ready — select a measurement and an existing output folder."
        )
        self.details = tk.Text(frame, height=6, wrap="word", state="disabled", takefocus=True)
        self.details.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(14, 0))
        scrollbar = ttk.Scrollbar(frame, command=self.details.yview)
        scrollbar.grid(row=6, column=3, sticky="ns", pady=(14, 0))
        self.details.configure(yscrollcommand=scrollbar.set)
        self.set_status(self.status.get())

    def load_demo(self) -> None:
        if self.job is not None or self.inspection_job is not None:
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
        if row == 1:
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
        for widget in [*self.inputs, self.demo_button, self.inspect_button, self.run_button]:
            widget.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")

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
        if self.job is not None or self.inspection_job is not None:
            return
        self.report = None
        self.open_button.configure(state="disabled")
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
        if self.job is not None or self.inspection_job is not None:
            return
        self.report = None
        self.open_button.configure(state="disabled")
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

    def open_report(self) -> None:
        if self.report is not None:
            try:
                if not self.report.is_file():
                    raise OSError("The report file is no longer available.")
                if not webbrowser.open(self.report.as_uri()):
                    raise OSError(
                        "No browser could be opened. Open the report path shown below manually."
                    )
            except (OSError, webbrowser.Error) as exc:
                self.set_status(f"{exc}\n{self.report}")

    def close(self) -> None:
        if self.job is not None or self.inspection_job is not None:
            if not messagebox.askyesno(
                "Cancel active task?",
                "Cancel the active BatteryLog task and close?",
                parent=self.root,
            ):
                return
            self.closing = True
            self.cancel()
        else:
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
