# Desktop launcher (0.11 development)

This is the first single-file GUI workflow in `0.11.0.dev0`. It is not included in the
published v0.10.0 release and is not a complete desktop product or standalone installer.

## Start

Install this development checkout into your usual Python environment:

```sh
python -m pip install -e .
batterylog-gui
```

On Windows, use the environment's `Scripts\batterylog-gui.exe`. Alternatively:

```sh
python -m batterylog.desktop
```

Python needs Tkinter/Tcl/Tk and an active graphical session. Check the environment with
`python -m tkinter`. If the module is absent, install the Tk support supplied by your Python
distributor (commonly `python3-tk` on Debian-based Linux). Official Windows Python installers
provide a Tcl/Tk option. The launcher adds no GUI dependencies to the Python package.
`batterylog-gui --help`, the existing CLI and Python API do not require Tk.

MDF/MF4 input still requires the existing optional dependencies:

```sh
python -m pip install -e '.[mf4]'
```

## One measurement

For a first try, select **Try demo…** and choose an existing folder. The launcher creates a
new `batterylog-demo-*` directory containing a small synthetic CSV and its YAML limits,
then fills the form. Select **Run analysis**, then **Open report**. No download or MDF
dependency is needed for this example.

The expected outcome is **FAIL**, with two violations at the final sample (4 seconds):
48 °C exceeds the illustrative 45 °C limit, and the 100 mV cell-voltage spread exceeds the
illustrative 80 mV limit. FAIL here is a completed engineering result, not a process error.
The report includes plots, violation evidence and the input/configuration hashes.
These demo limits are not recommended battery safety limits; use your validation plan
for real measurements. Each demo and each analysis uses a separate folder.

For your own file:

1. Select a CSV, MDF or MF4 measurement.
2. Select a YAML configuration, or leave it empty to use the existing default configuration.
3. Select **Inspect input** to read channel metadata before analysis. This uses the existing
   CLI inspection path in a subprocess, requires no output folder and does not decode samples
   or evaluate engineering rules. The launcher shows canonical bindings and the first blocking
   selection issue, plus up to 60 source channels in the scrollable details area.
4. Select an existing output location. Each run creates a separate `batterylog-*` folder.
5. Run analysis. The form is locked while the subprocess runs; Cancel remains available.
6. Open the completed HTML report in the default browser. Its path remains visible if no
   browser can be opened. The JSON result is next to the report.

The launcher uses the same interpreter and `python -m batterylog` as the CLI. It does not
add limits, infer units, modify configuration or change the validation rules. Canonical
signals, explicit YAML mappings and MDF metadata requirements still apply. Prepare noncanonical
units with the existing normalization workflow before analysis.

The combined development build also accepts [failure-model YAML](FAILURE_MODELS.md).
Select `examples/failure_models_demo.csv` and `examples/failure_models.example.yaml`
to exercise all five new model outcomes plus the existing pack/cell-sum rule. This
synthetic example produces FAIL with six events. The models can also run without
legacy limits: a fully observed passing model produces PASS; insufficient model
observations produce NOT_EVALUATED. The HTML and JSON retain result-v9 evidence.

## Batch folder

Enable **Batch folder** to switch the first picker from one measurement to an input
directory. **Recursive** optionally includes supported files in subdirectories. Select an
existing output location; each batch run creates a new `batterylog-batch-*` child directory
so previous runs are not overwritten. The launcher delegates to the existing sequential
`--batch` CLI workflow and shows PASS/FAIL/NOT_EVALUATED/ERROR counts plus the generated
`summary.csv` path when the run completes.

The result table lists each file, its outcome and its violation-event count. Select a row to
view its diagnostic and use **Open selected report** for a completed HTML report.
**Open output folder** opens this run's directory in the system file manager. ERROR and
NOT_PROCESSED rows do not open reports, and unknown event counts are shown as a dash rather
than zero. After cancellation, an available finalized `summary.csv` supplies the same table;
without a summary the launcher keeps the output-folder action but does not infer results
from leftover files. Large tables are inserted in small groups so Tk continues handling
input. Starting another task or changing mode clears the previous table and report actions.

Cancelling a batch sends a request over the worker's private stdin pipe. The worker raises
`KeyboardInterrupt` in its main thread so the existing CLI finalization path writes
`summary.csv`, preserves completed per-file HTML/JSON reports and marks untouched files as
NOT_PROCESSED. This works without a console window on Windows. If the worker remains blocked
for two seconds, the launcher escalates to a hard kill; a new summary may then be unavailable.
Any already-created batch output directory is retained rather than deleted.

| Displayed outcome | Meaning |
| --- | --- |
| PASS | The configured validation rules passed. |
| FAIL | An engineering validation failure; a completed report is available. |
| NOT_EVALUATED | No validation conclusion was reached; inspect the report. Without active rules this is the expected result. |
| ERROR | Input, configuration, dependency, process or output error. Batch reports from other completed files are retained. |
| CANCELLED | Single-file runs publish no report; batch runs retain completed reports and any finalized summary. |

Completed single-file output:

```text
selected-output-location/
  batterylog-<unique-name>/
    results/
      report.html
      result.json
```

While running, files are staged under `.pending` within the new run folder. The directory is
renamed to `results` only after the CLI has finished with a validation outcome and both files
exist. Existing runs and input/configuration files are never overwritten. Cancellation first
requests process termination, then escalates after two seconds if it is still running; the
GUI keeps polling until the process has exited before removing its owned output folder.
Closing during analysis asks whether to cancel and waits for this same cleanup. A cleanup
error keeps the window open so its message and affected folder remain visible.

A force-killed launcher, power loss or cleanup permission error can leave a run folder with
`.pending` files. These are not completed results. Cleanup errors are shown with the affected
path. The launcher does not automatically delete folders left by other runs.

The progress display is indeterminate: it does not invent a percentage or remaining time.
Error text displayed by the launcher is limited to the first 8 KiB of process diagnostics.
The subprocess's JSON stdout is discarded because the complete JSON is written to disk.

## Current scope and verification

This development workflow now includes single-file analysis, read-only input inspection and
sequential batch-folder analysis. It still has no channel-selection editor, unit-conversion UI,
embedded plot viewer, packaging installer or automatic update mechanism. The existing CLI
remains available for normalization and scripted workflows.

Tests exercise real CLI outcomes and parity, input/configuration hashes in HTML, distinct
output folders, partial-output cleanup, inspection metadata/issue handling and cancellation
escalation. Real Tk widget tests exercise selection, responsive analysis/inspection polling,
enabled controls, report opening and close handling.
For Linux without a desktop:

```sh
BATTERYLOG_REQUIRE_DESKTOP_TESTS=1 xvfb-run -a python -m pytest -q tests/test_desktop_ui.py
```

The main Linux CI matrix, minimum-runtime job and Windows job require these desktop tests; ordinary headless environments skip
only the display-dependent widget tests. Wheel/sdist smoke checks verify the installed GUI
help entry point outside the source checkout.

On Windows, require the real widgets and use Python-level output capture:

```powershell
$env:BATTERYLOG_REQUIRE_DESKTOP_TESTS = "1"
python -m pytest -q --capture=sys
```

During integration verification, pytest's default per-test file-descriptor capture
produced intermittent Tcl library-read errors while recreating test windows.
The same native Windows probe passed all 150 window creations with `--capture=sys`;
ordinary application launches do not use pytest capture. The Windows CI job uses
this capture mode and still fails if Tk cannot open the required windows.

## Windows review build

From a clean, committed development checkout with `build`, `twine`, and the development
dependencies installed, create an isolated review folder:

```powershell
.\.venv\Scripts\python.exe scripts\build_windows_review.py --output-parent C:\path\to\existing\folder
```

The builder checks both distributions in fresh base/MF4 environments outside the checkout,
opens and closes a real installed Tk window, and prepares the six-event synthetic model
report. The new folder contains `Start-BatteryLog.cmd`, the installed environment, examples,
distribution checksums and build diagnostics. Double-click the command file to open the
launcher. Keep the folder at its built location; Python virtual environments contain absolute
paths. This is a local Python-based review build, not a standalone installer.
