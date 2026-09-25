# Real-data validation

This document records external-data characterization performed against the released
BatteryLog **v0.9.1** package. It is evidence that the software paths were exercised on
large physical battery-pack measurements; it is **not** a certification of BatteryLog,
the source dataset, or any engineering threshold.

## Dataset

- Dataset: *Lithium-Ion Battery Pack Cycling Dataset with CC-CV Charging and WLTP/Constant Discharge Profiles*
- Authors: Joaquín de la Vega Hernández, Juan Antonio Ortega Redondo, Jordi Roger Riba Ruiz
- Version: 1.0
- DOI: `10.34810/data2395`
- License: CC BY 4.0
- Exact downloaded ZIP SHA-256:
  `174fccb08a8d215a1a8b1dcf8a5daeb951819ec97b8d9ff8b7d4a013763e77a3`
- ZIP size: 1,079,065,782 bytes
- Parquet files: 410
- Source rows: 30,187,165
- Columns per Parquet file: 132

The dataset describes a physical 3P12S pack: three parallel branches, each containing
12 cells in series. The dataset documentation states that acquisition is asynchronous
and uses zero-order hold (ZOH) between records.

## Adapter and topology mapping

The external validation harness is
[`scripts/validation/validate_cora_data2395.py`](../scripts/validation/validate_cora_data2395.py).
PyArrow is used only by the harness to read the external Parquet files; it is not a
BatteryLog runtime dependency.

Each physical branch is analyzed as one complete 12S series stack:

- `Voltage_Cell_P#S1 ... Voltage_Cell_P#S12` -> `cell_1_v ... cell_12_v`
- 24 top/bottom branch thermistors -> `temp_1_c ... temp_24_c`
- `Current_Actual_P# [A]` -> `pack_current_a`
- `Voltage_Actual_P# [V]` -> `pack_voltage_v`
- source timestamps -> elapsed `timestamp_s` within each cycle

No extra interpolation or resampling is performed by the validation harness. The source
dataset's own ZOH behavior therefore remains visible to BatteryLog.

The full campaign uses 25,000-row loader chunks and
`data_quality.mode = exclude_invalid_rows`. The pack-voltage/cell-sum threshold is
**0.15 V solely as an illustrative software-validation threshold**. It is not claimed as
a safe, recommended, or universal battery engineering limit.

## Full streaming campaign

The campaign processed every row of all 410 Parquet cycle files through BatteryLog's
measurement-loader streaming engine, once for each of the three physical branches.

| Metric | Result |
| --- | ---: |
| BatteryLog version | 0.9.1 |
| Source files | 410 |
| Branch analysis runs | 1,230 |
| Unique source rows | 30,187,165 |
| Branch-row analyses | 90,561,495 |
| Successful runs | 1,230 |
| Runtime errors | 0 |
| Rows excluded | 0 |
| Structured data-quality events | 0 |
| Direct-comparison parity | 1,230 / 1,230 |

For every successful branch run, the harness separately calculated the documented
binary64-guarded `abs(pack_voltage - sum(cells)) > 0.15 V` condition. It compared that
calculation with BatteryLog's total violation sample count, excluded-row count, and
recorded mismatch peak. All 1,230 runs matched.

Under the illustrative 0.15 V threshold:

| Outcome | Runs |
| --- | ---: |
| PASS | 43 |
| FAIL | 1,187 |
| NOT_EVALUATED | 0 |
| Violation events | 509,501 |
| Violating samples | 17,798,585 |

These PASS/FAIL counts characterize this test threshold against this acquisition method.
They must not be interpreted as a health assessment of the tested cells or as evidence
that 0.15 V is an appropriate production limit.

### Dataset-category breakdown

| Category | Branch runs | PASS | FAIL | Branch rows | Events | Violating samples |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Capacity / complete | 207 | 43 | 164 | 26,190,510 | 303 | 456 |
| Capacity / partial | 138 | 0 | 138 | 13,470,165 | 3,508 | 8,748,555 |
| WLTP / complete | 651 | 0 | 651 | 39,636,774 | 497,561 | 813,838 |
| WLTP / partial | 234 | 0 | 234 | 11,264,046 | 8,129 | 8,235,736 |

The largest observed absolute branch-voltage/cell-sum mismatch was approximately
**10.177 V**, in cycle 46 branch 1, a file explicitly labeled `partial_data`.

## Packaged CLI cross-check

A separate packaged-CLI campaign was run before the full streaming sweep. Ten complete
cycles were selected across the dataset timeline: five WLTP cycles and five capacity
checks. Each was split into three physical branches and processed by the installed
v0.9.1 CLI.

- Cycle files: 10
- CLI branch runs: 30
- Selected source rows: 401,931
- Branch-row analyses: 1,205,793
- CLI runtime errors: 0
- Direct-comparison parity: 30 / 30
- PASS at the illustrative threshold: 7
- FAIL at the illustrative threshold: 23
- Violation events: 12,016
- Violating samples: 19,435

Cycle 229 was additionally exercised with JSON and self-contained HTML report output.
All 16,365 selected WLTP rows per branch were processed, and the pack-voltage/cell-sum
plots and structured mismatch evidence were generated successfully.

## Performance characterization

Host used for this campaign:

- Windows 11 Pro
- AMD Ryzen 5 7500F, 6 cores
- 15.7 GiB physical RAM
- Python 3.13.14
- BatteryLog 0.9.1
- PyArrow 25.0.1
- pandas 3.0.6
- NumPy 2.5.3

The 1,230 BatteryLog analysis calls consumed **421.03 s** in aggregate. The full harness,
including Parquet decoding, canonical branch construction, comparison cross-checks, and
result serialization, completed in approximately **450.54 s**.

Per branch-run BatteryLog analysis time:

- median: 0.292 s
- p95: 0.589 s
- maximum: 0.858 s

These are host-specific characterization numbers, not CI timing guarantees.

## Important observations and limits

The dataset contains finite but physically implausible temperature values, including
values around 655 degC in some channels. Because such values are finite numeric samples,
they are not structural `data_quality` defects under BatteryLog's current contract.
A configured temperature engineering rule, source-specific cleaning policy, or future
plausibility rule is required to classify them semantically.

Large pack/cell-sum outliers also occur. The source documentation explicitly describes
asynchronous acquisition with ZOH, so a row does not prove that every source sensor was
sampled simultaneously. The mismatch results therefore characterize the software and
the source's row-level representation; they do not establish a universal sensor-tolerance
distribution.

This campaign specifically provides evidence for:

- large real-data ingestion through the streaming analysis engine
- 12S complete-series pack/cell-sum arithmetic
- chunked event generation across many cycle files
- structured result stability under high event counts
- direct sample-count and peak-evidence parity

It does **not** prove:

- universal correctness for all EV pack topologies or acquisition systems
- that the 0.15 V threshold is an engineering requirement
- physical simultaneity of ZOH-aligned source channels
- correctness of rules that were not enabled in this campaign
- bounded memory under arbitrarily large single-result event lists

## Reproduction

Create an isolated environment so the released package, rather than a development
checkout, is the analyzer under test. Install BatteryLog v0.9.1 and a Parquet reader,
then run:

~~~powershell
python -m venv .cora-validation
.\.cora-validation\Scripts\python.exe -m pip install `
  https://github.com/CANWECAN/BatteryLog/releases/download/v0.9.1/batterylog-0.9.1-py3-none-any.whl `
  pyarrow==25.0.1

.\.cora-validation\Scripts\python.exe `
  scripts\validation\validate_cora_data2395.py `
  C:\path\to\doi-10.34810-data2395.zip `
  --output C:\path\to\validation-output `
  --threshold 0.15 `
  --chunk-rows 25000
~~~

Verify the downloaded dataset hash before comparing results. Runtime numbers can vary
substantially by storage, CPU, Python, pandas, NumPy, and PyArrow versions.
