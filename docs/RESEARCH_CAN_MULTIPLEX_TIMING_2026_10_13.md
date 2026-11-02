# CAN multiplex coverage and timing — 2026-10-13

Baseline: `a1215fa7bb72561985bbfc0fbd1bc6bacbe85151`.
Private branch: `audit/cloud-balancing-spread-20261012`.

## Outcome

The Research checkout now has a **multiplex coverage/timing audit** that reports
missing groups, repeats, declared-order departures, selected-message gaps and
recorded-frame ages. It does not combine those frames into one measurement row or
claim a synchronized pack snapshot.

The first real Model 3 source has four fully covered review windows for the
declared groups 0–31. Each spans **49.598029–49.599934 s** between its first and
last required-group frames. Complete observed coverage is therefore a different
property from measurements arriving close together. The earlier three-brick
preparation remains a same-frame subset; it was not expanded into a synthetic
96-channel snapshot.

## Source and explicit review assumptions

This uses the same pinned, publisher-labeled Model 3 recording and community DBC
as [the first CAN bridge](RESEARCH_FIRST_CAN_BRIDGE_2026_10_13.md):

- `dalathegreat/EV-CANlogs`, commit `9cbfc24528d9dfb2923c532f987ce1f3c278908f`,
  `Tesla/Model 3/tesla-model3-battery-only.log.log`, GPL-3.0.
  SHA-256 `709dd42efa4c43cc97cfc5cd05a488641b22949c9db3697c11c4b0cd588c36b4`.
- `joshwardell/model3dbc`, commit `c56c113c353d09b1a5dd57677461f02fe8b7c6ca`,
  `Model3CAN.dbc`, MIT / copyright 2019 Josh Wardell.
  SHA-256 `d54df533fc82f3dab11ddd0f5ae4d846f22c0a24b111d8cba2b93e79caf60151`.

Raw files remain outside the repository. The existing DBC notice is retained.
This follow-up introduces no second vehicle source or firmware verification.

The profile explicitly declares bus `can0`, standard ID **0x401**, selector
`MultiplexSelector`, ordered required groups **0–31** and ignored groups **32–35**.
The ignored groups are still decoded and counted. Their prior zero/status-zero
observations do not authenticate inactive physical cells or full pack topology.
Each required group has three DBC brick-voltage fields; channel meaning and
actual physical series/parallel layout remain source-validation questions.

Review bounds: selected-message gap **5 s**, complete-window span **1 s**, and
age budgets **1 / 5 / 10 / 30 / 60 s**. These are declared timing probes, not
manufacturer safety requirements. The auditor checks the DBC group definitions,
frame type and full payload length rather than partially decoding damaged data.

## What a window means

An appearance of the first declared required group (0 for this profile) closes
the current review window and opens the next. This is **a declared partition
rule, not an authenticated BMS cycle boundary**. A repeated start frame can
therefore create a new partial window; repeats/order evidence are preserved so
the result does not silently label that as a genuine new cycle.

The head of a recording can begin in the middle of the group sequence, and its
tail can stop before the next boundary. Missing groups in those fragments do not
prove transport loss. A gap above the declared selected-message bound closes the
current window and clears receipt-age history. Ignored/other transport frames
never supply required-group coverage.

Only required frames received **inside the current window** count toward its
coverage. A separate timestamp-only history characterizes how old the last
received frame of each required group is. That history never contributes voltage
values, repairs coverage or produces canonical CSV rows. No look-ahead, row
sorting, interpolation, deduplication or full-pack sum computation occurs.

All timestamps are compared/subtracted as Decimal before numeric output. Exact
age/gap/span bounds are retained, including one-nanosecond boundary tests. The
recorded timestamps cannot authenticate the sensors' physical acquisition time.

## Original recording

**118,053 transport frames** were inspected. Of these, **181** were selected
0x401 messages: **161 required-group observations** and **20 explicitly ignored
group observations**. The required sequence showed no declared-order departures,
adjacent repeats, duplicate selected timestamps or selected-message gaps >5 s.

| Review window | Required groups seen | Missing groups | First-to-last required frame span | Boundary description |
| --- | --- | --- | ---: | --- |
| Head fragment | 8–31 | 0–7 | 36.800115 s | Recording starts before a declared group-0 boundary |
| Closed window 1 | 0–31 | None | 49.598029 s | Group 0 to next group-0 appearance |
| Closed window 2 | 0–31 | None | 49.599827 s | Same partition rule |
| Closed window 3 | 0–31 | None | 49.599895 s | Same partition rule |
| Closed window 4 | 0–31 | None | 49.599934 s | Same partition rule |
| Tail fragment | 0–8 | 9–31 | 12.799891 s | Recording ends before the next boundary |

None of the four complete windows satisfies the illustrative **1 s span bound**.
At 130 required-group arrivals all groups had appeared somewhere in the current
unbroken receipt history. At those arrivals:

| Maximum permitted recorded-frame age | Arrivals with every group's last frame within that age |
| --- | ---: |
| 1 s | 0 / 130 |
| 5 s | 0 / 130 |
| 10 s | 0 / 130 |
| 30 s | 0 / 130 |
| 60 s | 130 / 130 |

The oldest last-received group frame ranges **49.598029–58.402313 s** over these
arrivals. The 60 s outcome describes logged-frame ages; it does not certify that
associating those voltage values is physically justified for a given analysis.

## Six separate synthetic alterations

Each case changes a copy of the real transport recording. None is an observed
physical battery fault. Original source-line positions and changed-file hashes
are retained in the aggregate evidence; report lines refer to each changed file.

| Mutation | Observed response |
| --- | --- |
| Remove group 5 in the first closed window | That window retains missing group 5; complete coverage windows decrease 4 -> 3; one declared-order departure |
| Repeat a group-4 frame at the same recorded time | Repeat and identical-payload evidence retained; one duplicate timestamp; no deduplication |
| Exchange group-4/group-5 payloads while retaining timestamps | Coverage remains complete, but three declared-order departures are reported |
| Remove group 5 in the next closed window | Current-window coverage stays incomplete; old group's receipt age reaches **118.400182 s**; only 98/129 all-seen arrivals meet the 60 s budget |
| Remove four consecutive selected group frames | One selected-message gap reported; receipt history resets and the partial windows remain separate |
| Insert a DBC-defined but unconfigured selector 36 | One unexpected-group observation reported; it supplies no required-group coverage |

Coverage and order are separate observations: a reordered window can contain
every group, and a repeated group does not compensate for a missing different
group. Similarly, old receipt history cannot make a new window complete.

## Verification and reproduction

The streaming audit was compared with an **independent offline reference** which
reads the selector directly from the raw first payload byte, partitions records
by index, and recomputes per-arrival receipt history by brute-force scans. It does
not call the auditor, its DBC decoder or its timestamp cache.

The original and all six mutated cases match across **43 review windows**,
including complete window dictionaries: source lines, times, spans, group sets,
missing groups, duplicates and boundary annotations. Required/ignored/unexpected
accounting, declared-order departure counts, receipt-age budget counts and age
extrema also match. The reference is specific to this pinned source/profile;
agreement does not authenticate physical acquisition or the DBC's sensor meaning.

**26 new authored contract tests** cover fragments, missing groups, repeated
start/other groups, payload differences, reordered coverage, declared ignored and
unexpected selectors, gaps/history resets, bus/frame type separation, invalid
profiles, decoder failures and exact nanosecond bounds. The combined CAN-focused
run passed **58 tests**. Whole-tree Ruff checks and formatting passed. The latest
complete regression passed **2,289 tests / 46 skipped** in 144.48 s. Skips remain
44 GUI/display cases and two actual-MF4 cases with unavailable optional backends;
nine warnings are from existing adversarial overflow probes. This supersedes the
previous 2,263-pass complete run and is recorded in `CURRENT_STATE.md`.

From a Research checkout with `requirements-can.txt` installed, use new output
paths/directories:

```bash
python -m batterylog_research.can_multiplex_audit \
  model3-battery.log Model3CAN.dbc \
  batterylog_research/can_model3_multiplex_profile.json multiplex-audit.json
python -m batterylog_research.can_multiplex_validation \
  model3-battery.log Model3CAN.dbc \
  batterylog_research/can_model3_multiplex_profile.json multiplex-validation
```

The audit emits **only a JSON timing/coverage report**, with input hashes checked
before/after processing. It does not overwrite an existing result. The campaign
creates baseline/mutation reports, changed input copies and `summary.json` in the
scratch validation directory. Only the compact aggregate evidence is committed:
`batterylog_research/can_multiplex_summary_20261013.json`.

## Remaining gates

We can now expose the multiplex timing problem before any proposed full-stack
reconstruction. The next step is a second genuine BMS recording with suitable
message definitions and source-specific semantics. An authenticated sample/cycle
counter, sensor timing and justified association policy are needed before a
complete asynchronous sweep can become meaningful full-pack input.

Application checksums/counters, physical fault labels, CAN FD/ISO-TP and live
adapter capture remain unvalidated. Windows/driver, disconnect/reconnect and
sustained-recording checks still require a PC/CAN interface. No production model,
runtime dependency, schema, merge, release, public push or CI activation changed.
