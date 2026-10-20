# BatteryLog technical status

Updated: 20 October 2026. This file summarizes implementation and qualification;
reproducible methods and source-specific results are in the linked technical notes.

## Product and package

The 0.11 development tree implements one free Apache-2.0 BatteryLog distribution.
Core and all 28 first-party experimental Python modules share the root license
and NOTICE; the Model 3 MIT notice is retained. There is one wheel/sdist and
no batterylog-research companion dependency or alpha version.
See [licensing/package inventory](docs/LICENSING.md) and
[product direction](docs/PRODUCT_DIRECTION.md).

The root CLI exposes batterylog experimental can|precharge|replay. Precharge HTML
and replay are in the base installation; DBC preparation uses the optional [can]
extra. Authored fixtures and source-specific profiles are packaged; raw external
captures/DBCs and internal notes are excluded. The old separate add-on builders
are retired. The operator, precharge HTML and documentation are part of the
unified product.

The public development integration derives from reviewed Research candidate
b9662055668c7a7e64a75c8379242c689ec40618. The last published release remains
v0.10.0; this source integration is not a new release.
Source timestamp order is checked before binary64 analysis, including CSV mapping
and chunk boundaries. Reports/model arithmetic remains binary64.

## Interfaces

| Interface | Contract | Documentation |
| --- | --- | --- |
| CAN preparation | Explicit DBC/profile; canonical CSV and source/age evidence | [CAN preparation](docs/RESEARCH_FIRST_CAN_BRIDGE_2026_10_13.md) |
| CAN replay and recording | Exact recorded clock; bounded queue and explicit partial sessions | [Replay contract](docs/RESEARCH_CAN_OFFLINE_REPLAY_2026_10_17.md) |
| Precharge HTML | Source-linked current/gap plots, coverage and missingness | [HTML interpretation](docs/RESEARCH_PRECHARGE_HTML_2026_10_17.md) |
| Precharge observation | Explicit aligned CSV, hash-bound context and declared bounds | [File contract](docs/RESEARCH_PRECHARGE_FILE_REVIEW_2026_10_14.md) |
| Common file command | Staged CAN preparation/analysis/reporting or precharge review | [Operator contract](docs/RESEARCH_OPERATOR_2026_10_17.md) |
| Unified package | One Apache-2.0 batterylog wheel/sdist, with optional CAN/MF4 backends | [Package/licensing](docs/LICENSING.md) |

The common command and precharge HTML are installed with the same package. Prepared CAN rejects temporal models, signal remapping and unqualified
pack/cell-sum comparisons. Held samples are not independent acquisitions.

## Public integration verification — 20 October 2026

- Linux/Python 3.12.14 full headless suite: 3,198 passed, 44 skipped, four known overflow warnings.
  Core coverage 89.73% is below the unchanged 95% gate; the pytest command exits 1.
  All 44 skips are real Tk GUI cases: the runner has no DISPLAY.
  Graphical-session checks and native Windows verification remain pending.
- CI-pinned Ruff and mypy passed; mypy checks 49 Core source files.
- One wheel and one sdist build successfully. Archive safety, strict metadata,
  all source-test retention and 91 runtime source/resource byte comparisons pass.
  Official Apache LICENSE and the Model 3 MIT notice remain byte-identical.
- Each artifact was installed in a separate fresh virtual environment outside
  checkout. Base Core, precharge HTML and replay passed without CAN backends.
  Installing [can,mf4] on the same artifact passed CAN prepare/analyze/report,
  MF4 checks and pip check. These installs used NumPy 2.5.4, pandas 3.0.6,
  asammdf 8.8.27, cantools 44.2.1, canmatrix 1.2 and python-can 4.6.1.

These results verify software/package behavior, not physical fault accuracy.
Public integration preserves analysis/operator runtime source bytes and adapts
the CI policy/workflow to the public repository. All four Linux Python contexts
and Windows remain required on protected main; public planning forces the Full
profile. Tag-only release/version/checksum controls are retained.
Local paths and host names in six historical JSON records are redacted and
labeled; their recorded results and source fixtures are unchanged.
No hosted CI pass or current native/GUI qualification is inferred.

## Historical validation

These records refer to older revisions from the former private Research tree.
Their source commits and hosted run links may be inaccessible to public readers;
they do not qualify the current public development tree.

- Precharge HTML native source 44bb79e: 103 targeted checks and 3,172 full-suite
  passes with two skips; Core coverage 96.67%. Display statement/branch coverage
  is 99.53%. Hosted Linux source 9e68c3f has 3,023 passes and two skips,
  with 96.23% Core coverage. [Hosted verification](https://github.com/CANWECAN/BatteryLog-Research/actions/runs/39069799840).
  These software results do not establish physical qualification.

- Operator native source 10b1a852: 23 focused regressions; the recorded Windows suite has
  3,151 passes and two skips, with 96.67% Core coverage.
  [Hosted verification](https://github.com/CANWECAN/BatteryLog-Research/actions/runs/39067508529).
- Alpha source 9f31935: separate wheel/sdist, member/license/hash and installed
  command checks. [Hosted verification](https://github.com/CANWECAN/BatteryLog-Research/actions/runs/39042170811).
- CI selects documentation, fast or full profiles and enforces a final result gate.
  [Selection policy](docs/RESEARCH_CI_PROFILES_2026_10_17.md).

Counts belong to their identified revisions and environments. Core coverage and
selected Research statement/branch coverage are separate measurements.

## Qualification limits

- BMW raw traces retain ticks, payloads and source identity. Logger units,
  measurement topology, channel validity and acquisition uncertainty remain
  insufficient for an aligned physical precharge assessment.
- Public source audits have not established a complete independently justified
  physical reference and comparable evaluation capture.
- Replay and recorder tests establish software behavior, not adapter throughput,
  live-bus reconnect behavior or HIL qualification.
- Caller-selected thresholds and reference bounds are not calibrated safety limits.

See the [capability map](docs/RESEARCH_WORK_MAP_2026_10_14.md),
[software roadmap](docs/RESEARCH_HARDWARE_FREE_ROADMAP_2026_10_17.md),
[measurement contract](docs/MEASUREMENT_CONTRACT.md) and
[distribution boundary](RESEARCH_BOUNDARY.md).
