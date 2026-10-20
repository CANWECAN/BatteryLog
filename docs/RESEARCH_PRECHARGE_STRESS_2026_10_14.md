# Severe precharge software stress campaign

Private Research, 14 October 2026. Original campaign: cloud Linux; native
Windows follow-up is recorded below. Base remote commit
`7e2adda5002affab475984ef647051c8c5321d2e`, tree
`ad7cbca2e50816ae0d01267e0ba9a1e3aab00db1`, matched the clean local tree.
The predecessor closure CI succeeded.

## Reproduced defects and corrections

1. **Unknown phase rounded into a known state.** On this host,
   `np.finfo(np.longdouble).nmant` reports 63. A value immediately above one is unknown in the
   original array but becomes one when cast to binary64. The base capture
   observer reported zero unknown samples, one observed activation and one
   covered interval for three such unknown rows. Classification now happens
   before conversion: only original zero/one values are known; other values
   remain unknown internally. Original source arrays are not modified.
2. **Descending source time hidden by conversion.** Original `int64` timestamps
   `[2**53 + 1, 2**53]` collapse into equal binary64 values. The base accepted
   the descending source as an unobserved activation instead of rejecting its
   time ordering. Original values are now checked by direct comparison before
   relying on binary64 intervals. This avoids integer subtraction overflow too.

Both corrections apply to the shared Research input boundary. Core code,
statuses, thresholds, schema and package configuration remain unchanged.
Calculations still use binary64; ascending distinct timestamps that collapse
to duplicates lose qualification conservatively. No missing timing is invented.
Twelve new regression cases cover both interfaces, signed/unsigned integer and
extended-precision time, original unknown phase and retained earlier deviations.

## Independent evidence

The executable `batterylog_research.precharge_stress` uses a separate manual
row scanner. It does not call the production partition, validation or comparison
helpers to calculate its expected results. Its oracle deliberately covers
constant reference bands; the existing independent linear-reference tests
remain separate. The binary64 comparison guard follows the declared 8-epsilon
policy. This is neither exhaustive proof nor a general physical-fault oracle.

With seed **20261014**, the final campaign verified:

- 5,000 randomized captures: **1,022,061 rows and 39,018 active spans**.
  Injected duplicates, gaps, unknown phase, invalid current/pack/bus samples,
  signed current and voltage-gap deviations. Expected source ranges, observed
  onsets, coverage, counts, peaks, horizon brackets and example indices matched.
  75,402 samples were eligible for review; 48,405 manufactured deviations.
- 50 identical repeat checks and **396 separately reviewed source slices**,
  including conversion back to global example indices: all matched.
- **343** controlled time/current/voltage scale combinations, using exponents
  -300, -150, -10, 0, 10, 150 and 300. Expected coverage and one manufactured
  current deviation per case were preserved.
- Read-only inputs, complete source/envelope fingerprints and strictly finite
  JSON checked for every successful comparison and large profile.

No discrepancy remained in this tested campaign after the two fixes. Counts of
manufactured deviations are not failure detections or false-alarm rates.

## Isolated resource profiles

Each profile ran sequentially in a fresh Python process with a 180 s timeout.
Source sampling uses exact binary 1/1024 s increments. The constant synthetic
envelope is 0–2 A current magnitude and 0–0.2 signed voltage-gap fraction;
pack/bus are 100/90 V, with 3 A injected every seventh source row. These settings
exercise software workload, not a physically justified precharge reference.

| Profile | Rows | Reviewed samples | Covered reference intervals | Review wall s | Peak process RSS MiB | Serialized result bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Single full span | 1,000,000 | 999,999 | 1 | 10.94 | 245.75 | 1,355 |
| Single full span | 5,000,000 | 4,999,999 | 1 | 56.33 | 872.92 | 1,363 |
| 1,000 full spans, declared limit 1,000 | 1,001,000 | 1,000,000 | 1,000 | 11.22 | 197.93 | 1,010,257 |
| 500,000 spans, declared limit 1,000 | 1,000,000 | rejected | n/a | 0.46 | 197.89 | 84 error-control bytes |
| 20,000 short spans, explicitly raised limit 20,000 | 100,000 | 60,000 | 20,000 | 2.35 | 166.31 | 16,742,695 |

The over-limit worker replaces the curve dispatcher with a function that raises
if called. The observed rejection occurred with **zero curve reviews**, without
returning a truncated capture. Accepted profiles matched independently generated
sample/span/deviation counts. Sources were unchanged.

Wall time covers the review call only, excluding fixture generation, oracle,
hashing and JSON serialization. Peak RSS covers the entire worker, including
imports, source allocation, review, fingerprints and JSON. These are single
measurements on this cloud host, not latency guarantees, leak freedom, native-platform
benchmarks or a streaming/constant-memory claim. Large output at an explicitly
raised span limit remains a caller-visible resource cost.

Final extended campaign wall time: **93.21 s**, including controller checks and
worker launches. Runtime: Python 3.12.14, NumPy 2.3.5, Linux x86_64. Raw results
and exact source SHA-256 values are in
`batterylog_research/precharge_stress_results_20261014.json`.
An earlier four-profile run also passed; the table records the final extended
run, which includes the five-million-row profile.

## Verification and reproduction

Final focused tests: **143 passed**, including the 12 new conversion regressions,
35 capture tests, 40 curve tests and 56 existing Core precharge tests.
Ruff, Core mypy and dependency consistency passed. The original seven generated
curve observations remain unchanged except for their refreshed script hash.
Full hosted CI on the saved source passed; closure evidence is below.

```sh
python -m batterylog_research.precharge_stress --output /path/to/new-stress.json
python -m pytest -q tests/test_research_precharge_numeric_precision.py tests/test_research_precharge_capture_review.py tests/test_research_precharge_curve_review.py tests/test_precharge_current.py
```

Output creation is exclusive. Do not rerun with a path already containing a
report. The saved raw result hashes identify the exact observer/harness bytes;
timings may vary on rerun. The independent oracle is restricted to the stated
constant-band workload. GUI, arbitrary file ingestion, physical commissioning,
live CAN/HIL and real-fault labels remain separate verification scopes.

## Hosted closure

Draft [PR #6](https://github.com/CANWECAN/BatteryLog-Research/pull/6) is stacked
on the capture-review branch. Source commit
`52fad8dd78bf315dc8a41a0089cba0b5a841a31e`, tree
`c11a643c270c2eae0c2a70000b572094b25d976b`, matched the locally verified tree.
[Run 38539475180](https://github.com/CANWECAN/BatteryLog-Research/actions/runs/38539475180)
completed SUCCESS with all 12 jobs passing: Linux Python 3.11–3.14, minimum
runtime, Windows, five MF4 combinations and package verification.

Inspected Linux 3.11/3.12/3.13 each report 2,606 passed, two skipped, nine warnings
and 96.23% coverage. Minimum runtime has the same pass/skip counts and coverage
with ten warnings. Windows 3.13 reports 2,604 passed, four skipped, nine warnings
and 96.21% coverage. Inspected Linux 3.12 and Windows MF4 jobs each report
175 passed. The existing 95% coverage gate passed.

The large stress campaign ran on the cloud host separately from CI; its exact
observer/harness hashes are retained in the raw result. This closure edits
documentation only, retaining the successfully verified code/test/result blobs.
Closure-triggered CI is separate from this inspected source run. Native-platform and physical-field validation are separate measurements.

## Native Windows follow-up — 2026-10-14

The Windows campaign uses source 10773ac71819aa6051b14cc879d0c63703ce3ce3.
Earlier cloud-only results and this native result refer to their specifically
identified revisions and environments.

Focused suite: **143 passed**. Full native suite with required desktop widgets
and actual MF4 installed: **2,755 passed / 2 skipped / 9 existing warnings** in
160.46 s; Core coverage **96.67%**, above the unchanged 95% gate. Whole-tree
Ruff check/format, Core mypy (48 files) and dependency consistency passed.

Windows Python 3.13.14 / NumPy 2.3.5 completed 5,000 random cases, 343 scaling
combinations and all five sequential isolated resource profiles. Source hashes,
random totals, scale totals and resource-profile logical fields including counts,
bounds/rejections and serialized sizes match the cloud result exactly. Source
fingerprints remained unchanged. This is a cross-platform software check, not
OEM or physical commissioning validation.

| Native Windows profile | Review wall s | Reviewed samples | Covered intervals |
| --- | ---: | ---: | ---: |
| 1,000,000-row full span | 9.03 | 999,999 | 1 |
| 5,000,000-row full span | 46.28 | 4,999,999 | 1 |
| 1,000 full spans | 9.16 | 1,000,000 | 1,000 |
| 500,000 spans above declared bound | 0.34 | rejected before any curve review | n/a |
| Explicitly allowed 20,000 short spans | 1.68 | 60,000 | 20,000 |

Complete Windows campaign wall time was 76.13 s. Timings retain the original
review-only/whole-campaign scopes. The harness reports **null peak RSS on Windows**
because its resource-based peak measurement is unavailable there; no Windows
peak-memory value or cross-host memory parity is inferred. Linux RSS figures
above remain historical Linux-only measurements.

Saved native raw results, checksum identities, comparison flags and verification
summaries: `batterylog_research/precharge_native_windows_results_20261014.json`.
No implementation or test change was needed. This evidence commit triggers its
own hosted CI; latest exact-HEAD status is on draft PR #6.
