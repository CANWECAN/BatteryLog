# BMW clock provenance — step 3 investigation, 14 October 2026

**Investigation recorded; clock acceptance gate remains blocked.**
The companion original log is now pinned and compared with the reviewed CSV.
No trustworthy seconds-per-tick conversion was established. BMW remains
`curve_review_eligible: false`; this is not a completed physical clock validation.

## Source chain

All capture reads use EV-CANlogs commit
`9cbfc24528d9dfb2923c532f987ce1f3c278908f`.

- [Original log addition](https://github.com/dalathegreat/EV-CANlogs/commit/30ac29d0523a3cb97f1ca2749a28fe13c7ca6cd8),
  17 December 2023: four BMW startup/start-charge logs added; commit description
  attributes the test to Dala with TOMPPIX. It does not name the logger, version,
  timestamp unit, epoch or rollover policy.
- [CSV addition](https://github.com/dalathegreat/EV-CANlogs/commit/c92400651bf24a4a5fdf6a09f7fa2d5f3e78fbcc),
  14 May 2024, via [upstream PR #3](https://github.com/dalathegreat/EV-CANlogs/pull/3).
  The title calls these Savvy CAN logs. The PR body, issue comments and reviews
  inspected contain no conversion procedure or clock declaration.
- The pinned repository README only describes a collection of EV CAN data.
  The original tab-separated header names `Time`, with no unit or logger version.
  `Parser Name` is `Default Parser` throughout. Search of public primary sources
  did not produce an authenticated exporter specification for this header.
  This is a bounded research result, not proof that such documentation cannot exist.

The two external inputs are not redistributed in this Research change:

| Input | Bytes | SHA-256 | Git blob |
| --- | ---: | --- | --- |
| `BMW i3/2017-60AH-REX-PT-CAN2-startcharge.csv` | 5,348,227 | `d6bd56a3f0f60d7cfffa708a18b287c5802cc42fd5261e01b58d40e7c5c68ebf` | `3b66c4239cc4537f8ac68c4a5c2a0f63378684c6` |
| `BMW i3/2017-60AH-REX-PT-CAN2-startcharge.log` | 9,909,389 | `e858df31719d6a2dfd914a9f254a6a411e2b79451ec76cd51b5ff673f8c79dda` | `9e8aaad34a94c2b638405f2bfce5da60c2236a91` |

## Full ordinal comparison

Kali compared every record in original order after checking byte count,
SHA-256 and Git blob identity. Both files contain 132,941 records.

| Comparison | Result |
| --- | ---: |
| Raw integer timestamps equal | 132,941 / 132,941 |
| DLC / original Len equal | 132,941 / 132,941 |
| Declared-length payload bytes equal | 132,941 / 132,941 |
| Parseable CSV IDs equal original log IDs | 130,637 / 130,637 |
| CSV ID tokens rejected as malformed | 2,304 |
| Original `Ch=0` paired with CSV `Bus=1` | 132,941 |

Thus the files preserve the same ordered timestamp/DLC/payload sequence.
The timestamp numbers were not rescaled in this representation change.
Ordinal pairing does not establish the logger's physical clock semantics.

For example, CSV physical line 49 has `2.00E+02`, while the original log has
`0x000002e2`. Line 50 similarly has `2.00E+08` versus `0x000002e8`.
The original is a possible authoritative source for a future preparation step;
this audit does not repair IDs or replace the currently reviewed input.
The cause of this token transformation is not established.

Original line 18 carries opaque `Flags=E`, ID `0x00000000`, four payload bytes
`10 48 00 01`. Every CSV Extended field is `0`; no logger Flags column is
retained. **Do not interpret E as extended, error or validity without the
original format specification.** Channel renumbering also does not authenticate
the physical wiring or shared timebase.

## Raw clock discontinuity

The raw clock is non-decreasing, with 85,132 equal adjacent timestamps and
47,808 positive steps. One transition dominates:

| Source lines | Before | After | Raw delta |
| --- | ---: | ---: | ---: |
| 111158 -> 111159 | 2,688,401 | 45,638,073 | 42,949,672 ticks |

Every other positive adjacent step is at most 11 ticks. The large jump exists
in both the original log and CSV. It therefore predates the reviewed CSV
representation; no cause is authenticated. It must not be subtracted, smoothed,
called a long dwell, or identified as rollover from numerical resemblance alone.
Monotonic ordering is insufficient evidence of a continuous physical clock.

The earlier phase-source rows 1880 / 2124 / 2486 / 2575 have identical IDs,
payloads and raw timestamps in both files. The large jump occurs later in the
capture, outside these rows. This does not authorize an early-span time unit,
a precise contactor onset, aligned channels, or a precharge duration.

## Why the SavvyCAN label cannot establish units

A pinned contemporary-to-export
[SavvyCAN implementation](https://github.com/collin80/SavvyCAN/blob/080fc4d9bf171e8ebd3c1be71530913603a28eb0/framefileio.cpp),
dated 9 May 2024, writes native CSV timestamps using
`frame->timeStamp().microSeconds()` in `saveNativeCSVFile`.
Its native export header includes `Dir` and `LEN`, writes padded hexadecimal IDs
and textual true/false flags. This BMW CSV instead omits Dir, names the length
DLC, uses unpadded IDs and numeric Extended fields, and contains malformed IDs.

That documents SavvyCAN's own exporter convention, not this original logger's
unit or the undocumented upstream transformation. A format-compatible importer
can interpret numbers using its own convention without authenticating how those
numbers were acquired. Neither the upstream title nor plausible message periods
can transfer a microsecond or millisecond unit to the source.

## Reproduce the audit

From this private Research checkout with the two pinned originals outside it:

```bash
python -m batterylog_research.bmw_clock_provenance_audit \
  --csv /path/to/bmw-charge.csv \
  --log /path/to/bmw-charge-original.log
```

The standalone stdlib audit emits raw-tick JSON to stdout and rejects a changed
input before parsing. It is not a general log importer or part of the Core
analysis path. The retained
[results](../batterylog_research/bmw_clock_provenance_results_20261014.json)
include complete comparison counts, delta histogram, source pins, flag/ID
examples and the four earlier phase-source rows.

Native Kali execution: complete two-file audit passed; altered-byte CSV and log
inputs were each rejected; Ruff check and format check passed. Audit source
SHA-256: `908a038e83541472fad8b8e16c8d7f838e37ad8e86e1617b6d90a11968e4a081`.
No BatteryLog full regression rerun or physical acquisition check is claimed
by these focused checks. Prior #9 exact-head 12-job CI evidence remains
[separately recorded](https://github.com/CANWECAN/BatteryLog-Research/actions/runs/38595056579).

## Qualification decision

Keep `tick_unit` and `seconds_per_tick` null. Accept physical conversion only
with evidence tying this exact original format/capture to its logger/exporter
version, tick unit, clock source, resolution and reset/rollover handling, plus
an explanation of the observed discontinuity. A documented alternative capture
or controlled lab export is the fallback.

Step 4 may specify the measurement contract and document its missing evidence.
Source-specific aligned preparation (step 6) and real curve review (step 8)
remain blocked by clock and physical-contract/reference gates.
No reference curve, RC constant, normal timing envelope or field accuracy is
inferred. The audit retains raw source units and does not change Core,
dependencies, licensing or schema contracts.
