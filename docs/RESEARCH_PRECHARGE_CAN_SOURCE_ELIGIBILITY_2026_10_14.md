# Precharge CAN source eligibility — 14 October 2026

Private Research follow-up to source baseline
`415d8d91576f025325bcfa541ebdcdf1bba6afdc`.
Executed on Windows with the six pinned source files.
This inventories candidate DBC outputs; it does not align measurements, review a
declared response, diagnose a component, or change Core decisions.

## Concrete transfer result

| Publisher-labelled source | Input records | Malformed transport records | Selected decoded frames | Independent byte comparisons | Precharge-labelled signal observations |
| --- | ---: | ---: | ---: | ---: | ---: |
| Model 3 battery recording | 118,053 | 0 | 33,467 | 69,950 | 0 |
| BMW i3 start-charge CSV | 132,941 | 2,304 | 8,210 | 24,450 | 2 |
| Volvo EX30 battery-only CSV | 184,494 | 0 | 0 | 0 | 0 |
| Total | 435,488 | 2,304 | 41,677 | 94,400 | 2 |

The inventory examines explicitly selected state/command and electrical fields.
Zero EX30 selected decodes means none were selected for this precharge study,
not that the earlier EX30 compatibility review decoded no frames.
Precharge-labelled observations count signal reports, not physical episodes.
All three inventories retain `curve_review_eligible: false`.

Candidate bit layouts were checked against the pinned DBC. Authored direct
little-endian arithmetic independently reconstructed every selected raw and
scaled value; comparisons used absolute tolerance 1e-12, relative tolerance zero.
Agreement establishes candidate encoding arithmetic, not OEM semantics, validity,
measurement location, firmware matching, timing calibration or failure labels.

## BMW: a recorded state transition with missing timing justification

The candidate DBC contains all four interesting fields:

| Field | Frame | Declared unit / role |
| --- | --- | --- |
| `ST_DCSW_HVSTO` | 0x1FA | Reported switch state; raw 0 OPEN, 1 PRECHRG, 2 CLOSED, 3 SNA |
| `Battery_Current` | 0x112 | Amps; candidate battery current |
| `Battery_Volts` | 0x112 | Volts; candidate pack voltage |
| `DC_link` | 0x112 | Volts; unsigned eight-bit field with 4 V scale |

The 90 state reports contain **5 raw-zero, 2 raw-one and 83 raw-two** values.
There are two observed code changes, zero-to-one and one-to-two. This is one
recorded state progression with two PRECHRG reports, not two precharge events.
No independent acquisition or physical switching instant is inferred.

| Source evidence | Physical CSV line | Unconverted recorded tick |
| --- | ---: | ---: |
| Last reported raw-zero before raw-one | 1,880 | 2,621,457 |
| First raw-one report | 2,124 | 2,621,606 |
| Second/last raw-one report | 2,486 | 2,621,826 |
| Next raw-two report | 2,575 | 2,621,877 |

The unit of these ticks remains unverified. Do not multiply or divide by an
assumed logger scale, quote an elapsed duration in seconds, or infer an RC time
constant. State reports are sampled observations, not continuous phase truth.

For the first raw-one report, nearest earlier/later same-bus measurement frames
are lines 2,111/2,125, ticks 2,621,597/2,621,607: candidate pack **390.5 V**,
DC-link **0 V**, current **0 A**. Around the second raw-one report, frames at
lines 2,471/2,488, ticks 2,621,817/2,621,827, give pack approximately **390.4 V**,
DC-link **388 V**, current approximately **-0.1/-0.2 A**.

These are separate recorded frames preserved as neighbours, **not** resampled,
interpolated or accepted aligned phase/voltage/current rows. Source order,
integer ticks and bus identity remain explicit. This does not prove DC-link
voltage at a physical switching instant or identify the current through the
precharge path. The coarse 4 V DC-link encoding, current offset/filtering and
other connected loads must be understood before declaring comparison tolerances.

Whole-capture candidate extrema retain startup all-ones codes: current has
19 all-ones bit patterns, pack voltage 51 and DC-link 20. They are counted,
not authenticated as invalid codes, removed, clipped or diagnosed. The 2,304
malformed transport records retain their earlier compatibility blocker; malformed
hexadecimal IDs are not repaired. No reference envelope is chosen.

## Model 3: definitions present, no observed precharge label

The selected pack positive and negative contactor-state fields each occur in
301 frames and remain raw 1, labelled OPEN by the candidate DBC.
The PCS control request occurs 3,016 times and remains raw 0, labelled SHUTDOWN.
The requested voltage is a **setpoint**, not a measured DC-link channel.
The separately declared filtered DC-link reading is 9 V throughout this source.

The selected battery current/voltage frame appears 30,150 times. Candidate pack
voltage ranges 335.8–337.74 V and smooth current approximately 3.4–5.4 A.
These facts cannot establish a precharge curve or explain the state electrically.
In particular, the command field is not interchangeable with reported state or
feedback, and filtered voltage latency is not authenticated.

## EX30: no usable precharge selection

This CSV has no timestamps, bus or standard/extended metadata. The pinned partial
DBC supplies no complete precharge phase/current/pack/DC-link selection for this
study; earlier unknown multiplex branches, ambiguous units and candidate range
departures remain unresolved. No time axis or missing channel is invented.

## Reproduction and saved evidence

Original inputs remain outside the repository. Source paths, pinned identities
and source licensing are recorded in
[the first CAN bridge](RESEARCH_FIRST_CAN_BRIDGE_2026_10_13.md) and
[the second-source audit](RESEARCH_SECOND_CAN_SOURCES_2026_10_13.md):
EV-CANlogs commit `9cbfc24528d9dfb2923c532f987ce1f3c278908f`, and Model3CAN.dbc
commit `c56c113c353d09b1a5dd57677461f02fe8b7c6ca`.
Existing attribution is preserved. Original log/DBC bytes are not redistributed.

Install existing isolated Research CAN dependencies and use the same six local
names as the earlier Windows campaign:

```sh
python -m batterylog_research.precharge_can_source_audit SOURCE_DIRECTORY NEW_OUTPUT_JSON
python -m pytest -q tests/test_research_precharge_can_source_audit.py
```

The campaign verifies the six pinned files before inspection and checks their
SHA-256 identities afterward. Publication is a staged exclusive new-file write.
The raw summary includes its exact script hash and input hashes:
`batterylog_research/precharge_can_source_audit_results_20261014.json`.

The new 16 contract cases cover all four raw state codes, large integer clocks,
duplicate source timestamps, per-bus neighbour/transition separation, malformed
records and decreasing clocks, selected extended-frame rejection, candidate layout
mismatch, independent voltage/current references, original source lines, empty
inputs and refused output overwrite/source mismatch. New plus prior precharge
subset: **159 passed** on native Windows. Whole-tree Ruff check/format, Core
mypy (48 files) and dependency consistency passed. Full native suite: **2,771 passed / 2 skipped / 9 existing overflow warnings**,
157.58 s, Core coverage **96.67%**, with required real desktop and actual MF4.
Hosted exact-source closure is recorded separately in the draft PR after completion.

## Next evidence contract

Before using these channels for a time-indexed curve review, obtain:

- An authenticated source/DBC/firmware mapping with raw validity-code policy.
- Explicit logger clock units, ordering/export conventions, sensor latency,
  acquisition timing and the alignment uncertainty allowed by the procedure.
- Phase/command/feedback semantics; pack/DC-link measurement locations and the
  relevant current path, including filtering, resolution and parallel loads.
- The initial bus voltage, connected load/capacitance and procedure context,
  plus an independently justified reference envelope and tolerances.

A verified clock convention would make BMW the first candidate for a further
source-specific preparation study. It would still not supply the missing physical
reference or prove that two reported phase samples support the required timing.
Keep the existing curve observer separate until these gates are met.
No universal threshold, automatic RC fitting, streaming guarantee, live CAN
transmission, public push, merge, release, schema or dependency change is included.
