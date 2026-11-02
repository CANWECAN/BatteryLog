# Kali step 2 verification and CORA numeric bug hunt — 14 October 2026

Separate native source scopes were validated. The totals do not describe an
integrated sibling tree.

## Isolation and environment

CAN/precharge source: PR #8 at f94209379382570ff6b668815279601a4e81b862.
CORA parent: PR #7 at 91c3664e36b241e1848a562bf0ac4a343a8d9e3a.
The correction is on audit/kali-cora-bughunt-20261014, based on #7.

Environment: Python 3.14.7, NumPy 2.5.4, pandas 3.0.6, asammdf 8.8.27,
cantools 44.2.1, canmatrix 1.2, python-can 4.6.1, pytest 9.1.1, Ruff 0.17.0
and mypy 1.19.1. Full tests required actual MF4 and real Tk under Xvfb.

Initial numeric reproduction used the old environment read-only (NumPy 2.5.3).
Final regressions and comparisons used the fresh environment.
Prior step-one documentation CI 38588482062 passed all 12 jobs at f9420937.

## Reproduced defects and correction

| Finite input | Earlier descriptive result | Corrected behavior |
| --- | --- | --- |
| Constant temperatures 1e307 | Grid calculation gives infinite residual | Explicit numeric descriptor ValueError |
| Six increasing timestamps -1e308 to 1e308, finite adjacent intervals | Infinite total duration | Reject unrepresentable duration |
| Statistic values 1.5e308, 1.5e308 | Infinite median | Reject nonfinite derived statistic |

For the first two cases, CLI JSON encoding failed after its exclusive output
was opened, leaving a zero-byte report. The complete strict JSON is now encoded
before reserving the destination; encoding failure neither creates a new file
nor overwrites an existing one. This addresses encoding errors, not every
possible interrupted filesystem write.

The helper validates derived duration, statistics and temperature descriptors.
Core rules/statuses, thresholds, schemas, dependencies and source measurements
are unchanged. Recorded 655.28-degree cases remain in the software comparison.
Eight regressions cover numeric boundaries and Inf/NaN serialization failure
with new/existing destinations. Historical source-specific results are preserved.

## Native verification

| Scope | Focused | Full native suite | Core coverage |
| --- | ---: | --- | --- |
| CAN/precharge and CAN boundaries | 373 passed | 2,773 passed; zero skips; nine existing overflow warnings; 136.13 s | 96.51% |
| Fixed CORA and temporal helper | 44 passed | 2,779 passed; zero skips; nine existing overflow warnings; 134.90 s | 96.51% |

Whole-tree Ruff check/format, Core mypy (48 files) and pip check passed separately.
The 95% gate passed. This is Core coverage, not Research line coverage.
Hosted CI for the new source is a separate record on the draft PR.

## Real CAN parity

All six pinned external inputs were downloaded and hash-verified on Kali.
The entire native JSON equals the saved Windows report, including script/input
hashes and every source record: 435,488 transport records, 41,677 selected
decoded frames and 94,400 independent byte comparisons. BMW retains 2,304
malformed records and two PRECHRG-labelled observations. Input hashes were
unchanged before/after. Original source bytes remain outside the repository.

All three inventories remain curve_review_eligible=false. Cross-host arithmetic
agreement does not authenticate BMW clock units, firmware or physical meaning.

## Before/after generated comparison and retained limit

Seed 20261014: 200 authored captures / 6,265 rows, variable spacing and gaps,
current changes and occasional preserved 655.28-degree spikes.

- 197 accepted reports were exactly equal; returned JSON finite, inputs unchanged.
- Three captures produced the same conservative RuntimeError in both versions:
  independent temperature eligibility counts disagreed with Core.
- Core/helper evaluated-count pairs were 47/46, 52/51 and 18/17. Corresponding
  sag counts agreed. Source fixtures are retained in the machine evidence.
- The cause of those existing compatibility limits was not established here.
  No count/timing guard was weakened and no report was emitted for them.

This is software regression evidence, not field-fault performance. Original
CORA Cycle 229 CSVs were not rerun in this step; their earlier observations
remain associated with PR #7's original source.

## Evidence and qualification requirements

batterylog_research/kali_step2_validation_results_20261014.json stores native
checks/provenance, exact source hashes, failure reproduction, corrected outcomes,
generated comparison and complete CAN parity. Local logs/downloads remain in
the separate Kali evidence directory.

This branch is based on #7. CAN/#8 code is not copied or merged into it.
License, dependency and schema contracts are unchanged; live CAN/HIL was not tested.

Next **3/10**: authenticate BMW logger/exporter clock units and conventions.
Keep BMW blocked if source evidence is unavailable; use a documented alternative
capture or controlled lab export rather than infer a conversion.
