# Declared recording coverage audit

This development API checks exported CSV recordings against an explicit plan.
It does not execute tests, diagnose a battery, or evaluate engineering limits.
It belongs to the existing free Apache-2.0 BatteryLog product.

```python
import json
from batterylog.recording_audit import audit_recordings

audit = audit_recordings("measurements", plan="recording-plan.json")
print(json.dumps(audit, indent=2, allow_nan=False))
```

The audit API reads inputs without modifying them or writing reports. Existing
analysis/batch commands and their schemas/results are unchanged.

## Review reports and CLI

To publish a source-linked overview with the existing per-file engineering
JSON/HTML reports, use the directory review mode:

```sh
batterylog measurements --audit-recordings recording-plan.json --output-dir results/run-001 --cell-max-v 4.2
```

The engineering limit above is illustrative; supply the actual validation
configuration with `--config` or the existing engineering-rule overrides.
Without active engineering rules the engineering status remains NOT_EVALUATED.
`--audit-recordings` is mutually exclusive with batch, inspect and normalize;
it uses exact planned paths, so `--recursive`, `--report` and `--json-out` are
not accepted. It reads only the CSVs named in the plan.

The new output directory must be outside the input directory. It contains
`review.json`, `review.html` and `files/<source.csv>/result.json|report.html` for
completed engineering analyses. The overview shows coverage and engineering
outcomes separately, expected/observed evidence, issue counts/first lines,
source/plan hashes, and relative links to the unchanged engineering reports.

The Python reporting API is:

```python
from batterylog import AnalysisService
from batterylog.recording_review import review_recordings

review = review_recordings(
    "measurements",
    "results/run-001",
    plan="recording-plan.json",
    service=AnalysisService(validation_config),
)
```

Omit `service` for a coverage-only review. If a caller supplies `config_evidence`,
it must describe the configuration actually used by the service, as for batch.
The wrapper uses a separate `recording_review_schema_version: 1` envelope;
it does not insert recording coverage into an engineering AnalysisResult.

All outputs are staged and the review directory is published only when JSON,
HTML and the relevant per-file evidence are complete. Cancellation propagates;
staging is discarded and previous outputs remain untouched. Per-file engineering
input errors stay explicit ERROR results. A source hash mismatch between the two
analyses, a changed plan/source before publication, or a report-write failure
aborts publication rather than associating mismatched evidence.

CLI exit codes: `4` for any coverage/engineering ERROR, otherwise `1` for
INCOMPLETE coverage or engineering FAIL, otherwise `3` for NOT_EVALUATED in
either dimension, otherwise `0`. Invalid argument combinations return `2`.

## Plan version 1

```json
{
  "recording_plan_schema_version": 1,
  "recordings": [
    {
      "id": "run-001",
      "path": "session/run-001.csv",
      "expected_channels": ["cell_1_v", "cell_2_v", "temp_c"],
      "time": {
        "column": "timestamp_s",
        "unit": "s",
        "start_s": "0",
        "end_s": "600",
        "max_gap_s": "1",
        "boundary_tolerance_s": "0"
      }
    }
  ]
}
```

These numbers are illustrative expectations, not calibrated defaults. Specify
the actual procedure's window, acceptable log interval and endpoint tolerance.

- `recording_plan_schema_version` must be integer `1`, not a boolean.
- `recordings` is nonempty. Each recording requires a unique `id` and an exact
  relative POSIX `path` ending in `.csv` (case-insensitive). No glob discovery,
  parent traversal, empty/dot components, backslashes, drives or alternate streams.
  Paths are unique without regard to case for Windows/Linux portability.
- `expected_channels`, when supplied, is a nonempty unique list of exact source
  header names. Names are not interpreted as physical units or canonical bindings.
  Unlisted columns and unlisted files are outside the audit's scope.
- `time`, when supplied, requires all six displayed fields. The unit declaration
  is explicitly `s`; there is no conversion or inference. Bounds may refer to
  relative time or epoch seconds, consistently with the original source clock.
- All four time quantities are finite decimal **strings**. `start_s < end_s`,
  `max_gap_s > 0`, and `0 <= 2*boundary_tolerance_s < end_s-start_s` are required.
  A window or channel list must not be guessed from the available data.
- Unknown fields and duplicate JSON keys are errors. Invalid plans raise
  `ValueError` before scanning recording samples. Invalid input directories and
  unreadable plan files raise ordinary input errors.

## What is checked

Existing input inspection supplies the channel inventory. The audit then reads
a captured, hash-identified source snapshot with a strict UTF-8/BOM-aware CSV
reader. Every record must have the header's width; blank records, duplicate or
empty headers and malformed quoting are not silently repaired.

Every expected channel must exist, have at least one finite numeric sample, and
have no invalid samples in the CSV. Constant numeric values are allowed. This
only checks recorded numeric availability; values may still be physically wrong.
Extra columns are not sample-validated. Header-only input is incomplete.

When time is declared, source timestamps must be finite decimal seconds and
strictly increasing throughout the file, with at least two valid timestamps.
Invalid, repeated or backwards timestamps make coverage incomplete. No sorting,
interpolation, missing-sample filling or clock-origin inference is performed.

The first timestamp must be no later than `start_s + boundary_tolerance_s` and
the last no earlier than `end_s - boundary_tolerance_s`. Every adjacent interval
overlapping the expected window must be at most `max_gap_s`. Having the expected
endpoints alone therefore does not hide an internal gap. Invalid timestamps
break adjacency and remain explicit defects; they cannot create a successful
coverage result.

Raw decimal timestamps are converted to exact rational numbers **before**
subtraction or comparison. Epoch magnitude does not introduce binary64 rounding
into this audit. Tokens are limited to 256 characters and decimal exponents and
adjusted exponents to [-128, 128]; unsupported values are reported, not rounded.
These rules do not change the existing engineering models' numeric contract.
Formatting exact time evidence uses an explicit Decimal context so unrelated
application Decimal exponent/trap settings cannot invalidate supported clocks.

Multiple expected ids resolving to the same physical file are ambiguous and
both receive an error. Equal bytes in genuinely separate files alone are not
proof of a duplicated run. Symlink escapes and non-file inputs are rejected.
The source is hash-checked again before its completed audit result is accepted.

## Independent result semantics

The returned envelope has `recording_audit_schema_version: 1` and
`scope: "declared_csv_recording_coverage"`. It is not an analysis-result payload.

| Coverage status | Meaning |
| --- | --- |
| COMPLETE | All declared file, channel and time criteria were checked and satisfied. |
| INCOMPLETE | A required file, sample/channel or time criterion is known to be unmet. |
| NOT_EVALUATED | No known defect, but a plan, channel list or time expectation is undeclared. |
| ERROR | A file assignment, read, CSV structure or source-stability check failed. |

Aggregation precedence is ERROR, INCOMPLETE, NOT_EVALUATED, COMPLETE. One existing
file passing its checks cannot hide another expected file's absence. Per-record
`file_status`, `channel_status` and `time_status` expose the checked dimensions.
Issues include a code, total count, first affected physical CSV line where
applicable, and source channel. All occurrences are counted without storing an
unbounded per-row event list. Files are streamed from disk-backed snapshots.

The envelope always states `engineering_analysis_performed: false` and
`sensor_acquisition_freshness: "NOT_EVALUATED"`. To evaluate voltage, temperature,
current or other engineering rules, run the existing analysis separately.
Recording COMPLETE and engineering FAIL can both be correct. Conversely, an
engineering PASS does not establish complete recording coverage.

The retained inspection metadata may report ISSUES when source names have no
Core mapping. That does not invalidate an otherwise complete raw-name audit;
it also does not establish engineering eligibility. The audit never treats
inspection's metadata OK as evidence that samples are valid.

The plan and successfully captured sources carry SHA-256 identifiers. Those
identify audited bytes; they do not prove that a physical test occurred or that
files were never changed before auditing. Sensor freshness, calibration,
chemistry, SOC, physical units and cross-sensor acquisition alignment remain
unverified. CSV row timestamps are not independent sensor acquisition timestamps.

MDF/MF4/CAN input, automatic test discovery, resuming test execution and desktop
integration are outside this CSV workflow. Independent utility and real-world
validation remain pending.
