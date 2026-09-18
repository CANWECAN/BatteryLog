# BatteryLog

BatteryLog is a small engineering toolkit for validating EV battery test logs from the command line or Python.

The current MVP focuses on deterministic CSV analysis: cell-voltage spread, thermal limits, input validation, and machine-readable results.

## Why it exists

Battery validation often starts with large amounts of test data and repetitive checks. BatteryLog aims to turn those checks into reproducible software rather than ad-hoc spreadsheet work.

## Current capabilities

- Analyze CSV battery logs
- Detect cell-voltage imbalance
- Track maximum cell voltage, minimum cell voltage, and maximum temperature
- Reject missing, non-numeric, or non-finite sensor data
- Apply configurable voltage-spread and temperature thresholds
- Emit JSON from the CLI
- Run as a Python API

## Expected CSV schema

At minimum, the file must contain:

- `temp_c`
- one or more cell-voltage columns named `cell_*_v`

Example:

```csv
timestamp_s,temp_c,cell_1_v,cell_2_v
0,28,3.95,3.94
1,48,3.68,3.58
```
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

Example result:

```json
{
  "cells_detected": 4,
  "max_cell_voltage_v": 3.95,
  "max_delta_v": 0.1,
  "max_temperature_c": 48.0,
  "min_cell_voltage_v": 3.58,
  "rows_analyzed": 5,
  "violations": ["CELL_IMBALANCE_HIGH", "TEMPERATURE_WARNING"]
}
```
## Python API

```python
from batterylog import analyze_battery_log

result = analyze_battery_log("examples/sample_battery_log.csv")
print(result["violations"])
```

## Engineering notes

The analyzer fails closed on invalid sensor values. A missing reading is treated as invalid input instead of being silently excluded from min/max calculations, because silently skipping a cell can hide a real imbalance.

Thresholds are currently global for the input file. Per-signal limits, richer rule definitions, plotting, CAN/DBC decoding, MF4 support, and report generation are planned follow-on work.

## Status

Early MVP. The API may change while the validation model is being expanded.
