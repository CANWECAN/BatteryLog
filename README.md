# BatteryLog

BatteryLog is an engineering toolkit for validating EV battery test logs from the command line or Python.

The current version focuses on deterministic CSV analysis, optional MDF/MF4 ingestion, configurable validation rules, structured violation events, explicit validation status, and self-contained HTML evidence reports.

## Why it exists

Battery validation often involves repetitive checks across long measurement logs. BatteryLog turns those checks into reproducible software so violations can be traced to when they happened, how severe they were, and which signals were involved.

## Open source and real-world use

BatteryLog is open-source software licensed under the [Apache License 2.0](LICENSE). Commercial, internal, research, and educational use are welcome subject to the license terms.

Using BatteryLog on real battery/BMS validation data? If your confidentiality requirements allow it, please consider sharing **anonymized** engineering feedback through GitHub, such as:

- validation scenarios and test shapes
- dataset size and performance measurements
- vendor signal-naming patterns
- integration experience
- bugs, edge cases, and unexpected results

You do **not** need to publish proprietary test data to use BatteryLog. Even a short report such as "tested on a 96-cell, 1.2M-row HIL log" is useful for improving the project and documenting real-world adoption.

If BatteryLog supports research, validation, or engineering work, please cite or link the repository. Citation metadata is available in [`CITATION.cff`](CITATION.cff), and attribution information is recorded in [`NOTICE`](NOTICE).

## Report preview

The preview below is generated from the repository's vendor-style sample CSV and explicit signal-mapping config.

![BatteryLog HTML validation report](docs/assets/report-preview.png)

## Current capabilities

- Analyze CSV battery logs in bounded row chunks in both standard analysis and HTML evidence-report paths
- Optionally ingest ASAM MDF/MF4 measurement files through the same chunked validation engine
- Preserve violation events, extrema, and timestamp-ordering checks across chunk boundaries
- Map vendor-specific timestamp, pack-current, pack-voltage, cell-voltage, and temperature channel names into a canonical signal model
- Load validation limits from YAML
- Detect cell overvoltage and undervoltage
- Detect excessive cell-voltage imbalance
- Detect high and low temperature events
- Group consecutive failing samples into one violation event
- Optionally split sparse failing samples using a configurable maximum timestamp gap
- Record event start, end, and worst-case timestamps
- Record measured value, engineering limit, unit, and implicated signals
- Support optional scalar pack-current/pack-voltage signals plus one or more cell-voltage and temperature signals
- Reject missing, non-numeric, non-finite, or time-disordered required data
- Emit explicit `NOT_EVALUATED`, `PASS`, or `FAIL` validation status
- Report which rules were actually evaluated
- Emit a versioned machine-readable JSON result
- Publish and CI-validate the result contract as Draft 2020-12 JSON Schema
- Generate self-contained HTML validation reports
- Render deterministic inline SVG plots for cell-voltage envelope, cell delta, temperature envelope, configured limits, and violation evidence
- Record input/config SHA-256 provenance in HTML reports
- Return CI-friendly process exit codes
- Run as a Python API

## Canonical CSV schema

Without an explicit signal-mapping block, every input must contain:

- `timestamp_s`
- one or more indexed cell-voltage columns named `cell_<n>_v`
- one or more indexed temperature columns named `temp_<n>_c`

Examples are `cell_1_v`, `cell_96_v`, `temp_1_c`, and `temp_24_c`. The legacy single-temperature name `temp_c` is supported only when indexed temperature signals are not present.

The optional scalar electrical channels are `pack_current_a` and `pack_voltage_v`. They may appear independently. When present, they participate in required-numeric data-quality handling and their minimum/maximum values are emitted in the current result schema. The pack-voltage cell-sum rule requires an explicit positive tolerance; enable it only after verifying that the selected cells form the complete, synchronized series stack. Pack current activates charge/discharge overcurrent rules only when explicit limits and a positive-current direction are configured.

Aggregate names such as `cell_min_v`, `cell_max_v`, or `temp_max_c` are intentionally not treated as raw sensor channels.

Example:

```csv
timestamp_s,pack_current_a,pack_voltage_v,temp_1_c,temp_2_c,cell_1_v,cell_2_v
0,-25,7.89,28,27,3.95,3.94
1,35,7.26,48,46,3.68,3.58
```

The two cells in this illustrative snippet make up the entire series stack, so their sum equals the pack voltage at each sample. `timestamp_s` must be numeric and non-decreasing.

## Explicit signal mapping

Vendor exports do not need to be renamed before analysis. A YAML config can explicitly map source channel names into BatteryLog's canonical model:

```yaml
schema_version: 5
signals:
  timestamp: Time_s
  pack_current: PackCurrent
  pack_voltage: PackVoltage
  cell_voltage:
    pattern: 'BMS_CellVoltage_(?P<index>\d+)'
  temperature:
    pattern: 'T_Module_(?P<index>\d+)'
```

Signal patterns are applied as **full matches**, not substring searches. Both cell-voltage and temperature patterns must define a named `index` capture group containing ASCII digits. The numeric index determines canonical ordering, so source names such as `BMS_CellVoltage_001`, `BMS_CellVoltage_2`, and `BMS_CellVoltage_10` become `cell_1_v`, `cell_2_v`, and `cell_10_v`.

When a `signals` block is present, `timestamp`, `cell_voltage`, and `temperature` are required. Config schema v3 additionally accepts optional `pack_current` and `pack_voltage` source names. BatteryLog fails closed when:

- the mapped timestamp or a configured pack signal is missing
- a pattern matches no required channels
- two source channels resolve to the same logical index
- one source channel matches both sensor patterns
- the timestamp also matches a sensor pattern
- source signal names are duplicated

Extra columns that do not match the explicit patterns are not part of the canonical battery-signal model. For example, `BMS_CellVoltage_Max` is not selected by the numeric-index pattern above.

Signal mapping performs **naming/canonicalization only**. It does not convert units. CSV values must already use:

- seconds for the timestamp
- amperes for pack current
- volts for pack and cell voltage
- degrees Celsius for temperature

Violation events use canonical names such as `cell_1_v` and `temp_2_c`. The machine-readable result and HTML report record whether canonical or explicit mapping was used, along with the source timestamp, configured patterns, and selected pack-signal sources.

A tested vendor-style example is included. It selects four cell channels from a roughly 400 V pack for the existing per-cell checks; those cells are only a subset of the series stack. Do not enable the pack-voltage cell-sum rule with this example because its sum cannot represent the pack measurement:

```powershell
.\.venv\Scripts\batterylog.exe examples\vendor_battery_log.csv --config examples\vendor_mapping.example.yaml
```

## Optional MDF/MF4 ingestion

MDF/MF4 support is isolated behind the optional `mf4` dependency so the core installation remains lightweight. From a development checkout:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,mf4]"
```

Installed distributions use the standard Python extra syntax `batterylog[mf4]`. Files ending in `.mf4` or `.mdf` are dispatched to the MDF loader automatically; other paths continue to use the CSV loader.

The MDF adapter consumes already-decoded physical measurement channels. It deliberately disables automatic bus-logging processing; raw CAN/LIN decoding and DBC-driven extraction are separate future capabilities.

For canonical MDF channels, use names such as `pack_current_a`, `pack_voltage_v`, `cell_1_v`, `cell_2_v`, and `temp_1_c`. With an explicit `signals` mapping, BatteryLog selects the mapped vendor channels and uses the MDF master time as the source timestamp. The configured `signals.timestamp` name is assigned to that master time before the existing canonicalization step, so the same mapping contract can be reused across CSV and MDF inputs.

MDF timestamps are preserved as stored; BatteryLog does not silently shift the master to start at zero. Channel alignment is fail-closed: the first MDF implementation disables interpolation. If selected channels use different timestamp rasters, missing aligned samples become `NaN` and are rejected by the existing required-data validation instead of being silently interpolated.

MDF unit metadata is validated before data reaches the rule engine. Pack-current channels must identify amperes (`A`, `amp`, `amps`, `ampere`, or `amperes`); pack/cell-voltage channels must identify volts (`V`, `volt`, or `volts`); and temperature channels must identify degrees Celsius (`degC`, `°C`, or `Celsius`). Missing units and units requiring conversion, such as `mV` or Fahrenheit, are rejected; automatic unit conversion is not yet supported.

Example:

```powershell
.\.venv\Scripts\batterylog.exe test-run.mf4 --config validation.yaml --report battery-report.html
```

## Validation rules

BatteryLog currently emits these rule codes:

| Code | Condition |
| --- | --- |
| `CELL_IMBALANCE_HIGH` | per-row max cell voltage minus min cell voltage is above the configured limit |
| `CELL_OVERVOLTAGE` | at least one cell is above the configured maximum voltage |
| `CELL_UNDERVOLTAGE` | at least one cell is below the configured minimum voltage |
| `PACK_CHARGE_OVERCURRENT` | signed pack current exceeds the configured charge-current magnitude in the declared charge direction |
| `PACK_DISCHARGE_OVERCURRENT` | signed pack current exceeds the configured discharge-current magnitude in the declared discharge direction |
| `PACK_VOLTAGE_CELL_SUM_MISMATCH` | absolute difference between pack voltage and sum of selected series-cell voltages exceeds the configured positive tolerance |
| `TEMPERATURE_HIGH` | at least one temperature signal is above the configured maximum |
| `TEMPERATURE_LOW` | at least one temperature signal is below the configured minimum |
| `TEMPERATURE_SPREAD_HIGH` | row-wise maximum temperature minus minimum temperature exceeds the configured spread limit |

A rule can be disabled by setting its YAML value to `null`. Pack voltage is an optional measurement; its cell-sum rule activates only with an explicit positive tolerance.

## YAML configuration

Example:

```yaml
schema_version: 5

limits:
  cell_voltage:
    min_v: 2.8
    max_v: 4.2
    max_delta_v: 0.08

  temperature:
    min_c: -20
    max_c: 55
    max_spread_c: 12

  pack_current:
    charge_max_a: 80
    discharge_max_a: 160
    positive_direction: discharge

event_detection:
  max_gap_s: 2.0

data_quality:
  mode: strict
```

`charge_max_a` and `discharge_max_a` are non-negative magnitudes. When either is numeric, `positive_direction` is required and must be `charge` or `discharge`; BatteryLog never guesses a vendor's sign convention. Violation events preserve the source current sign in both `measured_value` and the corresponding signed `limit_value`. Configuring an overcurrent rule without a selected `pack_current_a` signal fails closed.

The values in `examples/validation.example.yaml` are illustrative only. They are not universal safety limits or chemistry defaults. Validation limits must come from the tested cell/pack specification, operating state, BMS strategy, and test plan.

BatteryLog does not assume universal engineering limits. If no YAML config or explicit CLI/Python threshold is supplied, it computes metrics only and emits no validation violations.

This is deliberate: voltage, temperature, and imbalance limits must come from the applicable cell/pack specification and validation plan rather than from generic tool defaults.

Precedence is:

```text
CLI numeric override / CLI explicit disable > YAML config
```

A rule is active only when its effective limit is numeric. A YAML value of `null` disables that rule, and the CLI can explicitly disable an active YAML rule with the corresponding `--no-*` option.

Unknown config keys are rejected instead of silently ignored, so spelling mistakes do not disable a validation rule unnoticed.

The `event_detection.max_gap_s` value controls event segmentation only. It is not a battery safety limit. When configured, adjacent failing rows are kept in the same event only when their timestamp gap is less than or equal to the configured value. A larger gap starts a new event.

If `max_gap_s` is omitted or `null`, BatteryLog preserves the original row-contiguity behavior.

### Required-data quality

Configuration schema 2 adds an explicit `data_quality.mode`:

- `strict` is the default and preserves the historical fail-fast behavior: the first missing, non-numeric, or non-finite required numeric value raises an input error.
- `exclude_invalid_rows` is opt-in. Rows containing an invalid required timestamp, present/configured pack-current or pack-voltage, cell-voltage, or temperature value are excluded from engineering-rule evaluation and measured extrema, and the defect is recorded as structured evidence.

Exclusion can never turn defective input into a passing result. Any structured data-quality event forces `validation_status` to `FAIL`, even when no engineering rule is active or no engineering-rule violation is recorded. Excluded rows also break violation-event continuity, so BatteryLog never bridges a rule event across unknown data.

Result row accounting distinguishes `rows_input`, `rows_analyzed`, and `rows_excluded`. Structured data-quality events use 1-based source data-row numbers and one of `MISSING_REQUIRED_VALUE`, `NON_NUMERIC_REQUIRED_VALUE`, or `NON_FINITE_REQUIRED_VALUE`. Adjacent rows with the same defect code and signal set are grouped into one deterministic event run.

Configuration schemas 1-5 remain accepted with their historical behavior. Schema 1 is equivalent to `data_quality.mode: strict`; schema 2 adds the `data_quality` block; schema 3 adds optional explicit `signals.pack_current` and `signals.pack_voltage` sources. Schema 4 adds explicit pack-current magnitude limits and the required `positive_direction` convention. Schema 5 adds `limits.temperature.max_spread_c`; schema 6 adds `limits.pack_voltage.cell_sum_max_delta_v`.

## Numerical comparison semantics

Validation limits use strict engineering boundaries:

- high-limit rules violate only when the measured value is strictly greater than the configured limit
- low-limit rules violate only when the measured value is strictly less than the configured limit
- a value on the configured boundary is not a violation

BatteryLog applies a very small binary64 representation guard when deciding whether a computed floating-point value is effectively on the boundary. The relative guard is fixed at `8 * float64 epsilon` (approximately `1.776e-15`), while the absolute tolerance is `0.0`. This avoids applying one unit-dependent absolute allowance across volts, degrees Celsius, and seconds.

This guard is **not** an engineering tolerance, sensor accuracy allowance, hysteresis, or calibration margin. Those belong in the test specification and must be reflected in the configured engineering limits themselves.

The same comparison policy is used for cell overvoltage, cell undervoltage, cell imbalance, charge/discharge overcurrent, high/low temperature, pack-voltage versus cell-sum mismatch, and maximum event-gap boundaries. The effective policy is included in the machine-readable result as `comparison_policy` and rendered in HTML reports.

Cell-delta values may still be rounded for serialized/display output to suppress unreadable subtraction artifacts; that presentation normalization does not participate in the validation decision.

## Validation status

BatteryLog separates "no violations" from "no validation was performed":

| Status | Meaning |
| --- | --- |
| `NOT_EVALUATED` | no engineering rule had an active numeric limit and no structured data-quality defect was recorded |
| `PASS` | at least one engineering rule was evaluated, no rule violations were found, and no structured data-quality defect was recorded |
| `FAIL` | at least one engineering-rule violation and/or structured required-data quality defect was recorded |

The result also contains `rules_evaluated`, so downstream reports can show exactly which checks participated in the status decision.

## Result schema

Machine-readable analysis results include their own `schema_version`. The current **result schema is 8**.

The current Draft 2020-12 JSON Schema is published at [`batterylog/schema/result-v8.json`](batterylog/schema/result-v8.json) and is included in the Python distribution package. The frozen v7, v6, v5, v4, v3, and v2 artifacts remain packaged for earlier consumers.

Result schema version 2 was BatteryLog's **first formally frozen result contract**. Result schema version 3 extends that contract with structured data-quality evidence and explicit row accounting:

- `data_quality.mode` and grouped `data_quality.events`
- `rows_input`, `rows_analyzed`, and `rows_excluded`
- nullable measured extrema when every input row is excluded

Result schema version 4 adds pack-signal provenance and nullable electrical extrema:

- `signal_mapping.pack_current_source` and `signal_mapping.pack_voltage_source`
- `max_pack_current_a` and `min_pack_current_a`
- `max_pack_voltage_v` and `min_pack_voltage_v`

A pack extrema pair is numeric only when that signal was selected and at least one row was analyzed; otherwise it is `null`.

Result schema version 5 adds `PACK_CHARGE_OVERCURRENT` and `PACK_DISCHARGE_OVERCURRENT`, ampere violation evidence, and these applied-limit fields:

- `pack_charge_max_a`
- `pack_discharge_max_a`
- `pack_current_positive_direction`

Result schema version 6 adds `TEMPERATURE_SPREAD_HIGH`, `limits_applied.temperature_spread_max_c`, and exact `max_temperature_spread_c` evidence. Spread events identify the hottest and coldest temperature signal(s) at the event peak.

Result schema version 7 enriches every engineering violation event with `sample_count`, `duration_s`, and `peak_excursion`. The threshold, grouping, first-equal-peak tie-break, and PASS/FAIL semantics are unchanged.

Result schema version 8 adds `PACK_VOLTAGE_CELL_SUM_MISMATCH`, an opt-in absolute difference between `pack_voltage_v` and the sum of selected `cell_*_v` channels. Enable it with YAML schema 6 under `limits.pack_voltage.cell_sum_max_delta_v` or `--pack-cell-sum-max-delta-v`. The tolerance must be positive and the pack-voltage channel is required. The result and event include pack voltage, cell sum, signed error (`pack - sum`), absolute delta, and peak time. This check assumes the selected cells represent the complete series stack on the same time basis as the pack sensor. Omitted or parallel cells, tap offsets, and unsynchronized channels need explicit preparation before interpreting the result. A row assembled from multiplexed or forward-filled BMS signals does not by itself prove simultaneous sampling; align or reconstruct those signals before enabling this rule. The rule is disabled by default.

The current schema rejects unknown top-level/nested fields and encodes status invariants such as:

- `NOT_EVALUATED`: no rules evaluated, no violation events, and no data-quality events
- `PASS`: at least one rule evaluated, no violation events, and no data-quality events
- `FAIL`: at least one violation event and/or data-quality event
- `rows_analyzed == 0`: at least one row was excluded, engineering-rule violations are empty, and measured extrema are `null`
- non-empty `data_quality.events`: at least one row was excluded

Some arithmetic relationships require semantic validation beyond Draft 2020-12 JSON Schema. BatteryLog-generated results guarantee `rows_input == rows_analyzed + rows_excluded`, data-quality event bounds satisfy `1 <= start_row <= end_row <= rows_input`, and each data-quality event's `affected_values` equals its inclusive row span multiplied by its signal count. Engineering violation events guarantee `sample_count >= 1`, `duration_s == end_time_s - start_time_s`, and `peak_excursion == abs(measured_value - limit_value)` within the documented 12-decimal evidence rounding. Consumers of results from independent or untrusted producers should check these relationships in addition to schema validation.

Package versions, YAML configuration-schema versions, and result-schema versions are intentionally independent. The current YAML config schema is 6; config schemas 1-5 remain accepted with their historical behavior.

From result schema v2 onward, adding, removing, renaming, changing the required status/type/meaning of result fields, or otherwise changing the machine-readable wire contract requires a new result-schema version. The full policy and historical rationale are documented in [`docs/RESULT_SCHEMA_VERSIONING.md`](docs/RESULT_SCHEMA_VERSIONING.md).

## Event semantics

A violation is not reported once per failing row. By default, consecutive failing rows are grouped into one event. When `event_detection.max_gap_s` is configured, a timestamp gap greater than that value starts a new event even if no passing row exists between the samples. A gap exactly on the configured boundary remains in the same event.

Each event stores:

- `start_time_s`: first failing sample
- `end_time_s`: last consecutive failing sample
- `peak_time_s`: timestamp of the worst value in the event
- `measured_value`: worst value reached
- `limit_value`: configured engineering threshold
- `sample_count`: number of violating analyzed samples represented by the event
- `duration_s`: elapsed timestamp span from first to last failing sample; a single-sample event or duplicate timestamps may yield `0.0`
- `peak_excursion`: non-negative absolute threshold distance at the event peak, in the event unit
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

Run profiling benchmarks separately from CI:

```powershell
.\.venv\Scripts\python.exe benchmarks\benchmark_event_builders.py --rows 300000 --signals 20
.\.venv\Scripts\python.exe benchmarks\benchmark_csv_analysis.py --rows 200000 --cells 100 --mode analysis
.\.venv\Scripts\python.exe benchmarks\benchmark_csv_analysis.py --rows 200000 --cells 100 --mode report
.\.venv\Scripts\python.exe benchmarks\benchmark_mf4_analysis.py
```

The event-builder benchmark intentionally creates many short events. The CSV benchmark generates a temporary canonical log and can profile either the Python analysis path or the full CLI HTML evidence-report path, reporting end-to-end time plus `tracemalloc` Python-heap peak usage. The MF4 benchmark requires `.[dev,mf4]`, generates deterministic uncompressed MDF4 inputs at two sizes by default, then runs each analysis/report case in fresh child processes while sampling process RSS with `psutil`. These are profiling aids, not pass/fail CI timing gates. The current MDF/MF4 methodology and baseline results are documented in [`docs/MF4_BENCHMARK.md`](docs/MF4_BENCHMARK.md).

## CLI usage

Compute metrics only, without assuming engineering limits:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv
```

Use a YAML config with canonical signals:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv --config examples\validation.example.yaml
```

Analyze a vendor-style CSV through explicit signal mapping:

```powershell
.\.venv\Scripts\batterylog.exe examples\vendor_battery_log.csv --config examples\vendor_mapping.example.yaml
```

Override YAML values from the CLI:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv --config examples\validation.example.yaml --cell-max-v 4.15 --temp-max-c 50 --max-event-gap-s 0.5
```

Disable rules that are active in YAML:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv --config examples\validation.example.yaml --no-cell-max-v --no-temp-max-c
```

Available disable options are `--no-cell-min-v`, `--no-cell-max-v`, `--no-imbalance-limit-v`, `--no-temp-min-c`, `--no-temp-max-c`, `--no-pack-charge-max-a`, and `--no-pack-discharge-max-a`.

The existing `--temp-warning-c` option remains available as an alias for `--temp-max-c`; `--no-temp-warning-c` is likewise an alias for `--no-temp-max-c`. Pack-current limits use `--pack-charge-max-a` and `--pack-discharge-max-a`; `--pack-current-positive-direction charge|discharge` supplies or overrides the explicit sign convention. A numeric override and its matching disable option are mutually exclusive and produce a CLI usage error when supplied together.

Use `--no-max-event-gap-s` to disable a YAML event-gap limit and return to row-contiguity grouping. Omitting both event-gap options preserves YAML; `--max-event-gap-s N` overrides it. The numeric and disable options are mutually exclusive. Explicit disable is recorded as `analysis_options.max_event_gap_s: null`.

Generate a self-contained HTML report:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv --config examples\validation.example.yaml --report battery-report.html
```

Write the canonical JSON result explicitly as UTF-8:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv --config examples\validation.example.yaml --json-out battery-result.json
```

JSON remains the canonical stdout output for completed analyses, including when `--report` or `--json-out` is supplied. `--json-out` adds an atomically written UTF-8 file; it does not suppress stdout. This avoids relying on shell-specific redirection encodings while preserving the existing script-friendly stdout contract.

The HTML report contains the validation status, dataset summary, measured extrema, deterministic inline SVG time-series plots, effective limits, evaluated rules, signal-mapping provenance, violation events, BatteryLog version, result-schema version, UTC generation timestamp, and SHA-256 provenance for the input log and optional YAML config. The plots cover the cell-voltage min/max envelope, cell-voltage delta, temperature min/max envelope, an optional temperature-spread chart when that rule is configured, an optional pack-current chart when pack current is present, and pack-voltage/cell-sum and absolute-mismatch charts when pack voltage is present. Configured limit lines come from the effective `limits_applied` result, while shaded violation intervals and worst-case markers come from the existing structured violation events.

Report and JSON output paths are not allowed to overwrite the input log or validation config, and the JSON and HTML output paths must be distinct.

## Process exit codes

| Exit code | Meaning |
| ---: | --- |
| `0` | command completed successfully; for analysis, at least one rule was evaluated and all evaluated rules passed |
| `1` | validation completed and at least one evaluated rule failed |
| `2` | CLI usage/parsing error |
| `3` | metrics were computed but no engineering rule was evaluated |
| `4` | input, configuration, analysis, report-generation, or output-write error |

`run()` returns these integer codes for expected CLI outcomes; `main()` is the single process boundary that raises `SystemExit(run())`. `--help` is treated as a successful CLI outcome and returns `0`.

Compared with the 0.6.x line, runtime/data/config/report errors move from exit code `2` to `4`; code `2` is reserved for command-line usage errors.

This allows CI/HIL pipelines to distinguish a true PASS, validation failure, unevaluated dataset, malformed command line, and runtime/input failure without parsing the JSON payload.

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
    signal_mapping=config.signals,
)
```

The older `load_validation_limits()` helper remains available for callers that intentionally need only the engineering-limit portion of a config file.

The legacy `imbalance_limit_v` and `temp_warning_c` arguments to `analyze_battery_log()` are deprecated and emit `DeprecationWarning`. New code should construct `ValidationLimits` and pass it through `limits=`. During the compatibility period, a supplied legacy value overrides the corresponding field from `limits=`.

## Engineering notes

The analyzer fails closed on invalid required measurement values. A missing present/configured pack signal, cell, or temperature sample is treated as invalid input instead of being silently excluded from min/max calculations, because silently skipping a signal can hide a real validation failure. The validation error identifies the first failing data row, column, and value to make large-log diagnosis practical.

Event grouping uses row contiguity by default and can optionally split sparse failures with `event_detection.max_gap_s`.

Signal mapping deliberately does not infer units or perform unit conversion. CSV inputs remain responsible for canonical engineering units. The MDF/MF4 loader uses available channel metadata to validate amperes, volts, and degrees Celsius explicitly before canonical data reaches the rule engine.

HTML evidence generation copies the source measurement file into a private temporary-file snapshot while computing SHA-256 in the same streaming pass. Analysis then consumes that exact snapshot through the selected loader. CSV uses 50,000-row chunks. When all required MDF/MF4 channels share one channel group, BatteryLog reads record-bounded selected-signal chunks sized from a 64 MiB numeric-row target; multi-group inputs retain the `asammdf` no-interpolation DataFrame fallback with a 64 MiB output-chunk target. The optional YAML config remains an immutable byte snapshot. This keeps the provenance content-addressed: the bytes named by the report hashes are the bytes that produced the result, without retaining the full source measurement as one large Python `bytes` object.

BatteryLog still re-hashes the on-disk source/config before writing the report to detect ordinary later drift. That final content check is streamed and ignores metadata-only changes; it is a secondary guard rather than the basis of the provenance guarantee. A file that is changed and restored between checks cannot cause different bytes to be analyzed under the recorded snapshot hash.

The security and trust boundaries of this evidence model are documented in [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md). SHA-256 provenance binds results to analyzed bytes; it does not authenticate the origin of the data or digitally sign the generated report.

CSV standard analysis and HTML evidence-report analysis use 50,000-row source chunks. MDF/MF4 chunk targets are **not** end-to-end process RSS bounds. After removing `asammdf`'s full selected-channel `filter()` materialization for single-group inputs, the repeatable 96-cell/12-temperature Windows benchmark measured median OS-native peak RSS of 475.2 MiB and 678.5 MiB for standard analysis and 393.3 MiB and 547.7 MiB for report mode at 100,000 and 200,000 rows respectively. That is a 18-27% peak-RSS reduction versus the original path, but RSS still grows with source size; multi-group inputs also retain the original no-interpolation fallback. These host-specific results are informational and documented in [`docs/MF4_BENCHMARK.md`](docs/MF4_BENCHMARK.md). Global extrema, timestamp ordering, and active violation-event state are carried across analyzer chunk boundaries. The machine-readable result still materializes its violation-event list, so workloads that intentionally produce extremely large numbers of distinct events can consume memory proportional to the result itself.

Evidence-report mode requires temporary storage approximately proportional to the source measurement-file size while the report is being generated. The temporary snapshot is closed and removed automatically when analysis finishes. The optional YAML config is still retained in memory and therefore contributes memory proportional to config size.

Time-series plotting is intentionally separate from `AnalysisResult`: the reducer consumes row-level extrema already computed by the streaming analyzer and never recalculates PASS/FAIL decisions, limits, or violation events. Inputs within the configured point budget remain lossless; larger inputs use deterministic extrema-preserving reduction that is independent of loader chunk boundaries. HTML reports render the retained geometry directly as inline SVG, with no external JavaScript, image files, or plotting dependency. The default retained-point budget is 2,400; violation intervals and worst-case markers are overlaid from `AnalysisResult["violations"]`, so downsampling cannot erase validation evidence. The detailed contract is documented in [`docs/REPORT_SERIES.md`](docs/REPORT_SERIES.md).

Planned follow-on work includes CAN/DBC decoding, richer rule metadata, broader unit-conversion policy, signed evidence manifests, and further real-world report/performance validation.

## Status

Early MVP. The API may change while the validation model is expanded.

## Release artifacts

Tagged releases build wheel/sdist artifacts in CI after the core Linux/Windows and optional MF4 integration checks pass. Each release includes SHA-256 checksums; package and tag versions must agree. See [the release procedure](docs/RELEASING.md).
