# BatteryLog

BatteryLog is an engineering toolkit for validating EV battery test logs from the command line or Python.

The current version focuses on deterministic CSV analysis, configurable validation rules, structured violation events, and strict input validation.

## Why it exists

Battery validation often involves repetitive checks across long measurement logs. BatteryLog turns those checks into reproducible software so violations can be traced to when they happened, how severe they were, and which signals were involved.

## Current capabilities

- Analyze CSV battery logs
- Load validation limits from YAML
- Detect cell overvoltage and undervoltage
- Detect excessive cell-voltage imbalance
- Detect high and low temperature events
- Group consecutive failing samples into one violation event
- Record event start, end, and worst-case timestamps
- Record measured value, engineering limit, unit, and implicated signals
- Support one or more cell-voltage and temperature signals
- Reject missing, non-numeric, non-finite, or time-disordered required data
- Emit machine-readable JSON from the CLI
- Run as a Python API

## Expected CSV schema

Every input must contain:

- `timestamp_s`
- one or more indexed cell-voltage columns named `cell_<n>_v`
- one or more indexed temperature columns named `temp_<n>_c`

Examples are `cell_1_v`, `cell_96_v`, `temp_1_c`, and `temp_24_c`. The legacy single-temperature name `temp_c` is supported only when indexed temperature signals are not present.

Aggregate names such as `cell_min_v`, `cell_max_v`, or `temp_max_c` are intentionally not treated as raw sensor channels.

Example:

```csv
timestamp_s,temp_1_c,temp_2_c,cell_1_v,cell_2_v
0,28,27,3.95,3.94
1,48,46,3.68,3.58
```

`timestamp_s` must be numeric and non-decreasing.

## Validation rules

BatteryLog currently emits these rule codes:

| Code | Condition |
| --- | --- |
| `CELL_IMBALANCE_HIGH` | per-row max cell voltage minus min cell voltage is above the configured limit |
| `CELL_OVERVOLTAGE` | at least one cell is above the configured maximum voltage |
| `CELL_UNDERVOLTAGE` | at least one cell is below the configured minimum voltage |
| `TEMPERATURE_HIGH` | at least one temperature signal is above the configured maximum |
| `TEMPERATURE_LOW` | at least one temperature signal is below the configured minimum |

A rule can be disabled by setting its YAML value to `null`.

## YAML configuration

Example:

```yaml
schema_version: 1

limits:
  cell_voltage:
    min_v: 2.8
    max_v: 4.2
    max_delta_v: 0.08

  temperature:
    min_c: -20
    max_c: 55
```

The values in `examples/validation.example.yaml` are illustrative only. They are not universal safety limits or chemistry defaults. Validation limits must come from the tested cell/pack specification, operating state, BMS strategy, and test plan.

BatteryLog does not assume universal engineering limits. If no YAML config or explicit CLI/Python threshold is supplied, it computes metrics only and emits no validation violations.

This is deliberate: voltage, temperature, and imbalance limits must come from the applicable cell/pack specification and validation plan rather than from generic tool defaults.

Precedence is:

```text
CLI override > YAML config
```

A rule is active only when a numeric limit is explicitly supplied. A YAML value of `null` disables that rule.

Unknown config keys are rejected instead of silently ignored, so spelling mistakes do not disable a validation rule unnoticed.

## Event semantics

A violation is not reported once per failing row. Consecutive samples that violate the same rule are grouped into one event.

Each event stores:

- `start_time_s`: first failing sample
- `end_time_s`: last consecutive failing sample
- `peak_time_s`: timestamp of the worst value in the event
- `measured_value`: worst value reached
- `limit_value`: configured engineering threshold
- `unit`: engineering unit for the rule
- `signals`: signal or signals responsible for the worst value

Example:

```json
{
  "code": "CELL_OVERVOLTAGE",
  "start_time_s": 120.1,
  "end_time_s": 120.4,
  "peak_time_s": 120.3,
  "measured_value": 4.24,
  "limit_value": 4.2,
  "unit": "V",
  "signals": ["cell_23_v"]
}
```

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Run the quality gate:

```powershell
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q --cov=batterylog --cov-fail-under=95
```

## CLI usage

Compute metrics only, without assuming engineering limits:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv
```

Use a YAML config:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv --config examples\validation.example.yaml
```

Override a YAML value from the CLI:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv --config examples\validation.example.yaml --cell-max-v 4.15 --temp-max-c 50
```

The existing `--temp-warning-c` option remains available as an alias for `--temp-max-c`.

## Python API

```python
from batterylog import ValidationLimits, analyze_battery_log

limits = ValidationLimits(
    cell_min_v=2.8,
    cell_max_v=4.2,
    imbalance_max_v=0.08,
    temperature_min_c=-20,
    temperature_max_c=55,
)

result = analyze_battery_log(
    "examples/sample_battery_log.csv",
    limits=limits,
)

for event in result["violations"]:
    print(event["code"], event["peak_time_s"], event["signals"])
```

YAML can also be loaded programmatically:

```python
from batterylog import analyze_battery_log, load_validation_limits

limits = load_validation_limits("examples/validation.example.yaml")
result = analyze_battery_log("test.csv", limits=limits)
```

## Engineering notes

The analyzer fails closed on invalid required sensor values. A missing cell or temperature sample is treated as invalid input instead of being silently excluded from min/max calculations, because silently skipping a signal can hide a real validation failure.

Event grouping currently uses row contiguity. A future version may add a maximum allowed time gap so sparse logs can distinguish physically separate events even when no passing sample exists between them.

Planned follow-on work includes HTML reporting, plots, MF4/MDF support, CAN/DBC decoding, richer rule metadata, and larger-log processing.

## Status

Early MVP. The API may change while the validation model is expanded.
