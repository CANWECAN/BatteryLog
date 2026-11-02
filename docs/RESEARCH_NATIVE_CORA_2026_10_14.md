# Native verification and CORA temporal context — 2026-10-14

The Windows repeat matched the cloud precharge campaign. Prepared CORA
Cycle 229 data does not justify selecting a production temperature window:
all three investigated endpoint windows increased exceeding-row counts.
Sag coverage limitations were confirmed in this subset. No Core decision,
threshold, schema, package or public repository change was made.

## Source and isolation

- Environment: Windows 11, Python 3.13.14, NumPy 2.3.5, pandas 2.2.3 and asammdf 8.8.27.
- Baseline: 10773ac71819aa6051b14cc879d0c63703ce3ce3, tree 4af65d61e2889984510fb3e9740eeefb5b15c804; hosted CI 38541248331 passed.
- Helper: `batterylog_research/cora_temporal_review.py`. It requires finite recorded values, strictly increasing time and the exact prepared 12-cell/24-temperature layout. Full input arrays are held in memory; incompatible input is rejected.

## Native verification

- Baseline suite: 2,755 passed, two skipped, nine warnings; Core coverage 96.67%.
- Focused temporal/helper tests: 36 passed, including 14 new cases.
- Suite including the helper: 2,769 passed, two skipped, nine warnings; Core coverage 96.67%. Real Tk was required.
- Whole-tree Ruff and Core mypy (48 files) passed with the required typing stubs. Dependency consistency passed.
- Native and hosted counts describe separate environments.

## Native severe precharge repeat

Command: python -m batterylog_research.precharge_stress --random-cases 5000
--seed 20261014 --output batterylog_research/native_precharge_stress_results_20261014.json

Exact SHA-256 hashes of curve reviewer, capture reviewer and stress harness
match the saved cloud run. Random/scaling summaries and every resource-profile
count, source-immutability check and serialized-result size match.

- 5,000 random captures, 1,022,061 rows, 39,018 active spans.
- 75,402 reviewed samples and 48,405 manufactured deviations.
- 50 repeated-call checks, 396 source-slice comparisons.
- 343 scaling combinations, 1e-300 through 1e300.
- Total campaign wall time: 76.61 s. Resource workers ran sequentially.

| Native profile | Rows | Reviewed samples | Review time |
|---|---:|---:|---:|
| One full span | 1,000,000 | 999,999 | 9.14 s |
| One full span | 5,000,000 | 4,999,999 | 46.57 s |
| 1,000 spans | 1,001,000 | 1,000,000 | 9.36 s |
| 500,000 spans, limit 1,000 | 1,000,000 | Rejected; zero curve calls | 0.34 s |
| Explicit limit 20,000 | 100,000 | 60,000 | 1.70 s |

Native peak_process_rss_mib is null: this unchanged harness uses resource,
which is unavailable on Windows. No native peak-memory or cross-host speed
claim is inferred. Cloud memory results remain a separate measurement.
The software campaign does not supply physical fault labels or HIL evidence.

## CORA data and provenance

- DOI: 10.34810/data2395. The local source README identifies CC BY 4.0 and
  authors Joaquin de la Vega Hernandez, Juan Antonio Ortega Redondo and
  Jordi Roger Riba Ruiz, Universitat Politecnica de Catalunya.
- Dataset: Lithium-Ion Battery Pack Cycling Dataset with CC-CV Charging and
  WLTP/Constant Discharge Profiles. The README describes asynchronous
  acquisition and zero-order hold; row timestamps do not prove channel freshness.
- Input: prepared Qtzl_Cycle_229_WLTP_WLTP_P1/P2/P3.csv only. Each contains
  16,365 WLTP rows: 49,095 branch-row observations representing 16,365 source
  timestamps, not independent packs or 33 whole-cycle model runs.
- Historical preparation records identify 38,392 rows in the original cycle,
  with charging/standby rows excluded from these CSVs. This run did not rehash
  the original archive or rerun the earlier 11-cycle / 99-run campaign.
- All three input CSV SHA-256 hashes were checked before/after review.
  Input files and recorded extreme values were preserved.
- A mapped precharge state/DC-link channel is absent from the prepared column
  contract. This does not establish absence in the original dataset.
  Semicycle labels were not converted into measured hardware state.
- Configuration matches the historical baseline: max gap 1 s; temperature
  10 degC/min with minimum interval 0.25 s; sag positive direction charge,
  excess 0.025 V, discharge load at least 2 A, baseline abs current at most
  0.05 A, reference age at most 5 s, settling 0.5 s.

## Temperature findings

All branches share median row spacing 0.319625 s and no gap above 1 s.
Per-sensor median intervals between recorded changes range from about
1.60–10.56 s. Repeated adjacent values comprise roughly 86.65–97.34%,
depending on the sensor. These are observed value-change statistics, not
measured sensor refresh periods. All 72 recorded temperature channels are
compatible with a 0.01 degC candidate grid using a declared 0.00004 degC
tolerance; this does not establish hardware resolution or calibration.

The table counts rows with at least one sensor above 10 degC/min.
Window endpoints are original samples in the same contiguous block; no
interpolation or outlier removal is performed. Counts are not event counts.

| Branch | Adjacent | 1 s endpoint window | 2 s | 5 s |
|---|---:|---:|---:|---:|
| P1 | 2,402 | 6,939 | 9,139 | 5,453 |
| P2 | 2,302 | 6,737 | 9,104 | 6,117 |
| P3 | 2,309 | 6,387 | 8,552 | 6,574 |

Adjacent eligibility is 16,364 rows per branch; window eligibility is
16,361 / 16,358 / 16,349. Independent adjacent counts match Core sample counts.
The higher counts are compatible with one recorded jump influencing several
trailing windows. Neither lower peaks nor larger/smaller counts demonstrate
better fault detection. Previously tested short genuine pulses can be lost
in a wider window.

P1 maximum is 655.280029 degC (temp_10_c, CSV row 7,023, elapsed 2,247.30482 s).
P3 maximum is 655.309998 degC (temp_22_c, row 3,051, elapsed 976.287164 s).
P2 maximum is 37.680000 degC. Extremes remain in every calculation, and windowing
does not solve their plausibility. There are no fault labels available to this
review; these alarms are not reported as proven false alarms.

## Sag findings

Independent load tracing matches Core evaluated-sample counts. Load episodes
and Core incomplete_intervals are different accounting units; the table
records both rather than defining them as universally equivalent.

| Branch | Load episodes | No reference | Stale reference | Available reference | Core eligible samples | Core incomplete intervals | Core status |
|---|---:|---:|---:|---:|---:|---:|---|
| P1 | 98 | 26 | 34 | 38 | 1,301 | 60 | FAIL |
| P2 | 98 | 26 | 33 | 39 | 1,222 | 60 | FAIL |
| P3 | 103 | 31 | 37 | 35 | 1,046 | 68 | NOT_EVALUATED |

One P2 episode has an available reference but no sample after settling.
Across branches 188/299 load episodes have no eligible observations.
P3 has zero sag events but 68 incomplete intervals: the absence of PASS is
consistent with insufficient coverage and is not proof of failed selectivity.

Available references have median observed low-current spans of
2.884 / 4.168 / 2.236 s for P1/P2/P3. Respectively 4/2/4 available references
come from a single low-current row (zero observed span). These durations do
not prove electrochemical relaxation. Adding a minimum-rest gate would
reduce coverage; it needs a declared purpose and evaluation before adoption.

## Decision and next bounded work

1. Keep the production estimator unchanged. Inspect original acquisition/
   sensor mapping and add event-level source plausibility context before
   choosing a temperature window.
2. Use the measured sag missing/stale/reference-duration context to explain
   coverage. Do not silently turn incomplete review into PASS or add a
   minimum-rest threshold based on this one WLTP subset.
3. Real precharge assessment still needs exported current, pack/DC-link
   nodes, state timing and a justified reference. Synthetic agreement does
   not replace that evidence.

Raw evidence: `batterylog_research/cora_cycle229_temporal_results_20261014.json`
and `batterylog_research/native_precharge_stress_results_20261014.json`.
The campaign does not establish live-CAN/HIL or physical fault-detection performance.

## Hosted source closure

Draft PR #7: https://github.com/CANWECAN/BatteryLog-Research/pull/7.
After retaining the concurrent base's native evidence, source commit
8daa703b6ba0c93d189e373beab4b2cfb12bcde8 (tree
4a6162551318657be1df3615c8de5c136d9632d0) has identical code/test blobs to the
native-tested f97dc6a source.

Exact-source CI 38578431972 completed SUCCESS with all 12 jobs passed:
https://github.com/CANWECAN/BatteryLog-Research/actions/runs/38578431972.

Linux 3.11/3.12/3.13: 2,620 passed / 2 skipped / 9 warnings, coverage 96.23%.
Linux 3.14: same counts, coverage 96.02%. Minimum runtime: 2,620 passed /
2 skipped / 10 warnings, coverage 96.23%. Hosted Windows: 2,618 passed /
4 skipped / 9 warnings, coverage 96.21%. Package and all five MF4 jobs passed;
inspected Linux 3.12/3.13 and Windows MF4 logs each show 175 passed.

Source/data hashes and raw native results are unchanged by this documentation
closure. Any documentation-triggered CI run is a separate record. Reference
ages above use row timestamps; they do not measure channel acquisition age.
No production estimator selection, threshold change, merge or release.
