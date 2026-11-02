# Real-data characterization of the development failure models

This campaign checks the development analyzer against independently calculated
observations in physical battery measurements. It does not provide ground-truth
fault labels, sensor calibration, or validated safety limits. The data comes from
a laboratory battery pack driven by WLTP-derived current profiles; it is not an
instrumented production vehicle log.

## Source and eligibility

Source: de la Vega Hernández, Joaquín; Ortega Redondo, Juan Antonio; Riba Ruiz,
Jordi Roger. *Lithium-Ion Battery Pack Cycling Dataset with CC-CV Charging and
WLTP/Constant Discharge Profiles*. DOI: [10.34810/data2395](https://doi.org/10.34810/data2395).
The dataset is licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The source README documents three parallel 12S branches, positive charging
current, negative discharge current, asynchronous acquisition and zero-order hold.
The archive used here is pinned by its exact SHA-256:

`174fccb08a8d215a1a8b1dcf8a5daeb951819ec97b8d9ff8b7d4a013763e77a3`

The campaign selects complete cycles 125, 127, 196, 197, 229, 260, 268, 338,
343, 406 and 410. They cover the earlier ten-cycle campaign and one additional
WLTP cycle used for detailed examples. This is a named characterization subset,
not a random statistical sample or a sweep of all 410 files.

Each branch is mapped to 12 cell voltages, 24 top/bottom thermistors, its own
current and voltage, and elapsed source time. Full charge/discharge/standby
sequences are retained; no additional interpolation, smoothing, clipping or
physical outlier removal is applied. The references require strictly increasing
finite source times and stop if that contract is not met.

| Check | Evidence available in this source |
| --- | --- |
| Pack voltage versus series-cell sum | Branch and all 12 cell voltages; asynchronous row representation remains a limitation |
| Sustained cell imbalance | Complete per-branch cell-voltage inventory and timestamp spans |
| Temperature rise | Adjacent recorded thermistor values; source jumps and ZOH affect physical interpretation |
| Relative cell sag under load | Resting references and discharge episodes identified using the documented current sign |
| Balancing improvement / timeout | No directly logged balancing-active channel is mapped; deliberately remains NOT_EVALUATED |

The source `Semicycle` describes the test operating stage. It is not silently
converted into measured per-branch balancing hardware status. Balancing is not
inferred from cell-voltage changes.

## Sensitivity profiles

All profiles are illustrative software-characterization parameters. Their values
are not battery operating limits or calibrated fault thresholds.

| Profile | Imbalance V | Temperature rise degC/min | Excess sag V | Pack/cell-sum mismatch V |
| --- | ---: | ---: | ---: | ---: |
| sensitive | 0.02 | 5 | 0.01 | 0.15 |
| baseline | 0.05 | 10 | 0.025 | 0.30 |
| relaxed | 0.10 | 30 | 0.05 | 0.50 |

Common settings: imbalance duration 30 s; maximum observation gap 1 s;
temperature minimum pair interval 0.25 s; positive current direction charge;
resting current magnitude at most 0.05 A; discharge magnitude at least 2 A;
resting reference age at load onset at most 5 s; load settling time 0.5 s.
The resting-current setting selects a reference for a relative voltage observation;
it does not independently establish a zero-current calibration condition.

## Independent audit

The [campaign harness](../scripts/validation/validate_cora_failure_models.py)
computes voltage-spread spans and temperature-rise intervals with array run
segmentation, and sag with separately enumerated load episodes. It does not call
the production temporal collector to obtain expected observations.

For each run it compares model outcome, evaluated sample count, incomplete
interval count, event count, start/end/peak timestamps, peak values, sample counts
and the numeric measurement chain against the source rows. It separately checks
pack/cell-sum violating sample counts and excluded rows. JSON schema and semantic
validation are also run. Cycle 229 is repeated with 997-row chunks versus the
4096-row default, and its missing balancing status is explicitly tested.

Eight small tests anchor the reference arithmetic, exact-threshold behavior,
gap boundaries, absent/consumed resting references, timestamp rejection and
detection of a deliberately changed reported peak. They do not replace the
external source-data campaign.

## Campaign results

The [machine-readable summary](cora_failure_models_summary.json) records the
measurement campaign against analyzer base commit
`7310c0d91eee2085dbf8a1282628f573841beb33`.

| Metric | Result |
| --- | ---: |
| Complete source cycles | 11 |
| Unique source rows | 978,674 |
| Physical branches per cycle | 3 |
| Threshold profiles | 3 |
| Branch/profile runs | 99 |
| Independent model-event chain matches | 1,242,226 / 1,242,226 |
| Runtime or arithmetic-audit errors | 0 |
| Alternate-chunk parity checks | 3 / 3 |
| Missing-balancing evaluations correctly NOT_EVALUATED | 6 / 6 |
| Harness runtime on this Windows host | 584.17 s |

Event totals count repeated threshold-profile observations, not unique physical
failures. There are 33 branch runs per profile.

| Profile | Sustained imbalance PASS / FAIL / NOT_EVALUATED | Imbalance events | Temperature events | Relative sag PASS / FAIL / NOT_EVALUATED | Sag events |
| --- | --- | ---: | ---: | --- | ---: |
| sensitive | 1 / 32 / 0 | 557 | 544,602 | 0 / 18 / 15 | 1,110 |
| baseline | 14 / 19 / 0 | 180 | 370,072 | 0 / 18 / 15 | 775 |
| relaxed | 23 / 10 / 0 | 63 | 324,410 | 0 / 17 / 16 | 457 |

Temperature rise is FAIL in all 33 branch runs in all three profiles. Increasing
the threshold changes event counts but does not remove the source-value problem.

The 15 capacity-check branches do not reach the illustrative 2 A discharge
eligibility condition, so their sag outcome is NOT_EVALUATED. In the relaxed
profile one additional branch has qualified observations without a sag event,
but also incomplete load intervals; it correctly remains NOT_EVALUATED. A lack
of events therefore does not silently become PASS.

The external references and existing model/MF4 tests passed together:
131 tests. Ruff lint/format, package-wide mypy, dependency consistency and diff
checks also passed. The raw archive digest was checked again after the main
campaign, and a final cycle-229 smoke run exercises the harness's final digest
check without changing the source measurements.

## Three traceable observations from cycle 229, branch 1

These are the largest events for the baseline profile, not independently confirmed
physical failures. Elapsed times refer to the full source cycle.

| Observation | Recorded evidence | Interpretation boundary |
| --- | --- | --- |
| Sustained imbalance | 5141.325–5190.282 s; 154 samples over 48.957 s; peak at 5171.717 s: cell 5 = 3.375 V, cell 6 = 3.096 V, spread = 0.279 V | Confirms sampled spread beyond the illustrative 0.05 V / 30 s condition; does not identify its cause |
| Relative sag | Resting reference at 1538.842 s; load onset at 1539.166 s; peak at 1546.203 s with -6.127 A: cell 6 drops from 4.035 V to 3.374 V, drop 0.661 V, median cell drop 0.421 V, excess 0.240 V | An observed difference from peer cells; not internal resistance or proof of a bad connection |
| Temperature-channel jump | 2246.984–2247.305 s: thermistor 10 changes from 2.220 to 655.280 degC in 0.320676 s, recorded slope about 122190.628 degC/min | An implausible source value is retained and exposed; this is not evidence of physical thermal runaway |

The implausible thermistor value is finite, so structural numeric data-quality
checks do not classify it as a malformed sample. Temperature-rate flags in this
source therefore combine logged sensor/acquisition behavior with potential
thermal changes. Raising a slope threshold does not validate the source values.

The CLI demo processes all 38,392 cycle-229 branch-1 rows. Under the
baseline profile it produces 16 sustained-imbalance events, 5,046 temperature-rise
events and 36 relative-sag events. JSON semantic validation passes and the
self-contained HTML includes all three model outcomes. The high event count is
useful evidence of report behavior, not a count of confirmed physical defects.

## Reproduce and view the technical demo

Run from a development checkout installed in its environment. PyArrow is an
external validation dependency; it is not added to BatteryLog's runtime extras.

~~~powershell
.\.venv\Scripts\python.exe -m pip install pyarrow==25.0.1
.\.venv\Scripts\python.exe scripts\validation\validate_cora_failure_models.py `
  C:\path\to\doi-10.34810-data2395.zip `
  --output C:\path\to\new-campaign-folder
~~~

Use a new output directory. The harness verifies the pinned archive digest and
emits `summary.json`, per-run records, source-column/member-hash inventory,
selected event chains, and a canonical cycle-229 branch-1 CSV with its source
manifest and illustrative configuration. The raw data and large HTML/JSON
outputs are kept outside git.

~~~powershell
.\.venv\Scripts\python.exe -m batterylog `
  C:\path\to\new-campaign-folder\demo\cycle229-P1.csv `
  --config C:\path\to\new-campaign-folder\demo\illustrative-models.yaml `
  --json-out C:\path\to\new-campaign-folder\demo\result.json `
  --report C:\path\to\new-campaign-folder\demo\report.html
~~~

The demo is expected to return FAIL, exit code 1, under these illustrative
parameters. Its HTML can also be generated from the desktop single-file mode.
Interpret the evidence as measured log behavior: a threshold crossing does not
identify a faulty cell, a bad connection, thermal runaway, or defective sensors.
