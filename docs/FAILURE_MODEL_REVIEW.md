# Failure-model development verification — 2026-10-07

Branch: `feat/failure-models`, based on `main` commit
`ad051793a9d3b72af8a5647234ea968bd4387b18` (released v0.10.0).
Implementation and test snapshot: `0a54c2afbd0e7e7e8d83af2e9f012aa51bceb19d`.
The follow-up verification record changes documentation only.

The requested five areas are present: existing pack/cell-sum mismatch plus new
sustained imbalance, temperature rise, load-relative cell sag, and balancing
improvement/timeout. The balancing area produces two explicit model outcomes.
See [the model contract](FAILURE_MODELS.md) for formulas and eligibility.

| Verification | Recorded result |
|---|---|
| Linux, Python 3.12.14, NumPy 2.5.3, pandas 3.0.6, PyYAML 6.0.3, asammdf 8.8.27 | 1,644 passed; coverage 98.87% |
| Linux, Python 3.11.16, minimum runtime NumPy 1.26.0 / pandas 2.2.0 / PyYAML 6.0 | 1,578 passed, 2 skipped; coverage 98.26% |
| Minimum-runtime skips | The two real MF4 integration test modules; the optional backend is absent in that environment |
| Ruff lint and formatting | Passed |
| Package-wide mypy 1.18.2 | Passed |
| Dependency consistency | Passed in development, minimum-runtime and installed-wheel environments |
| Wheel and source distribution | Built successfully; strict Twine metadata checks passed |
| Source distribution corpus | All Python/JSON/Markdown test fixtures preserved byte-for-byte |
| Installed wheel outside checkout | Base/service/CLI/schema/HTML/normalization/batch smoke tests passed; optional MF4 smoke passed |
| Installed source distribution outside checkout | Base/service/CLI/schema/HTML/normalization/batch smoke tests passed on Python 3.11 |
| Frozen result-v8 schema and golden corpus | Unmodified; existing serialized golden checks passed |

Coverage measurements use separate data files for the two interpreter environments.
The four overflow warnings in the main suite come from existing boundary tests;
the minimum suite also emits pandas 2.2's existing optional-PyArrow warning.

The added tests include 280 Hypothesis examples with independent oracles:
100 sustained intervals and 60 each for temperature pairs, peer-relative sag and
balancing deadlines. Deterministic regressions exercise gap/duration/limit edges,
unrounded peaks, duplicate timestamps, missing channels, malformed values,
excluded measurements, censored episodes and multiple chunk sizes. Twenty new
real binary MF4 cases cover grouping, source mapping, booleans, invalidation,
asynchronous sampling, unit contracts, duplicate channels, normalization and
scaled one-bit status that must not silently become `true`.

The five-model synthetic example yields six events: one original pack/cell-sum
event and one for each new model outcome, including both balancing checks. The
CLI, HTML report and batch event total agree. Model state is bounded by sensor
count plus the event output, with no concatenation of input chunks. A local smoke
measurement of 5,000 rows × 96 cells with sustained/rise enabled took 0.527 seconds;
this is a single smoke measurement, not a performance guarantee.

These are deterministic validation checks on synthetic measurements, including
measurements written into actual MF4 files. No new model has been calibrated or
validated against acquired vehicle data in this work. Adjacent-sample temperature
rates can be noise-sensitive; relative sag can hide common-mode drops; balancing
spread is affected by the test operating conditions. Those limits are explicit
in the contract and reported measurement chains.

Windows, Python 3.13/3.14 and the hosted GitHub Actions matrix were not run for
this branch. The existing workflow runs on main pushes and pull requests; no PR
was opened or modified, no main merge was performed, and no tag or release was
created. The separate desktop-launcher work remains untouched.
