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

At the initial cloud snapshot, Windows, Python 3.13/3.14 and the hosted GitHub
Actions matrix had not been run. No PR, main merge, tag or release was created
in that snapshot. The separate desktop-launcher work remains untouched.

## Windows and CI follow-up - 2026-10-07

The branch was recovered at `cec8578` into a separate Windows worktree. An initial
Windows/Python 3.13.14 run found five failures in the new CSV normalization fixtures:
`Path.write_text(frame.to_csv(...))` translated pandas' CRLF output a second time,
creating CR-CR-LF records. The strict loader correctly treated the resulting blank
rows as invalid measurements. Writing directly with `DataFrame.to_csv(path, ...)`
fixes fixture generation; the model calculations and strict loader are unchanged.
The normalization parity test now exercises LF and CRLF input independently with
canonical/explicit mapping and one/full-frame chunks.

| Follow-up verification | Recorded result |
|---|---|
| Windows, Python 3.13.14, NumPy 2.5.3, pandas 3.0.6, PyYAML 6.0.3, asammdf 8.8.27 | 1,647 passed, 1 skipped; coverage 98.87% |
| Windows skip | Existing Linux-only `/proc` process-lifetime benchmark |
| Focused normalization regressions | 10 passed |
| Ruff 0.16.8 lint and formatting | Passed |
| Package-wide mypy 2.3.1 | Passed, 40 source files |
| Dependency consistency and git whitespace check | Passed |
| Frozen result-v8 schema and golden corpus | Still unchanged against main |

The MF4 CI job now explicitly includes `tests/test_failure_models_mf4.py` on its
existing Linux Python 3.11-3.14 and Windows Python 3.13 matrix. Without this change,
that new module was skipped by the base jobs and omitted from the MF4 command.
A draft PR will trigger the hosted matrix; hosted results are reported in the PR
checks. No main merge, tag or release is part of this work.
