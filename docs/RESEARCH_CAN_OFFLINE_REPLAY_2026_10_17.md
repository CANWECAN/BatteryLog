# Offline CAN replay and recording lifecycle - 17 October 2026

This Research-only module supplies the first three items of the hardware-free
roadmap: separate coverage measurement, ordered file replay and software recording
lifecycle checks. The base is draft #17 at
83e37c34edc5b3e5e961da0fa55a14ae6560cdab, whose hosted CI passed all 12 jobs.

## Run

From the private source checkout, using the existing Python environment:

```sh
python -m batterylog_research.can_replay capture.log /path/to/new-session
python -m batterylog_research.can_replay capture.log /path/to/another-session --stop-after 100
```

The output directory must be new. Successful source EOF returns 0. Intentional
early stop returns 1 with a partial session. Argument, input or filesystem errors
return 2; failures after the directory was created can retain a failed manifest
and partial data. Keyboard interruption records the stopped prefix and re-raises.
A missing/failed manifest is never a successful session.

Input uses the existing strict classic candump parser: decimal timestamp, bus,
standard/extended ID and zero to eight data bytes. The source and serialized
journal record bounds are 4,096 bytes each. Unsupported formats and source clock
reversal reject. No DBC, optional CAN dependency or physical interface is needed.

## Replay and journal contract

Replay yields immutable existing Frame objects on demand. Pause refuses further
reads without advancing the iterator; resume continues at the next source frame.
Stop is terminal, and actual EOF is a distinct state. The replay does not wait,
retime messages or infer clock units. It is not a wall-clock playback benchmark.

Each JSONL record contains sequence, source_segment, source_line,
timestamp_as_recorded, bus, frame_id, extended and data_hex. Decimal values,
byte payloads, identifier types and source order are preserved. Timestamp strings
represent exact Decimal values, not necessarily the original token spelling.
No measurement normalization, decoding or battery decision occurs.

The file entry point hashes exactly the raw bytes delivered to its parser.
The manifest records consumed_bytes, consumed_sha256 and fully_consumed.
For a stopped or malformed source the hash identifies only that consumed prefix,
including a rejected line or the bounded prefix of an overlong line.
Even stopping exactly at the final frame does not claim EOF before it is observed.
The source filename/hash is provenance, not producer or physical authentication.

## Recorder lifecycle

Recorder is single-owner and call-driven, with no background threads or driver.
Offer enqueues validated serialized frames; drain writes pending rows in order.
Capacity is an integer from 1 to 100,000 (default 1,024). Overflow rejects the
new incoming frame, increments dropped_frames and records first/last dropped
sequence/source-line examples. It never overwrites an already accepted frame.
The ordinary file entry point drains at capacity, providing backpressure.

Disconnect disallows ingress until explicit reconnect. Reconnect starts a new
source segment and permits a declared clock restart; a reversal within one segment
fails, including after a dropped frame. Segment boundaries remain in the journal.
These are simulated software events, not evidence of adapter reconnect behavior.

Finish drains accepted pending data while the recorder remains writable, then
closes it. Once failed, no further writes occur; pending counts remain explicit.
Short writes, write/flush/close failures, malformed frames and source failures
prevent completion. Counts distinguish received, accepted, written, dropped,
invalid and still-pending frames. Written counts acknowledge complete write calls;
they do not establish power-loss durability after a later flush failure.
Failed writes are never retried into the same possibly partial record.

Only uninterrupted EOF with no known drops/failures publishes frames.jsonl.
Other sessions keep frames.jsonl.part. A closed manifest is published last as
session.json using the existing no-overwrite hard-link helper. Existing output
directories, data targets and manifests are never overwritten. Failed finalization
cannot be retried; successful finish is idempotent. A filesystem may prevent the
manifest itself from being published; retained .part files are incomplete evidence.
No crash/power-loss durability or hardware capture guarantee is made.

## Measured coverage and verification

The initial six-module measurement ran 421 existing CAN/precharge cases with
branch coverage enabled. Approximate combined statement/branch percentages:

| Module | Coverage |
| --- | ---: |
| can_prepare | 87% |
| can_capture_review | 92% |
| can_multiplex_audit | 86% |
| precharge_curve_review | 97% |
| precharge_capture_review | 100% |
| precharge_file_review | 93% |
| Six-module total | 91% |

This is a selected operational-module scope, not all Research experiments.
The earlier Core 96.67% metric remains a separate measurement. Coverage identifies
unexercised paths; it does not authenticate physical model behavior.
Eight new Decimal-time API rejection cases cover unusable empty, non-vector and
nonfinite clocks. Existing observer implementations are unchanged.

New replay tests cover pause/stop/EOF/source failure, bounded queue accounting,
explicit disconnect/reconnect and clock reset, invalid frames, short/write/flush/
close failures, protected output paths, failed finalization, consumed-prefix
hashes, keyboard interruption, source line bounds and the real CLI.

Independent campaign, raw-source comparison, stress, final coverage and native
full-suite facts are retained in batterylog_research/can_offline_replay_validation_20261017.json.
Hosted CI is recorded against the eventual exact saved head in its draft PR.

The pinned Model 3 raw input remains outside git and is identified by SHA-256
709dd42efa4c43cc97cfc5cd05a488641b22949c9db3697c11c4b0cd588c36b4.
Its physical signal semantics/clock qualifications are not improved by replay.
The original source reference is in RESEARCH_FIRST_CAN_BRIDGE_2026_10_13.md.

## Scope

Decision/schema/threshold contracts, dependencies, packaging and licensing are
unchanged. This software campaign does not establish adapter, live-bus or HIL
behavior. Physical precharge requires qualified acquisition and reference data.

## Native checkpoint results

- Six-module baseline: 421 passes. Seven-module final targeted run: 482 passes;
  six additional actual CLI invocations are explicitly measured into the coverage
  dataset. Replay combined statement/branch coverage: 98.96% (216/218 statements,
  69/70 branches). Older CAN module coverage remains separately visible.
- 53 new replay/lifecycle tests and eight new Decimal time rejection cases pass.
- Independent 600 batch scenarios: 96,224 offered frames; 43,013 intentional
  overflow drops; zero accounting or retained-record mismatches.
- Pinned real Model 3: two runs of 118,053 complete frame comparisons, capacity
  one / 1,024. Both 22,582,719-byte journals have SHA-256
  19008b96d9f536c7befef94a6fcab7de59d0b60d1db3d3e2e4178ca03cc83ab9.
- 500,000 authored frames: 4.913 s, 35.95 MiB peak process RSS, peak pending 32.
  This unpaced software measurement is not a physical CAN bus-rate claim.
- Required real Tk/actual MF4 native Windows full suite: 3,000 passed / two
  skipped / nine existing warnings in 168.76 s; Core coverage 96.67%.
  Earlier intermittent Tk cause remains unestablished, despite this passing run.
