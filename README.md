# BatteryLog

BatteryLog is an engineering toolkit for validating EV battery test logs from the command line or Python.

The current version focuses on deterministic CSV analysis, configurable validation rules, structured violation events, explicit validation status, and self-contained HTML evidence reports.

## Why it exists

Battery validation often involves repetitive checks across long measurement logs. BatteryLog turns those checks into reproducible software so violations can be traced to when they happened, how severe they were, and which signals were involved.

## Report preview

The preview below is generated from the repository's included sample CSV and validation config.

![BatteryLog HTML validation report](docs/assets/report-preview.png)

## Current capabilities

- Analyze CSV battery logs
- Load validation limits from YAML
- Detect cell overvoltage and undervoltage
- Detect excessive cell-voltage imbalance
- Detect high and low temperature events
- Group consecutive failing samples into one violation event
- Optionally split sparse failing samples using a configurable maximum timestamp gap
- Record event start, end, and worst-case timestamps
- Record measured value, engineering limit, unit, and implicated signals
- Support one or more cell-voltage and temperature signals
- Reject missing, non-numeric, non-finite, or time-disordered required data
- Emit explicit `NOT_EVALUATED`, `PASS`, or `FAIL` validation status
- Report which rules were actually evaluated
- Emit a versioned machine-readable JSON result
- Generate self-contained HTML validation reports
- Record input/config SHA-256 provenance in HTML reports
- Return CI-friendly process exit codes
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

event_detection:
  max_gap_s: 2.0
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

The `event_detection.max_gap_s` value controls event segmentation only. It is not a battery safety limit. When configured, adjacent failing rows are kept in the same event only when their timestamp gap is less than or equal to the configured value. A larger gap starts a new event.

If `max_gap_s` is omitted or `null`, BatteryLog preserves the original row-contiguity behavior.

## Validation status

BatteryLog separates "no violations" from "no validation was performed":

| Status | Meaning |
| --- | --- |
| `NOT_EVALUATED` | no engineering rule had an active numeric limit; metrics were computed only |
| `PASS` | at least one engineering rule was evaluated and no violations were found |
| `FAIL` | at least one evaluated rule produced a violation |

The result also contains `rules_evaluated`, so downstream reports can show exactly which checks participated in the status decision.

## Result schema

Machine-readable results include a separate `schema_version`. The current result schema is `1`.

Package versions and result-schema versions are intentionally independent. A package release may add compatible features without changing the result schema; the schema version should change only when the machine-readable result contract changes incompatibly.

## Event semantics

A violation is not reported once per failing row. By default, consecutive failing rows are grouped into one event. When `event_detection.max_gap_s` is configured, a timestamp gap greater than that value starts a new event even if no passing row exists between the samples. A gap exactly on the configured boundary remains in the same event.

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

Override YAML values from the CLI:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv --config examples\validation.example.yaml --cell-max-v 4.15 --temp-max-c 50 --max-event-gap-s 0.5
```

The existing `--temp-warning-c` option remains available as an alias for `--temp-max-c`. CLI overrides take precedence over YAML values.

Generate a self-contained HTML report:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv --config examples\validation.example.yaml --report battery-report.html
```

The report contains the validation status, dataset summary, measured extrema, effective limits, evaluated rules, violation events, BatteryLog version, result-schema version, UTC generation timestamp, and SHA-256 provenance for the input log and optional YAML config.

The report path is not allowed to overwrite the input log or validation config.

## Process exit codes

| Exit code | Meaning |
| ---: | --- |
| `0` | at least one rule was evaluated and all evaluated rules passed |
| `1` | validation completed and at least one evaluated rule failed |
| `2` | input, configuration, CLI, or report-generation error |
| `3` | metrics were computed but no engineering rule was evaluated |

This allows CI/HIL pipelines to distinguish a true PASS from a validation failure or an unevaluated dataset without parsing the JSON payload.

## Python API

```python
from batterylog import EventDetectionConfig, ValidationLimits, analyze_battery_log

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
    event_detection=EventDetectionConfig(max_gap_s=0.5),
)

for event in result["violations"]:
    print(event["code"], event["peak_time_s"], event["signals"])
```

YAML can also be loaded programmatically:

```python
from batterylog import analyze_battery_log, load_validation_config

config = load_validation_config("examples/validation.example.yaml")
result = analyze_battery_log(
    "test.csv",
    limits=config.limits,
    event_detection=config.event_detection,
)
```

The older `load_validation_limits()` helper remains available for callers that intentionally need only the engineering-limit portion of a config file.

## Engineering notes

The analyzer fails closed on invalid required sensor values. A missing cell or temperature sample is treated as invalid input instead of being silently excluded from min/max calculations, because silently skipping a signal can hide a real validation failure.

Event grouping currently uses row contiguity. A future version may add a maximum allowed time gap so sparse logs can distinguish physically separate events even when no passing sample exists between them.

Planned follow-on work includes report plots, MF4/MDF support, CAN/DBC decoding, configurable signal mapping, richer rule metadata, and larger-log processing.

## Status

Early MVP. The API may change while the validation model is expanded.
