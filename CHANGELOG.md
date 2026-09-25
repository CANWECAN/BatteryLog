# Changelog

All notable changes to BatteryLog are documented here.

## Unreleased

### External validation evidence

- Added a reproducible CORA dataset validation harness and documented the BatteryLog v0.9.1 campaign across all 410 public Parquet cycle files (30,187,165 unique source rows; 90,561,495 branch-row analyses; 1,230/1,230 direct-comparison parity).

### Documentation

- Streamlined the main README into a project overview and quick-start guide, moved detailed CLI/config/schema/engineering semantics into `docs/REFERENCE.md`, and classified the current project status as pre-1.0 engineering beta.

## 0.9.1 - 2026-09-25

### 0.9.1 development scope

- Validate pack-voltage plausibility against the measured cell-voltage sum with reproducible evidence.
- Fix pack-current type checking and enforce the affected analysis modules in CI.
- Preserve the existing rule thresholds, grouping, and historical schema artifacts.

### Pack-voltage plausibility

- Added an opt-in pack-voltage versus complete series-cell sum check, with explicit source measurements, signed error, and peak timestamp in result schema v8.
- Added YAML config schema v6 and CLI override/disable for the positive absolute-delta threshold; legacy config schemas 1-5 and result schemas 2-7 remain frozen.
- Added synchronized whole-frame/streaming evaluation, fail-closed missing-pack behavior, and a report comparison plot plus mismatch-threshold plot.
- Sized report-series downsampling for combined pack-current and pack/cell-mismatch extrema; tiny budgets report a clear error if the retained extrema cannot fit.
- Added a complete 96S synthetic end-to-end regression across whole-frame, multiple streaming chunk sizes, report downsampling, and incomplete-stack mismatch behavior; this is software-path validation, not physical sensor calibration.
- Made row-wise cell summation chunk-deterministic after the 96S regression exposed platform/chunk-sensitive binary64 reduction order.

## 0.9.0 - 2026-09-24

### 0.9 development scope

- Expand BatteryLog from cell-limit checking toward pack-level electrical and thermal validation.
- Add first-class pack-current and pack-voltage signals while preserving CSV/MDF semantic parity.
- Add deterministic charge/discharge overcurrent and temperature-spread validation.
- Improve the engineering evidence emitted by the existing five validation rules without changing their 0.8 threshold semantics.
- Treat SOC plausibility and rate-of-change analysis as candidates that must be justified against real validation data before entering the release scope.
- Keep capacity/energy/DCIR, balancing analysis, raw CAN/DBC decoding, generic rule DSLs, dashboards, and unrelated framework expansion outside the initial 0.9 scope.

### Pack electrical signals

- Added optional canonical `pack_current_a` and `pack_voltage_v` measurements with streaming/whole-frame extrema parity.
- Added config schema version 3 for optional explicit vendor pack-current and pack-voltage source names while retaining schemas 1 and 2 unchanged.
- Added CSV/MDF semantic parity, including fail-closed MDF ampere/volt unit validation and required-numeric data-quality handling.
- Promoted the machine-readable result contract to schema version 4 with pack-signal provenance and nullable electrical extrema while retaining frozen result-v2 and result-v3 artifacts.
- Kept the existing five rule codes and their 0.8 threshold, grouping, and PASS/FAIL semantics unchanged; no overcurrent rule is introduced in this change.

### Pack-current validation

- Added config schema version 4 with explicit `limits.pack_current.charge_max_a`, `discharge_max_a`, and required `positive_direction` polarity when either current limit is active.
- Added deterministic `PACK_CHARGE_OVERCURRENT` and `PACK_DISCHARGE_OVERCURRENT` rules using the existing strict binary64-guarded comparison and event-grouping semantics.
- Kept configured current limits as non-negative magnitudes while preserving the source current sign in violation `measured_value` and `limit_value` evidence.
- Active pack-current validation now fails explicitly when `pack_current_a` is unavailable instead of silently producing PASS.
- Promoted the machine-readable result contract to schema version 5 and retained result-v4 as a frozen pre-overcurrent artifact.
- Added CLI current-limit overrides/disables, CSV/MF4 parity tests, chunk-boundary event regression coverage, and a pack-current HTML plot sourced from `AnalysisResult` evidence.

### Temperature-spread validation

- Added config schema version 5 with `limits.temperature.max_spread_c` while retaining config schemas 1-4.
- Added deterministic `TEMPERATURE_SPREAD_HIGH` evaluation from row-wise maximum minus minimum temperature using the existing strict binary64-guarded comparison and event-grouping semantics.
- Added peak evidence identifying the hottest and coldest temperature signal(s), plus exact `max_temperature_spread_c` result evidence.
- Promoted the machine-readable result contract to schema version 6 while retaining result-v5 as a frozen pre-temperature-spread artifact.
- Added CLI override/disable support, whole-frame/streaming chunk-boundary parity tests, schema coverage, and a dedicated temperature-spread HTML plot without changing report-series point-budget semantics.

### Rule-event evidence

- Added `sample_count`, `duration_s`, and `peak_excursion` to every engineering violation event without changing threshold, grouping, tie-break, or PASS/FAIL semantics.
- Defined `duration_s` as the first-to-last failing timestamp span rather than an integrated dwell estimate, so single-sample events and duplicate timestamps may legitimately report zero duration.
- Preserved whole-frame/streaming parity by summing sample counts across chunk merges, recomputing merged duration from event endpoints, and carrying peak excursion with the selected worst peak.
- Promoted the machine-readable result contract to schema version 7 while retaining result-v6 as a frozen pre-event-evidence artifact.
- Exposed the enriched evidence in HTML violation tables and added schema, duplicate-timestamp, arithmetic-invariant, and chunk-boundary regression coverage.

## 0.8.0 - 2026-09-21

### Structured data quality

- Added YAML configuration schema version 2 with explicit `data_quality.mode`; configuration schema 1 remains accepted and preserves strict fail-fast behavior.
- Added opt-in `exclude_invalid_rows` handling for missing, non-numeric, and non-finite required numeric samples without interpolation or silent repair.
- Added grouped structured data-quality events with 1-based source data-row ranges, affected signal names, and affected-value counts.
- Excluded rows now break engineering-rule event continuity and can never produce a false PASS; any structured data-quality event forces `validation_status` to `FAIL`.
- Added explicit `rows_input`, `rows_analyzed`, and `rows_excluded` accounting and support for all-excluded inputs with null measured extrema.
- Promoted the machine-readable result contract to schema version 3 while retaining the frozen result-v2 schema artifact for 0.7 consumers.
- Added HTML report data-quality evidence, row-accounting summaries, and null-safe all-excluded rendering.
- Added streaming/whole-frame parity, chunk-boundary, false-PASS, all-invalid, schema, CLI, and report regression tests.
- Hardened required-value classification so boolean samples are rejected as non-numeric consistently across strict, CSV streaming, whole-frame, and MDF/MF4 paths.
- Preserved the historical third positional `ValidationConfig` argument as `signals`; the new `data_quality` option is keyword-only.
- Tightened result schema v3 invariants so data-quality evidence requires excluded rows and all-excluded results cannot carry engineering-rule violations; documented remaining cross-field arithmetic invariants as semantic validation requirements.

### Loader architecture

- Introduced a format-neutral measurement-loader contract so source adapters can feed the same chunked validation engine without adding format branches to the rule engine.
- Routed both path-backed and file-backed CSV analysis through dedicated loader adapters while preserving existing CSV behavior.
- Added optional MDF/MF4 ingestion behind the `mf4` extra using `asammdf` with a 64 MiB output-DataFrame chunk target.
- Added explicit MDF channel ambiguity checks, physical-unit validation, preserved master timestamps, and fail-closed no-interpolation alignment semantics.
- Added real MDF4 integration tests for CSV equivalence, vendor signal mapping, misaligned rasters, duplicate channel names, and HTML evidence reports.
- Gated tagged releases on dedicated MDF/MF4 integration jobs across Python 3.11-3.14 and Windows.

### Report plots

- Added a separate immutable report-series contract without embedding plot geometry in the machine-readable result contract.
- Added deterministic `extrema-preserving-v1` downsampling with a configurable retained-point budget.
- Preserved first/last samples and per-bucket extrema for cell minimum/maximum voltage, cell delta, and temperature minimum/maximum.
- Added chunk-boundary invariance and property-based tests proving retained-point bounds and global-extrema preservation.
- Added three self-contained inline SVG plots to HTML evidence reports: cell-voltage envelope, cell-voltage delta, and temperature envelope.
- Rendered configured limit lines from the effective result limits and violation intervals/worst-case markers from structured `AnalysisResult` events rather than re-evaluating rules from plot data.
- Kept plot collection off the standard non-report analysis path and kept plot geometry out of the JSON result contract.
- Added CSV and real MDF4 CLI report tests covering plot generation, provenance, deterministic rendering, and event-marker sourcing.
- Hardened plot evidence after adversarial review: malformed per-point envelopes/deltas, non-finite or out-of-domain events, reversed event timing, and unmapped rule codes now fail closed; instantaneous events use exact vertical markers and single-row plots show explicit samples.

### Large-log analysis

- Added a repeatable end-to-end MDF/MF4 benchmark that generates realistic multi-channel MF4 inputs, isolates measured workloads in fresh child processes, and records wall-clock throughput plus sampled process RSS for both standard analysis and HTML evidence-report paths.
- Documented a three-repeat Windows baseline showing source-size-proportional MDF/MF4 RSS growth despite the 64 MiB `asammdf` output-chunk target; results remain informational rather than CI performance gates.
- Identified `asammdf.iter_to_dataframe(channels=...)` full selected-channel filtering as a major pre-chunk memory cost and added a record-bounded `MDF.select()` path when all required channels share one channel group.
- Preserved the existing no-interpolation multi-group fallback and fail-closed invalidation semantics; real MDF4 tests cover CSV equivalence, vendor mapping, invalid samples, and misaligned rasters.
- Re-running the same benchmark reduced median native peak RSS by 18-27% and substantially increased throughput while still documenting the remaining source-size-proportional memory growth.
- Added `psutil` to the development extra for cross-platform process-RSS measurement without changing runtime dependencies.
- Changed the standard CSV file-analysis path from whole-file materialization to 50,000-row chunked processing.
- Preserved global extrema, timestamp-order validation, event-gap semantics, and active violation events across chunk boundaries during the streaming refactor.
- Added boundary-sensitive regression tests and differential property tests comparing chunked analysis against the whole-frame reference implementation.
- Extended the end-to-end CSV benchmark to profile both standard analysis and full CLI HTML evidence-report mode, and included profiling scripts in source distributions.
- Moved HTML evidence source capture to a private temporary-file snapshot: SHA-256 is computed while copying, and analysis consumes the same snapshot in bounded chunks.
- Changed the final source/config drift guard to streamed content hashing, avoiding whole-file byte materialization and accepting metadata-only changes when content is identical.
- Preserved the exact-byte provenance invariant; optional YAML configuration remains an immutable in-memory byte snapshot.

## 0.7.0 - 2026-09-20

### Release preparation

- Added CI wheel/sdist build, strict metadata checks, and independent installation smoke tests.
- Gated tagged release artifacts and SHA-256 checksums on Linux, Windows, and packaging checks.
- Added exact tag/package/citation version validation and an explicit sdist manifest.
- Added `--no-max-event-gap-s` to disable YAML event-gap segmentation from the CLI.
- Refreshed the report preview for 0.7.0 and result schema v2.
- Updated artifact upload/download CI actions to Node 24-based releases.

### Provenance hardening

- Bound HTML report provenance to immutable source/config byte snapshots instead of independently re-reading paths for hashing and parsing.
- SHA-256 evidence is now derived from the exact bytes consumed by CSV/YAML parsers.
- Added restore-race regression tests covering source and configuration TOCTOU scenarios.
- Retained the final on-disk re-hash as a secondary drift guard; provenance correctness no longer depends on that check.

### Licensing and attribution

- Licensed BatteryLog under the Apache License 2.0.
- Added PEP 639 SPDX package metadata and explicit LICENSE/NOTICE distribution files.
- Added a NOTICE attribution file with the canonical project repository.
- Added CITATION.cff metadata so GitHub and other tooling can generate software citations.
- Documented that commercial/internal use is welcome and invited anonymized real-world validation feedback.

### CLI contract

- Refactored `run()` to return integer codes for expected CLI outcomes; `main()` is now the single `SystemExit` boundary.
- Reserved exit code `2` for CLI usage/parsing errors and moved input/config/analysis/report/output errors to exit code `4`.
- Added `--json-out` for atomically written UTF-8 JSON while preserving JSON on stdout.
- Added collision guards preventing JSON output from overwriting input/config/HTML report paths.
- Existing 0.6.x automation that interprets runtime exit code `2` must update to code `4` for the 0.7.0 line.

### CLI rule control

- Added explicit `--no-*` CLI options for disabling validation rules that are active in YAML.
- Numeric overrides and matching disable options are mutually exclusive.
- CLI disable/numeric decisions take precedence over YAML without changing the existing Python config-helper semantics.
- Added `--no-temp-warning-c` as a compatibility alias for `--no-temp-max-c`.

### Result contract

- Promoted the current machine-readable result contract to result schema version 2.
- Result schema v2 is the first formally frozen BatteryLog result contract.
- Historical result schema v1 is documented as a legacy, pre-formal marker because 0.4.x-0.6.x payloads evolved while retaining `schema_version: 1`.
- Replaced the misleading strict `result-v1.json` artifact with `result-v2.json`.
- The v2 Draft 2020-12 schema rejects unknown fields and encodes validation-status invariants.
- The v2 schema uses an immutable v0.7.0 tag-addressed raw URL as its canonical `$id`.
- Added CI tests tying the runtime schema constant, artifact filename, schema `const`, and canonical identifier together.
- Documented that YAML configuration schema version 1 and result schema version 2 are independent contracts.

### Comparison semantics

- Unified validation boundary comparisons behind one explicit policy.
- High rules use strict `>`; low rules use strict `<`.
- Values indistinguishable from a configured boundary at binary64 representation scale are treated as on-boundary, not as violations.
- The representation guard uses a relative tolerance of `8 * float64 epsilon` and zero absolute tolerance; it is not an engineering or sensor tolerance.
- Cell-imbalance, cell-voltage, temperature, and event-gap comparisons now use the same floating-point boundary policy.
- Effective comparison semantics are recorded in machine-readable results and HTML reports.
- Validation decisions no longer depend on decimal rounding of cell-voltage delta.

## 0.6.1 - 2026-09-19

### Fixed

- Removed per-event chained pandas row/column indexing from violation construction; signal lookup now uses precomputed NumPy matrices.
- Report provenance verification now re-hashes source/config files after analysis instead of relying only on file size and modification time.
- Invalid numeric input errors now identify the first failing data row, DataFrame index, column, and value.

### Changed

- Legacy Python arguments `imbalance_limit_v` and `temp_warning_c` now emit `DeprecationWarning`. Use `ValidationLimits` through `limits=` instead.
- Legacy threshold arguments remain backward compatible for now and continue to override the corresponding `ValidationLimits` fields when both are supplied.

### Testing

- Added Hypothesis property-based tests for contiguous and time-gap-aware event grouping invariants.
- Added a reproducible synthetic event-builder benchmark under `benchmarks/`.
- Added a regression test proving that restoring file size/mtime cannot bypass post-analysis SHA-256 evidence verification.

## 0.6.0 - 2026-09-18

### Added

- Explicit YAML signal mapping for vendor-specific timestamp, cell-voltage, and temperature channel names
- Full-match regex selection with required named `index` capture groups for indexed sensor channels
- Canonicalization into `timestamp_s`, `cell_<n>_v`, and `temp_<n>_c` before validation
- Public `SignalPattern` and `SignalMapping` Python API types
- Signal-mapping provenance in machine-readable results and HTML reports
- Tested vendor-style CSV and YAML examples

### Correctness

- Ambiguous cell/temperature pattern matches fail closed.
- Duplicate logical indexes such as `Cell_1` and `Cell_01` are rejected.
- Duplicate or non-string source signal names are rejected at the canonicalization boundary.
- Aggregate channels are not selected unless the explicit user pattern actually maps them to a numeric logical index.
- Analyzer/config public APIs now reject invalid config-object types instead of silently falling back to defaults.

### Compatibility

- Canonical CSV names continue to work without a `signals` block.
- Existing validation/event configuration remains compatible.
- Result schema remains version `1`; signal-mapping provenance is additive.

### Units

Signal mapping performs naming only. It does not convert units. CSV timestamp, cell-voltage, and temperature values must already be expressed in seconds, volts, and degrees Celsius respectively.

## 0.5.0 - 2026-09-18

### Added

- Configurable time-gap-aware violation event grouping through `event_detection.max_gap_s`
- CLI override through `--max-event-gap-s`
- `ValidationConfig` and `EventDetectionConfig` public configuration models
- `analysis_options.max_event_gap_s` provenance in machine-readable results and HTML reports

### Compatibility

- Existing row-contiguity event grouping remains the default when no maximum gap is configured.
- Existing `load_validation_limits()` and `limits=` Python API usage remain supported.
- Result schema remains version `1`; the new analysis-options field is additive.

### Correctness

- A timestamp gap greater than the configured maximum starts a new event.
- A timestamp gap exactly equal to the configured maximum remains in the same event.
- Duplicate timestamps remain in the same event.
- Timestamp-gap comparison is normalized to avoid binary floating-point noise incorrectly splitting boundary events.

## 0.4.0 - 2026-09-18

First tagged public release.

### Added

- Self-contained HTML validation reports
- Input-log and validation-config SHA-256 provenance
- BatteryLog version and UTC generation metadata in reports
- Machine-readable result `schema_version` (introduced as `1`)
- CI-friendly process exit codes for PASS, FAIL, error, and NOT_EVALUATED
- Applied-limit snapshot in analysis results
- Atomic HTML report writing
- Windows CI coverage in addition to the Linux Python 3.11-3.14 matrix

### Changed

- HTML reporting uses the same AnalysisResult produced by the validation engine; the report layer does not recalculate validation decisions.
- Report output is prevented from overwriting the input log or validation config.

### Correctness

- Report evidence capture detects source/config changes during hashing and checks for changes again after analysis.
- Result schema versioning is independent from the package version.

## 0.3.1 - 2026-09-18

Development milestone.

- Added explicit `NOT_EVALUATED`, `PASS`, and `FAIL` validation status.
- Added `rules_evaluated` to distinguish a true PASS from a dataset where no rule ran.

## 0.3.0 - 2026-09-18

Development milestone.

- Added YAML-configurable validation limits.
- Added cell overvoltage, cell undervoltage, high-temperature, and low-temperature rules.
- Removed implicit universal engineering thresholds; rules now require explicit limits.
- Added strict indexed signal discovery and duplicate-input detection.
- Added strict YAML parsing, duplicate-key rejection, and unknown-key rejection.
- Added deterministic cell-delta boundary handling.
- Added protected-main workflow with required CI checks.

## 0.2.0 - 2026-09-18

Development milestone.

- Replaced string-only violations with structured violation events.
- Added event start, end, and worst-case timestamps.
- Added multi-temperature-sensor support.
- Added Python 3.11-3.14 CI matrix.
