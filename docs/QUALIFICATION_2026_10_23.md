# Local qualification - 23 October 2026

This record qualifies software behaviour in the unreleased 0.11.0.dev0 candidate.
Base: 05caefc8b1fbafe8dc5ac95e8ea6d8ad7e3a3a53, with the normalization source-clock fix.
Normalization source SHA-256: 7779d29ac40815ac31e5d7b027778afd6d9b7f0eb5f9b4dc7eeaea42404a8b5e.

## Platform checks

| Environment | Passing tests | Skips | Core coverage |
| --- | ---: | ---: | ---: |
| Linux / Python 3.14.7 | 3,270 | 0 | 96.46% |
| Native Windows / Python 3.13.14 | 3,268 | 2 | 96.63% |

All 45 real Tk cases pass on both platforms. Windows uses pytest --capture=sys,
as in CI; its skips cover unsupported platform facilities, not GUI availability.
Ruff 0.17.0 format/lint, mypy 1.19.1 on 49 Core files and pip check pass.
Four overflow warnings originate from the deliberately extreme-input regression.
The 28 new normalization cases fail in nine places before the fix and pass afterwards.

## Synthetic large-file checks

The CSV has 1,000,000 rows, 24 cell voltages and four temperatures. Five deliberately
triggered events have independent row/time expectations. Whole-frame analysis,
10,000/50,000-row streaming and report results agree, allowing 1e-12 absolute/relative
tolerance only for binary64 numeric values. No rows are excluded.

| Workload | Elapsed seconds | Native peak RSS MiB | Expected result |
| --- | ---: | ---: | --- |
| whole | 9.79 | 1266.93 | FAIL |
| stream-10000 | 7.25 | 137.77 | FAIL |
| stream-50000 | 5.99 | 176.89 | FAIL |
| report | 8.34 | 174.43 | FAIL |
| can | 10.19 | 140.25 | PASS |

The CAN source contains 1,000,000 authored classic frames and produces 500,000 anchor
rows with declared one-second context age. It is not a live-bus throughput test.
MF4 checks use 100,000 and 200,000 samples, 96 cell channels and 12 temperatures,
single-group uncompressed steady synthetic MDF, analysis and HTML modes, one repeat.
All stay within the predeclared 180-second and 2-GiB MF4 worker budgets.
MF4 native peak RSS grows with source size; these results do not establish a constant
end-to-end memory bound. Timings are this-host observations, not general guarantees.

## Packaging and demo

One Apache-2.0 wheel/sdist is checked for safe paths, retained source-test fixtures,
strict metadata, unchanged license/notice bytes and 91 runtime/resource byte matches.
Each artifact is installed in a separate fresh environment outside the checkout.
Base Core/precharge/replay run without CAN/MF4 backends; [can,mf4] then exercises
DBC preparation, analysis, HTML and MDF ingestion. The installed normalization fix
is checked for mapped/unmapped clocks and intra-/cross-chunk regressions.
The synthetic desktop demo intentionally returns FAIL with two rule violations;
its limits are illustrative. The demo is not a hardware or calibration reference.

## Remaining acceptance

Hosted required checks and main integration are separate gates. This record does
not imply a GitHub CI pass or a released build. Physical fault accuracy, manufacturer
calibration, live adapters and HIL remain outside this local software qualification.
