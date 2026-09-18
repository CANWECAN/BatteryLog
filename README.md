# BatteryLog

BatteryLog is an engineering toolkit for validating EV battery test logs from the command line or Python.

The current version focuses on deterministic CSV analysis, structured violation events, cell-voltage spread, thermal limits, and strict input validation.

## Why it exists

Battery validation often involves repetitive checks across long measurement logs. BatteryLog turns those checks into reproducible software so violations can be traced to when they happened, how severe they were, and which signals were involved.

## Current capabilities

- Analyze CSV battery logs
- Detect cell-voltage imbalance
- Detect high-temperature events
- Group consecutive failing samples into one violation event
- Record event start, end, and peak timestamps
- Record measured value, engineering limit, unit, and implicated signals
- Support one or more temperature signals
- Reject missing, non-numeric, non-finite, or time-disordered required data
- Apply configurable voltage-spread and temperature thresholds
- Emit JSON from the CLI
- Run as a Python API

## Expected CSV schema

Every input must contain:

- `timestamp_s`
- one or more cell-voltage columns named `cell_*_v`
- one or more temperature columns named `temp_*_c`

The legacy single-temperature name `temp_c` also matches the temperature pattern.

Example:

```csv
timestamp_s,temp_1_c,temp_2_c,cell_1_v,cell_2_v
0,28,27,3.95,3.94
1,48,46,3.68,3.58
```

`timestamp_s` must be numeric and non-decreasing.

## Event semantics

A violation is not reported once per failing row. Consecutive samples that violate the same rule are grouped into one event.

For each event BatteryLog records:

- `start_time_s`: first failing sample
- `end_time_s`: last consecutive failing sample
- `peak_time_s`: time of the worst measured value
- `measured_value`: worst value reached in that event
- `limit_value`: configured engineering threshold
- `unit`: engineering unit for the rule
- `signals`: signals responsible for the peak

This model is intended to support later HTML reports, plots, and test-evidence workflows without losing event provenance.

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Run the quality gate:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q --cov=batterylog
```

## CLI usage

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv
```

Custom limits:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv --imbalance-limit-v 0.08 --temp-warning-c 45
```

Example violation event:

```json
{
  "code": "CELL_IMBALANCE_HIGH",
  "start_time_s": 4.0,
  "end_time_s": 4.0,
  "peak_time_s": 4.0,
  "measured_value": 0.1,
  "limit_value": 0.08,
  "unit": "V",
  "signals": ["cell_1_v", "cell_4_v"]
}
```

## Python API

```python
from batterylog import analyze_battery_log

result = analyze_battery_log("examples/sample_battery_log.csv")

for event in result["violations"]:
    print(event["code"], event["peak_time_s"], event["signals"])
```

## Engineering notes

The analyzer fails closed on invalid required sensor values. A missing cell or temperature sample is treated as invalid input instead of being silently excluded from min/max calculations, because silently skipping a signal can hide a real validation failure.

Thresholds are currently global for the input file. Per-signal limits, chemistry-specific configuration, plotting, CAN/DBC decoding, MF4 support, and report generation are planned follow-on work.

## Status

Early MVP. The API may change while the validation model is expanded.
