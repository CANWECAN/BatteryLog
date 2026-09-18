# Changelog

All notable changes to BatteryLog are documented here.

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
- Machine-readable result `schema_version` (currently `1`)
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
