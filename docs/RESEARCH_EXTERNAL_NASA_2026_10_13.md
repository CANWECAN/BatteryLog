# Internet-source NASA-origin measurement campaign — 2026-10-13

Analyzer baseline: `0e1ba22c81be571e702308afe884b69e1fa25e9b`.
Private Research branch: `audit/cloud-balancing-spread-20261012`.
The campaign ran in a cloud environment.

## Provenance and scope

NASA's [Li-ion Battery Aging Datasets portal](https://data.nasa.gov/dataset/li-ion-battery-aging-datasets)
describes battery-terminal voltage in V, measured current in A, temperature in
degrees C and per-operation time in seconds. Its current portal provides no data
resource download. CORA's original download API responded with a bot-check HTML
page, so it was not used and the challenge was not bypassed.

The downloaded MAT files came from an independent public
[GitHub mirror](https://github.com/devhaaana/nasa-battery-aging-dataset/tree/c881323a09dfa4c8f7405945ac7c81480b5f4307/data),
pinned to commit `c881323a09dfa4c8f7405945ac7c81480b5f4307`.
Both mirror Git blob hashes and downloaded SHA-256 digests were checked.
This establishes byte identity with that mirror, not official NASA file
authentication. The portal does not specify a data license; no raw MAT files or
derived measurement CSVs are redistributed by this commit.

| File | Bytes | Source operations tested | Measurement rows | Excluded rows | Temperature events audited |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0005.mat | 15,956,874 | 338 | 591,458 | 0 | 170 |
| B0018.mat | 8,502,218 | 266 | 314,676 | 2 | 44 |
| Total | 24,459,092 | 604 | 906,134 | 2 | 214 |

Source SHA-256:
- B0005: `0eae4585baf3f200c09fe24c5ab884f1889679fc75206ca1aa19da704104f0b0`
- B0018: `d1e6c923a43ea1c9666b3a90bbb521757a067fd60b4d17dbfaa49c50b179da69`

All 304 charge and 300 discharge operations in these two files were used.
Impedance operations have different signal semantics and were not fed into
the voltage/current/temperature analyzer. Each operation is analyzed separately;
no cycle stitching, resampling, clipping, smoothing, gap-filling or fabricated
pack channels are applied. The adapter retains original per-operation elapsed
time and original NaN values.

## Executed checks

- Independent raw-array counts for cell undervoltage, overvoltage and high
  temperature; every analysis matched.
- Independent temperature-rise reference: statuses, eligible samples, event
  counts, start/end/peak times, rates and before/after measurement evidence.
  All 214 returned events matched.
- Complete result-v9 Schema and semantic validation on all 604 full-frame runs.
- Two streaming partitions (997 and 4,096 rows) compared exactly with each
  full-frame result on every operation.
- First and last charge/discharge operation in each cell also used partitions
  of 1, 7, 1,024 and 65,536 rows. Total exact dictionary matches: **1,240/1,240**.
  These cell operations are smaller than 65,536 rows; that size tests the
  single-chunk path, not a large-boundary crossing. The previous synthetic
  65,542-row regression covers an actual 65,536 boundary.
- Eight selected operations checked missing balancing/unloaded/contactor/precharge
  status inputs. All five unavailable evaluation codes in each run correctly
  stayed NOT_EVALUATED; hardware states were not inferred from charge/discharge.
- Four new reference/adapter/identity tests passed. The combined focused
  reference/distribution run passed 19 tests; whole-tree Ruff check/format passed.
- Campaign time: **107.575 s** on this host, excluding downloads and source
  inspection. This is not a performance SLA.

These checks exercised the analyzer's DataFrame and streaming-engine paths with
a MAT-to-canonical adapter. They did not constitute a packaged CLI, native GUI,
MF4 ingestion or coverage-matrix run.

## The non-finite source record

B0018 source operation 115 is a 993-row charge operation. Source sample indices
940 and 991 (zero-based) contain NaN in Voltage_measured, Current_measured and
Temperature_measured: two affected rows, six non-finite source values.

The campaign passed the unmodified rows to `exclude_invalid_rows`; BatteryLog
reported exactly two excluded rows. Strict mode was separately checked and
rejected that operation. The temperature reference does not bridge across these
invalid rows.

## Threshold outcomes are not test failures

The illustrative profile used cell voltage 2.7–4.2 V, temperature ceiling 45 C,
temperature-rise ceiling 1 C/min, minimum pair interval 0.1 s and maximum gap
60 s. These are software probes, not validated engineering requirements.

All 604 analyses returned FAIL under that profile. Independent threshold counts:
504 undervoltage samples, 442,884 overvoltage samples and zero samples above
45 C. Many charge samples sit just above the illustrative 4.2 V threshold;
the dataset also includes discharge observations below 2.7 V. No thresholds
were tuned merely to obtain PASS.

No unexpected software runtime error or reference/parity mismatch occurred.
A FAIL outcome here means the configured observation conditions were crossed,
not that a cell was physically faulty or that the validation campaign failed.

## Boundary and reproduction

The source contains independent single-cell experiments. It cannot validate
peer-relative voltage steps, inter-cell imbalance, real balancing hardware,
pack topology, synchronization or labeled physical fault-detection accuracy.
It also does not validate SOH/RUL estimation, which this campaign does not perform.

Install SciPy only in the external validation environment; no BatteryLog runtime
dependency was added. From a Research checkout:

```bash
python -m batterylog_research.nasa_cloud_validation \
  --data-dir /path/to/source-files \
  --output /path/to/new-results-directory \
  --download
python -m pytest -q tests/test_research_nasa_cloud_validation.py
```

The source downloads are hash-pinned; output must be a new directory.
The campaign emits aggregate `summary.json` and per-operation `operations.json`.
The aggregate observed result is retained in
`batterylog_research/nasa_cloud_summary_20261013.json`.
Production analysis algorithms are unchanged.
