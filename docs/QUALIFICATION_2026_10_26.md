# Recording review and CSV clock qualification

Date: 26 October 2026. Development version: 0.11.0.dev0.
The last published release remains v0.10.0.

## Source and local test scope

Runtime source:
1643a445996a13f3f677e654e9e8365252c4d0e4.
Subsequent candidate changes are documentation, distribution checks and packaging
regressions. Runtime source bytes remain identical to this qualified source.

Native Windows/Python 3.13.14: 3,429 passed, 2 platform-specific skips.
All 45 real Tk tests ran with BATTERYLOG_REQUIRE_DESKTOP_TESTS=1.
Core statement coverage: 5,093 / 5,273 = 96.5864%, above the unchanged 95% gate.
Normalization: 97.38%; recording audit: 95.42%; recording review: 96.70%.
These are software coverage measurements, not physical detection accuracy.

The skips require Linux /proc exec-lifetime measurement or POSIX signal
escalation; Windows terminates the latter worker immediately. Four existing
NumPy overflow warnings come from a passing fail-closed evidence test.
Ruff and the repository's mypy command pass with the existing local dependencies.

The changed source has not been qualified on Linux/Python 3.11–3.14 or minimum
dependency versions. Historical results in the 23 October note belong to their
identified source. Required hosted CI remains pending; no merge/release
acceptance is inferred from local tests.

## Recording and time contracts

[Recording review](RECORDING_AUDIT.md) audits only explicitly planned CSV paths,
channels and time windows. It preserves independent coverage and engineering
statuses; sensor acquisition freshness remains NOT_EVALUATED.

[Relative-time preparation](UNIT_NORMALIZATION.md) is an explicit CSV operation.
The first raw decimal clock is subtracted exactly, and declared units are divided
before converting elapsed seconds to binary64. Origin, units and source/output
hashes remain in the conversion evidence. Version 2 identifies the changed time
basis; default normalization retains version 1. Analysis of an unprepared epoch
clock still has the documented binary64 interval sensitivity.

The 76 relative-clock regressions cover threshold boundaries, positive/negative
origins, s/ms/us, mapped clocks, chunk boundaries, duplicate/backwards timestamps,
elapsed precision collapse, source mutation and cancellation. Decimal context
checks cover both clean and pre-set flags. Whole-file and 1/2/100-row streamed
results and report geometry agree on the authored six-row source.

## Installed distribution acceptance

The candidate wheel and sdist must pass archive/path safety, source-test fixture
retention, strict metadata, Apache LICENSE/NOTICE and original Model 3 MIT
attribution checks. Source/resource bytes must match the frozen candidate.
The sdist must include examples/recording_plan.json.

scripts/check_installed_package.py invokes scripts/check_recording_package.py
outside checkout using the installed console command. It checks relative-time
conversion evidence, API/streamed/CLI/JSON/HTML parity, event times, source/config
hashes, local report links and COMPLETE/PASS, COMPLETE/FAIL and INCOMPLETE/PASS
review outcomes. Existing base, CAN/precharge/replay and MF4 smoke checks remain.

The local acceptance environment reuses existing dependency files without
processing the source checkout's editable-install hooks. BatteryLog itself must
resolve inside each artifact environment. No dependency downloads or fresh
minimum-version dependency resolution are implied by this method.

## Limits and integration

Authored fixtures establish software behavior and traceability. Independent
user utility, calibrated physical references, live adapter/HIL behavior and
physical fault-detection accuracy remain unvalidated.

One free Apache-2.0 package is retained. Publishing a development branch does not
merge main, publish a release or satisfy protected-branch checks. CI trigger and
branch-protection policy remain unchanged. Required hosted checks must run on
the final candidate once account access is available.
