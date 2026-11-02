# BMW source preparation: raw trace checkpoint, 14 October 2026

**Step 6's raw-source trace is implemented. Physical alignment remains blocked.**
This records the part that can be prepared from authenticated file bytes without
inventing a clock convention, measurement validity or continuous phase truth.
It does not complete the physical acceptance criteria in steps 3, 4, 6, 7 or 8.

## Source review and scope

Rechecked the upstream BMW folder's commit history and
[CSV upload PR #3](https://github.com/dalathegreat/EV-CANlogs/pull/3), including
its body, comments and reviews. The inspected folder history's latest change is
fd5487f9 (26 July 2024); PR #3 has no body, comments or reviews supplying the
missing clock/conversion contract. This check found no new qualifying evidence
in those sources; it is not a claim that such evidence cannot exist elsewhere.

The source remains EV-CANlogs commit
`9cbfc24528d9dfb2923c532f987ce1f3c278908f`. Original log and CSV identities are
the [step-three pins](RESEARCH_BMW_CLOCK_PROVENANCE_2026_10_14.md); DBC identity
and candidate field semantics remain the
[step-four contract](RESEARCH_BMW_MEASUREMENT_CONTRACT_2026_10_14.md).
Three original inputs and the complete derived trace stay outside git.

## What the tool retains

`batterylog_research.bmw_raw_source_trace` accepts only that pinned CSV, original
log and DBC. It reads each into one bounded snapshot. CSV/log reads stop at the
known byte size plus one; the DBC read stops at 64,001 bytes. All three byte pins
must match before records are parsed. The existing clock probe now uses this
bounded pinned reader too, with its report facts unchanged on the real source.

Every ordinal CSV/log record is compared for raw timestamp, DLC and payload.
Parseable CSV IDs must match the original ID. Malformed CSV IDs remain recorded
tokens, without guessing or repair. Selected candidate identities come from the
original log. Original `0x...` ID tokens, channel, counter, parser, direction and
opaque flags remain attached to selected records alongside CSV metadata.

For the selected 0x112 and 0x1FA frames, the trace retains zero-based source
record index, physical line ranges in each representation, raw integer ticks,
payload, raw codes, exact decimal candidate values and pinned encoding metadata.
It records the difference from the previous same-ID transport timestamp; this
is **not sensor age or a physical sample interval**. Acquisition time and sensor
age remain null. Duplicate or backward timestamps are never sorted or repaired.
Physical multi-line records retain their complete line ranges.

Negative current and all-ones codes remain values. All-ones/range-departure flags
are metadata observations, not authenticated validity decisions. Current range
0..819.2 A, pack range 0..819 V and DC-link range 0..820 V match the pinned DBC;
they do not supply a physical filtering policy. Candidate state reports remain
separate frames. No state is copied onto electrical rows, and SNA is not inactive.

Output format is `batterylog-bmw-raw-source-trace-v1`, strict JSON. It contains
neither `timestamp_s` nor `precharge_active`, and always declares
`aligned_rows_created=false` and `curve_review_eligible=false`. No accepted
capture, seconds-per-tick or alignment override exists. The existing aligned
file reviewer rejected the raw-trace header supplied as context, creating no
output. This prevents interchange of the two formats; it does not authenticate
someone's separately authored capture declarations.

## Reproduce

From the Research checkout (the trace itself uses only standard-library code):

```sh
python -m batterylog_research.bmw_raw_source_trace \
  --csv /path/to/bmw-charge.csv \
  --log /path/to/bmw-charge-original.log \
  --dbc /path/to/BMW-i3-PT-CAN2.dbc
```

JSON is fully built/encoded before being printed to standard output. There is
no destination-file publisher here. Use the Python function or capture stdout
outside git when retaining this source-derived trace.

## Validation

Native Windows source comparison:

- 132,941 records inspected; 8,120 electrical and 90 state frames retained.
- Every selected source index, physical line, timestamp, payload and metadata
  matches the independent original/CSV pass: 8,210 comparisons.
- All encoding definitions match cantools, and all 24,450 candidate values match
  its decoder with relative tolerance zero and absolute tolerance 1e-12.
- State codes remain 5 OPEN / 2 PRECHRG / 83 CLOSED. The two PRECHRG reports do
  not establish two physical events or an aligned active interval.
- 419 negative current values; all-ones counts 19 / 51 / 20. Range departures
  remain 438 / 51 / 20. Facts agree with the previous measurement probe.
- 2,304 malformed CSV IDs, 85,132 adjacent duplicate ticks and the original
  42,949,672-tick jump remain visible. Prior clock-probe facts agree.
- Three same-size mutations and three appended-byte mutations rejected. Inputs
  unchanged; deterministic repeat and strict JSON round-trip passed.
- Trace construction: 0.85 s in this run. Serialized trace: 13,412,692 bytes,
  SHA-256 `4f9e4b0a8bcd02952e586d1dc58d704dc18f3290a5faf8186b4e1a626f6fea9c`.
  This is one software timing observation, not a memory or acquisition guarantee.
- 36 authored regression cases passed: prefix/metadata/line preservation,
  exact integer ticks, duplicate/backward/jump order, candidate decoding,
  SNA separation, changed-input rejection, bounded reads and decimal context.

Actual CLI output parses identically to the API report; an attempted
`--seconds-per-tick` override is rejected by the CLI. Native full suite with
required real Tk and actual MF4: **2,878 passed / two skipped / nine existing
warnings**, 161.19 s, Core coverage 96.67%. Whole-tree Ruff check/format (226
files), dependency consistency and staged whitespace checks passed. Core mypy
passed on 48 files using the exact existing CI flags
`--follow-imports=silent --ignore-missing-imports`. An initial call without those
flags reported missing pandas/jsonschema stubs; that failed attempt is retained,
and no code or environment change was used to resolve it.

Full native checks are retained in
`batterylog_research/bmw_raw_trace_native_validation_20261014.json`.
Source comparisons are retained in
`batterylog_research/bmw_raw_trace_comparison_results_20261014.json`.
Exact saved head and hosted CI closure are recorded in the draft PR after
verification, without recursive documentation-only commits.

## Remaining gate

Clock units/jump cause, exact vehicle/firmware mapping, measurement nodes/current
path/sign, analog validity/staleness, reported-state meaning/latency, sensor
timing/filtering/alignment and independently justified reference remain unresolved.
Raw trace preparation is complete in this scope; physical step 6 remains blocked.
Next useful work needs authenticated capture context or a documented controlled
export before selecting a reference or reviewing a real precharge curve.

Branch `build/bmw-raw-source-trace-20261014` is based on draft #12 at 7c40d646.
CAN feature branch #8 remains separate. No Core result/schema, dependency,
licensing, merge, release or live CAN change.
