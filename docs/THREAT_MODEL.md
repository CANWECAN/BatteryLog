# BatteryLog threat model

BatteryLog is a validation and reporting tool. Its evidence metadata is intended to make analysis inputs auditable, not to authenticate who produced those inputs.

## Protected provenance invariant

For HTML evidence reports, BatteryLog copies the source measurement file into a private temporary-file snapshot while hashing that same byte stream. The selected CSV or MDF/MF4 loader consumes that snapshot in bounded chunks. The optional YAML configuration is captured as an immutable in-memory byte snapshot.

The SHA-256 values recorded in the report are computed from those exact snapshots, and the measurement/config parsers consume the same snapshots.

Therefore:

> the bytes identified by the report hashes are the bytes that produced the validation result.

A source or configuration path may change after the snapshot is captured without changing the bytes used for that analysis.

## Concurrent file changes

BatteryLog performs a final streamed on-disk re-hash before writing an HTML report. This detects ordinary source/config content drift that occurs after snapshot capture. Metadata-only changes do not fail this final check when file contents still hash identically.

That final check is a secondary operational guard. It is not the basis of the provenance guarantee and is not treated as an unbypassable file-locking mechanism.

An actor able to change a file and restore its original contents between checks may evade the final drift check, but cannot cause different bytes to be analyzed under the recorded snapshot hash.

## What SHA-256 evidence does not prove

BatteryLog evidence does not prove:

- who created the source log or configuration
- that the source system or measurement device was trustworthy
- that the file existed unchanged before BatteryLog captured it
- that a generated HTML report has not been modified after generation
- that the report was produced by a particular person, machine, or organization

Reports are not digitally signed.

If origin authentication or post-generation tamper evidence is required, a higher-level signing or trusted artifact-storage system is needed.

## Input trust

BatteryLog treats CSV, MDF/MF4, and YAML inputs as untrusted data and validates their structure, selected-channel metadata where available, and required numeric content. HTML report rendering escapes user-controlled text before embedding it.

Validation limits are engineering inputs. BatteryLog does not infer universal safe limits.

## Visualization evidence boundary

HTML time-series plots are presentation artifacts derived from row-level metrics computed during the same snapshot-backed analysis pass. They are not a second validation engine and do not determine `NOT_EVALUATED`, `PASS`, or `FAIL`.

Plot geometry may be deterministically downsampled for large inputs. Configured limit lines are rendered from the effective `AnalysisResult["limits_applied"]`, while shaded violation intervals and worst-case markers are rendered from `AnalysisResult["violations"]`. Downsampling therefore cannot remove a structured violation event from the report's validation evidence, even if an interior visual sample is not retained in the plotted series.

The machine-readable result, structured data-quality table, and structured violation table remain authoritative. Data-quality evidence is produced by the analyzer from required numeric inputs and is not reconstructed from plot geometry. A visualization defect could misrepresent presentation, but must not alter the validation decision or structured evidence contract.

## Memory and temporary-storage tradeoff

CSV analysis processes source data in fixed row chunks and carries validation state across chunk boundaries. MDF/MF4 uses record-bounded selected-signal reads for single-group inputs and retains a no-interpolation DataFrame fallback for multi-group inputs; these chunk targets do not by themselves establish a total-process RSS bound for third-party internals. The returned violation-event and data-quality-event lists are materialized and can grow with the number of distinct event runs.

Evidence-report mode achieves this without weakening exact-byte provenance by storing the immutable source snapshot in a private temporary file. Temporary storage therefore scales approximately with source measurement-file size and must be available for the duration of report generation. The snapshot is closed and removed automatically afterward.

The optional YAML configuration remains an in-memory byte snapshot, so unusually large configuration files still contribute memory proportional to config size.
