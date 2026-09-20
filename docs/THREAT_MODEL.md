# BatteryLog threat model

BatteryLog is a validation and reporting tool. Its evidence metadata is intended to make analysis inputs auditable, not to authenticate who produced those inputs.

## Protected provenance invariant

For HTML evidence reports, BatteryLog copies the source CSV into a private temporary-file snapshot while hashing that same byte stream. CSV analysis consumes that snapshot in bounded chunks. The optional YAML configuration is captured as an immutable in-memory byte snapshot.

The SHA-256 values recorded in the report are computed from those exact snapshots, and the CSV/YAML parsers consume the same snapshots.

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

BatteryLog treats CSV and YAML inputs as untrusted data and validates their structure and required numeric content. HTML report rendering escapes user-controlled text before embedding it.

Validation limits are engineering inputs. BatteryLog does not infer universal safe limits.

## Memory and temporary-storage tradeoff

Standard CSV analysis and HTML evidence-report analysis both process source data in bounded chunks and carry validation state across chunk boundaries, so Python heap usage does not grow with total CSV row count under ordinary event density. The returned violation-event list is still materialized and can grow with the number of distinct events.

Evidence-report mode achieves this without weakening exact-byte provenance by storing the immutable source snapshot in a private temporary file. Temporary storage therefore scales approximately with source CSV size and must be available for the duration of report generation. The snapshot is closed and removed automatically afterward.

The optional YAML configuration remains an in-memory byte snapshot, so unusually large configuration files still contribute memory proportional to config size.
