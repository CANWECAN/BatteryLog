"""Small native single-file launcher; all analysis runs in the existing CLI."""

import sys
import tkinter as tk
import webbrowser
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .desktop_demo import create_demo
from .desktop_job import DesktopJob


class DesktopWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.job: DesktopJob | None = None
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
            text="Without configured limits, the result is NOT_EVALUATED. No default limits are added.",
            wraplength=610,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 14))
        actions = ttk.Frame(frame)
        actions.grid(row=5, column=0, columnspan=3, sticky="w")
        self.run_button = ttk.Button(actions, text="Run analysis", command=self.start)
        self.run_button.grid(row=0, column=0)
        self.cancel_button = ttk.Button(
            actions, text="Cancel", command=self.cancel, state="disabled"
        )
        self.cancel_button.grid(row=0, column=1, padx=8)
        self.open_button = ttk.Button(
            actions, text="Open report", command=self.open_report, state="disabled"
        )
        self.open_button.grid(row=0, column=2)
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
        if self.job is not None:
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

    def start(self) -> None:
        if self.job is not None:
            return
        self.report = None
        self.open_button.configure(state="disabled")
        try:
            if not self.measurement.get().strip() or not self.output.get().strip():
                raise ValueError("Select a measurement and an existing output folder.")
            config = self.config.get()
            self.job = DesktopJob(
                Path(self.measurement.get()),
                Path(self.output.get()),
                Path(config) if config else None,
            )
        except (OSError, ValueError) as exc:
            self.set_status(f"ERROR\n{exc}")
            return
        for widget in [*self.inputs, self.demo_button, self.run_button]:
            widget.configure(state="disabled")
        self.cancel_button.configure(state="normal")
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
        for widget in [*self.inputs, self.demo_button, self.run_button]:
            widget.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.open_button.configure(state="normal" if self.report else "disabled")

    def cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.cancel_button.configure(state="disabled")
            self.set_status("Cancelling analysis…")

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
        if self.job is not None:
            if not messagebox.askyesno(
                "Cancel analysis?", "Cancel the active analysis and close?", parent=self.root
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
