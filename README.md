# BatteryLog

BatteryLog is an open-source engineering toolkit for reproducible EV battery/BMS log validation from the command line or Python.

**Current release:** `v0.9.1`

**Status:** **Pre-1.0 engineering beta.** The validation core is stable and extensively tested; APIs and supported workflows may still evolve before 1.0.

> **Real-data proof:** BatteryLog v0.9.1 was exercised on **30.2 million physical battery-pack records**, producing **90.6 million branch-row analyses** across **1,230 runs**, with **1,230/1,230 independent pack/cell-sum parity checks**.

## What it does

- Streams large CSV logs with bounded source-row chunks
- Optionally ingests ASAM MDF/MF4 measurement files
- Maps vendor signal names into a canonical battery model
- Applies explicit voltage, temperature, current, imbalance, spread, and pack-voltage plausibility rules
- Fails closed on invalid required measurement data
- Groups failing samples into structured violation events with peak evidence
- Emits versioned JSON results with `PASS`, `FAIL`, or `NOT_EVALUATED`
- Generates self-contained HTML evidence reports with deterministic inline SVG plots
- Records SHA-256 input/config provenance
- Runs in Linux/Windows CI and publishes checked wheel/sdist release artifacts

BatteryLog deliberately ships **no universal battery safety thresholds**. Limits must come from the tested cell/pack specification, BMS strategy, operating state, and validation plan.

## Quick start

From a checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

For MDF/MF4 support:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[mf4]"
```

Compute metrics without activating engineering rules:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv
```

Run validation from YAML and generate JSON + HTML evidence:

```powershell
.\.venv\Scripts\batterylog.exe examples\sample_battery_log.csv `
  --config examples\validation.example.yaml `
  --json-out battery-result.json `
  --report battery-report.html
```

Completed analyses also emit canonical JSON to stdout.

## Input model

Canonical CSV input starts with a numeric, non-decreasing timestamp plus indexed cell-voltage and temperature channels:

```csv
timestamp_s,pack_current_a,pack_voltage_v,cell_1_v,cell_2_v,temp_1_c,temp_2_c
0,-25,7.89,3.95,3.94,28,27
1,35,7.26,3.68,3.58,48,46
```

Required canonical signals:

- `timestamp_s`
- one or more `cell_<n>_v` channels
- one or more `temp_<n>_c` channels

Optional scalar signals:

- `pack_current_a`
- `pack_voltage_v`

Vendor-specific names can be selected with explicit regex-based YAML signal mapping instead of renaming source files.

The pack-voltage/cell-sum rule must only be enabled when the selected cells represent the **complete series stack** on the same meaningful time basis as the pack-voltage measurement. Parallel branches, omitted cells, multiplexed channels, and forward-filled/ZOH data require topology-aware preparation.

Full input, mapping, MF4, data-quality, and comparison semantics are in [`docs/REFERENCE.md`](docs/REFERENCE.md).

## Validation rules

| Rule | Purpose |
| --- | --- |
| `CELL_OVERVOLTAGE` | cell voltage above configured maximum |
| `CELL_UNDERVOLTAGE` | cell voltage below configured minimum |
| `CELL_IMBALANCE_HIGH` | row-wise cell-voltage spread above limit |
| `TEMPERATURE_HIGH` | temperature above configured maximum |
| `TEMPERATURE_LOW` | temperature below configured minimum |
| `TEMPERATURE_SPREAD_HIGH` | row-wise temperature spread above limit |
| `PACK_CHARGE_OVERCURRENT` | charge-current magnitude above configured limit |
| `PACK_DISCHARGE_OVERCURRENT` | discharge-current magnitude above configured limit |
| `PACK_VOLTAGE_CELL_SUM_MISMATCH` | absolute pack voltage vs. complete series-cell sum above tolerance |

Rules are opt-in through numeric limits. With no active rule, BatteryLog computes metrics and returns `NOT_EVALUATED` instead of pretending that the log passed validation.

Example configuration:

```yaml
schema_version: 6

limits:
  cell_voltage:
    min_v: 2.8
    max_v: 4.2
    max_delta_v: 0.08
  temperature:
    min_c: -20
    max_c: 55
    max_spread_c: 12

event_detection:
  max_gap_s: 2.0

data_quality:
  mode: strict
```

The values above are illustrative, not recommended production limits.

## Results and evidence

Each completed analysis reports:

- measured extrema and row accounting
- effective limits and evaluated rules
- structured violation events with start/end/peak timestamps
- implicated signals, sample count, duration, and peak excursion
- signal-mapping metadata
- comparison policy
- result-schema version
- optional structured data-quality evidence

Current machine-readable result schema: **v8**. Historical frozen result schemas remain packaged for compatibility.

Validation status:

| Status | Meaning |
| --- | --- |
| `NOT_EVALUATED` | no engineering rule was active and no structured data-quality defect was recorded |
| `PASS` | at least one rule was evaluated and no rule/data-quality failure occurred |
| `FAIL` | at least one engineering-rule violation and/or structured data-quality defect occurred |

CLI exit codes are `0=PASS`, `1=FAIL`, `2=usage error`, `3=NOT_EVALUATED`, `4=runtime/input/output error`.

## HTML report

Reports are self-contained and include validation status, extrema, limits, violation evidence, provenance, and deterministic inline SVG plots.

![BatteryLog HTML validation report](docs/assets/report-preview.png)

Plot reduction is evidence-preserving: retained geometry is separate from PASS/FAIL evaluation, and structured violation intervals/peaks remain sourced from the analysis result.

See [`docs/REPORT_SERIES.md`](docs/REPORT_SERIES.md) for the plotting/downsampling contract.

## Real-data validation

BatteryLog v0.9.1 was exercised against the public CORA experimental 3P12S battery-pack dataset (DOI `10.34810/data2395`).

| Campaign metric | Result |
| --- | ---: |
| Parquet cycle files | 410 |
| Unique physical source rows | 30,187,165 |
| Branch-row analyses | 90,561,495 |
| BatteryLog streaming runs | 1,230 |
| Runtime errors | 0 |
| Independent direct-comparison parity | 1,230 / 1,230 |

The campaign used a **0.15 V illustrative software-validation threshold** for the pack/cell-sum rule; it is not presented as a universal engineering tolerance. The source also uses asynchronous acquisition with zero-order hold, which materially affects row-level interpretation.

Exact dataset hash, topology mapping, methodology, performance, limitations, and reproduction steps are in [`docs/REAL_DATA_VALIDATION.md`](docs/REAL_DATA_VALIDATION.md).

## Python API

```python
from batterylog import ValidationLimits, analyze_battery_log

limits = ValidationLimits(
    cell_min_v=2.8,
    cell_max_v=4.2,
    imbalance_max_v=0.08,
    temperature_max_c=55,
)

result = analyze_battery_log("test.csv", limits=limits)
print(result["validation_status"])
```

See [`docs/REFERENCE.md`](docs/REFERENCE.md) for configuration loading, event semantics, mapping, and compatibility details.

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/REFERENCE.md`](docs/REFERENCE.md) | CLI, config, canonical signals, MF4, schemas, event and engineering semantics |
| [`docs/REAL_DATA_VALIDATION.md`](docs/REAL_DATA_VALIDATION.md) | CORA real-data campaign and reproduction |
| [`docs/RESULT_SCHEMA_VERSIONING.md`](docs/RESULT_SCHEMA_VERSIONING.md) | result-contract versioning policy |
| [`docs/REPORT_SERIES.md`](docs/REPORT_SERIES.md) | report-series and downsampling contract |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | provenance and trust boundaries |
| [`docs/MF4_BENCHMARK.md`](docs/MF4_BENCHMARK.md) | MF4 memory/performance characterization |
| [`docs/RELEASING.md`](docs/RELEASING.md) | release procedure |

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,mf4]"
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q --cov=batterylog --cov-fail-under=95
```

CI covers Linux, Windows, supported Python versions, optional MF4 integration, package installation, and tagged release artifact checks.

## License and citation

BatteryLog is licensed under the [Apache License 2.0](LICENSE). Commercial, internal, research, and educational use are welcome subject to the license terms.

Citation metadata is available in [`CITATION.cff`](CITATION.cff); attribution information is recorded in [`NOTICE`](NOTICE).

Tagged releases publish wheel/sdist artifacts plus SHA-256 checksums through [GitHub Releases](https://github.com/CANWECAN/BatteryLog/releases).
