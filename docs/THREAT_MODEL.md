# BatteryLog threat model

BatteryLog is a validation and reporting tool. Its evidence metadata is intended to make analysis inputs auditable, not to authenticate who produced those inputs.

## Protected provenance invariant

For HTML evidence reports, BatteryLog captures the source CSV and optional YAML configuration into immutable byte snapshots before parsing.

The SHA-256 values recorded in the report are computed from those exact byte snapshots, and the CSV/YAML parsers consume the same snapshots.

Therefore:

> the bytes identified by the report hashes are the bytes that produced the validation result.

A source or configuration path may change after the snapshot is captured without changing the bytes used for that analysis.

## Concurrent file changes

BatteryLog performs a final on-disk re-hash before writing an HTML report. This detects ordinary source/config drift that occurs after snapshot capture.

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

## Memory tradeoff

Standard CSV file analysis is chunked and carries validation state across chunk boundaries, so analysis memory does not grow with the total input row count. The returned violation-event list is still materialized and can grow with the number of distinct events.

Evidence-report mode deliberately remains on the immutable in-memory source snapshot path. This preserves the exact-byte provenance invariant above, but means report generation still scales memory with source-file size.

Bounded-memory evidence for multi-million-row inputs requires a future streaming/content-addressed snapshot design that preserves the same provenance guarantee and is tracked separately from the current report snapshot model.
