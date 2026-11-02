# BatteryLog experimental tools

These first-party modules are included in the single Apache-2.0 BatteryLog package.
Use [the root quick start](../README.md) and [licensing inventory](../docs/LICENSING.md).
The internal namespace is retained for compatibility; it is not a paid edition.

The recommended entry point is batterylog experimental can|precharge|replay.
Source-review/campaign modules remain experimental developer interfaces. Source
code visibility and installed availability do not establish physical qualification.

## Experimental temperature triage

See [temperature source-review tool](../docs/RESEARCH_TEMPERATURE_TRIAGE.md).
This isolated script inspects result-v9 temperature-rise event evidence with
explicit review bounds and never mutates results or filters measurement rows.

## Experimental peer-relative voltage-step experiment (2026-10-12)

The Research prototype `voltage_step_audit.py` reports sampled cell-voltage
changes relative to the median change across three or more series cells.
It does **not** diagnose a defective cell, a sensor fault, SOH or safety.
It preserves observed pack-current change as context and requires a
source-verified synchronous series-cell capture.

Example from a *Research checkout* (limits are illustrative only):

    python -m batterylog_research.voltage_step_audit normalized.csv \
      --peer-step-threshold-v 0.1 --max-gap-s 1

This observer cannot justify production fault thresholds. It does not
modify existing BatteryLog PASS/FAIL or report schemas. Synthetic tests
and the full review document were run in an isolated cloud environment;
a strict peer majority is required to flag a cell step. If no majority
supports the median, `ambiguous_peer_reference_pairs` records the uncertain
interval instead of pretending it is clean. The repository's top-level
`tests/test_research_voltage_steps.py` and
`tests/test_research_voltage_csv_contract.py` cover this experimental behavior.
The full BatteryLog regression and physical ground-truth review remain pending.

## Offline CAN preparation (2026-10-13)

`can_prepare.py` converts selected classic candump + DBC signals to canonical
measurements using explicit frame-age bounds and a separate alignment evidence
file. Selected brick voltages must share an anchor frame. Missing/expired context
remains missing; no future message repairs earlier rows. This is experimental
source preparation, not a production CAN loader or live bus interface.

The first pinned Model 3 campaign uses three same-frame brick groups and BMS
temperature extrema. It does not establish a complete series stack, fixed local
temperature sensors, current direction or physical fault labels. Dependencies are
isolated in `requirements-can.txt`; `can_cloud_validation.py` reproduces decoder,
raw-byte, native-analysis and hostile checks. See
[first CAN bridge evidence](../docs/RESEARCH_FIRST_CAN_BRIDGE_2026_10_13.md).

## Multiplex coverage and timing audit (2026-10-13)

`can_multiplex_audit.py` reports declared group coverage, fragments, repeats,
order departures, selected-frame gaps and recorded receipt ages. It produces
only timing/coverage JSON and never assembles voltage frames into a common
pack snapshot. Window boundaries are explicitly unauthenticated start-group
partitions. The pinned `can_multiplex_validation.py` campaign compares the
original recording and six synthetic changes against an independent raw-byte
and brute-force timing reference. See
[multiplex timing evidence](../docs/RESEARCH_CAN_MULTIPLEX_TIMING_2026_10_13.md).

## Second-vehicle source compatibility (2026-10-13)

`can_capture_review.py` reviews two explicit classic CAN CSV layouts against a
candidate DBC, retains malformed-record accounting and compares full decodes with
canmatrix. Partial multiplex dictionaries are counted as incomplete; raw all-ones
codes, declared ranges and units remain review evidence. It emits only JSON and
always requires additional mapping/timing work before measurement preparation.
`can_second_validation.py` pins EX30/BMW source identities and checks both reviews
against separate lexical and direct-byte references. Neither source currently
meets canonical analysis requirements. See
[second-source evidence](../docs/RESEARCH_SECOND_CAN_SOURCES_2026_10_13.md).

## Native Windows and offline CAN verification (2026-10-13)

The current Research snapshot passed native Windows/Tk and offline CAN checks.
A Windows collection failure in `field_stress.py` was fixed by keeping Linux's
optional peak-RSS measurement behind a platform guard; other platforms report
that metric as unavailable. Battery analysis is unchanged. See
[Windows verification evidence](../docs/RESEARCH_WINDOWS_CAN_VALIDATION_2026_10_13.md)
for exact suite/skip/coverage results and source-matched CAN campaigns.


## Offline CAN replay and recorder lifecycle (2026-10-17)

`python -m batterylog_research.can_replay capture.log /path/to/new-session`
replays strict classic candump records on demand into a bounded single-owner
journal. Exact decimal time, message bytes, source lines and identifier types
are retained. Pause/stop/EOF, queue loss, simulated source reconnect and writer
failure have explicit states; incomplete sessions retain .part data.
The source hash covers exactly the consumed byte prefix, with EOF stated.
This is software lifecycle verification with no CAN interface or bus transmission.
See [the replay contract and evidence](../docs/RESEARCH_CAN_OFFLINE_REPLAY_2026_10_17.md).
