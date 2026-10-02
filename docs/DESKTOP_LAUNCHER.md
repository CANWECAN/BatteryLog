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

1. Select a CSV, MDF or MF4 measurement.
2. Select a YAML configuration, or leave it empty to use the existing default configuration.
3. Select an existing output location. Each run creates a separate `batterylog-*` folder.
4. Run analysis. The form is locked while the subprocess runs; Cancel remains available.
5. Open the completed HTML report in the default browser. Its path remains visible if no
   browser can be opened. The JSON result is next to the report.

The launcher uses the same interpreter and `python -m batterylog` as the CLI. It does not
add limits, infer units, modify configuration or change the validation rules. Canonical
signals, explicit YAML mappings and MDF metadata requirements still apply. Prepare noncanonical
units with the existing normalization workflow before analysis.

| Displayed outcome | Meaning |
| --- | --- |
| PASS | The configured validation rules passed. |
| FAIL | An engineering validation failure; a completed report is available. |
| NOT_EVALUATED | No validation conclusion was reached; inspect the report. Without active rules this is the expected result. |
| ERROR | Input, configuration, dependency, process or output error; no completed report is published. |
| CANCELLED | The run was cancelled before completion was displayed; no completed report is published. |

Completed output:

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
Closing during analysis asks whether to cancel and waits for this same cleanup.

A force-killed launcher, power loss or cleanup permission error can leave a run folder with
`.pending` files. These are not completed results. Cleanup errors are shown with the affected
path. The launcher does not automatically delete folders left by other runs.

The progress display is indeterminate: it does not invent a percentage or remaining time.
Error text displayed by the launcher is limited to the first 8 KiB of process diagnostics.
The subprocess's JSON stdout is discarded because the complete JSON is written to disk.

## Current scope and verification

This first workflow has no batch UI, channel-selection editor, unit-conversion UI, embedded
plot viewer, packaging installer or automatic update mechanism. The existing CLI remains
available for inspection, normalization and batch analysis.

Tests exercise real CLI outcomes and parity, input/configuration hashes in HTML, distinct
output folders, partial-output cleanup and cancellation escalation. Real Tk widget tests
exercise selection, responsive polling, enabled controls, report opening and close handling.
For Linux without a desktop:

```sh
BATTERYLOG_REQUIRE_DESKTOP_TESTS=1 xvfb-run -a python -m pytest -q tests/test_desktop_ui.py
```

The main Linux CI matrix requires these desktop tests; ordinary headless environments skip
only the display-dependent widget tests. Wheel/sdist smoke checks verify the installed GUI
help entry point outside the source checkout.
