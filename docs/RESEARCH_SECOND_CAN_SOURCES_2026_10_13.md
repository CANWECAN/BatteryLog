# Second-vehicle CAN source eligibility — 2026-10-13

Baseline: `b8b4e59d101d520fb4296c19198020c15f3d7eac`.
Private branch: `audit/cloud-balancing-spread-20261012`.

## Outcome

Reviewed **317,435 records** from publisher-labeled Volvo EX30 battery-only and
BMW i3 charging captures. Neither source is ready for canonical BatteryLog
analysis with the available metadata. This is a concrete source-compatibility
result, not a second successful battery analysis or a new production CAN loader.

The new Research-only `can_capture_review.py` retains every parsed record as a
valid transport frame or an explicitly counted issue. It compares strict DBC
decoding against an independent decoder, keeps raw-code/range observations and
declared units, and reports blockers. It emits JSON diagnostics only. The earlier
Model 3 preparation and timing audit are unchanged.

## Provenance and reproduction

All four inputs come from [dalathegreat/EV-CANlogs](https://github.com/dalathegreat/EV-CANlogs/tree/9cbfc24528d9dfb2923c532f987ce1f3c278908f),
commit `9cbfc24528d9dfb2923c532f987ce1f3c278908f`, GPL-3.0. Two vehicles from
the same collection do not constitute independent collector or OEM validation.
Folder labels and community DBC arithmetic do not authenticate firmware matching,
sensor calibration, acquisition timing or physical fault labels.

| Local input | Original path | Bytes |
| --- | --- | ---: |
| `ex30-battery.csv` | `Geely SEA platform/Volvo EX30/EX30_battery_only.csv` | 6,457,305 |
| `Geely-SEA-platform.dbc` | `Geely SEA platform/Geely-SEA-platform.dbc` | 4,124 |
| `bmw-charge.csv` | `BMW i3/2017-60AH-REX-PT-CAN2-startcharge.csv` | 5,348,227 |
| `BMW-i3-PT-CAN2.dbc` | `BMW i3/BMW-i3-PT-CAN2.dbc` | 64,000 |

SHA-256 and source Git blob identities are pinned in `can_second_validation.py`
and the retained JSON summary. They were checked before and after the campaign.
The original captures/DBCs are outside the repository; no original source bytes
or DBC definitions are redistributed by this change. Unit tests use an authored
synthetic DBC. Existing project licensing is unchanged.

Install the isolated `batterylog_research/requirements-can.txt` dependencies
alongside normal Research runtime dependencies. Place the four byte-identical
files under the local names above, then run from a Research checkout:

```bash
python -m batterylog_research.can_second_validation SOURCE_DIRECTORY NEW_OUTPUT_DIRECTORY
```

The output directory must not already exist. The campaign writes one review per
vehicle and `summary.json`, and checks independent lexical/frame accounting and
direct-byte references. It does not retrieve mutable files automatically.

For an individual diagnostic review:

```bash
python -m batterylog_research.can_capture_review ex30-battery.csv Geely-SEA-platform.dbc ex30-review.json --layout id_payload --frame-id 0x142
python -m batterylog_research.can_capture_review bmw-charge.csv BMW-i3-PT-CAN2.dbc bmw-review.json --layout indexed_csv --frame-id 0x112 --frame-id 0x1fa --frame-id 0x426
```

## Recorded evidence

| Check | Volvo EX30 | BMW i3 |
| --- | ---: | ---: |
| Input records, excluding header | 184,494 | 132,941 |
| Syntactically valid transport records | 184,494 | 130,637 |
| Malformed records | 0 | 2,304 |
| Selected message frames | 16,978 | 8,210 |
| Frames fully decoded by both libraries | 620 | 8,210 |
| Strict DBC decode rejections | 16,358 | 0 |
| Partial canmatrix returns after strict rejection | 16,358 | 0 |
| Full-decode numeric values compared | 1,395 | 74,610 |
| Separate direct-byte values compared | 1,395 | 16,600 |

Libraries: cantools 44.2.1 and canmatrix 1.2. Numeric comparisons use absolute
tolerance 1e-12 and relative tolerance 0. Maximum library difference was zero
for EX30 and 5.684341886080802e-14 for BMW. Direct-byte references matched all
17,995 tested values; agreement is strictly about the candidate DBC arithmetic.

### Volvo EX30: missing time and incomplete/uncertain definitions

The CSV header is exactly `ID,Data Bytes`. It has no timestamp, bus, DLC or
standard/extended flag. An eight-digit padded identifier does not establish an
extended frame. Diagnostic decoding follows the candidate DBC's message type;
the source's missing frame-type metadata remains an explicit blocker.

ID 0x142 has selectors **0–109** in the source. The DBC's machine-readable
branches define only **0, 1, 2, 3**, each observed 155 times. Its comment mentions
later cell messages, but that is not a complete bit layout or validated topology.
No branch is generated from the comment and no physical cell index is guessed.

cantools rejects the remaining **16,358** frames for undeclared multiplex
branches. canmatrix returns only the common selector field for these frames.
A nonempty decoder dictionary therefore cannot be treated as a complete decode.
The reviewer explicitly counts those partial results without accepting voltage
measurements from them.

Even the fully decoded values raise interpretation questions. The declared
`cell_min_voltage` and `cellvoltages` fields produce **30,289–30,297 mV**, and
`cell_max_voltage` produces **30,705–30,713 mV**, outside the DBC's declared
0–5,000 mV ranges. The pack field produces **32,897–32,905** with ambiguous unit
**`V+1`**. These are recorded candidate-DBC outputs, not confirmed battery
voltages. We did not divide by an invented scale, shift bits, rewrite units or
declare a physical overvoltage. A source/DBC mismatch, missing encoding semantics
or other cause remains unresolved.

Without timestamps, this source cannot establish current/temperature association,
receipt age, cycle duration, sample spacing or simultaneous pack measurements.
No synthetic time axis or canonical CSV is produced.

### BMW i3: malformed identifiers and unverified validity codes

The BOM-prefixed CSV has explicit `Time Stamp,ID,Extended,Bus,DLC,D1,...,D8`
columns. **2,304** ID strings fail hexadecimal syntax; the first is at physical
line **49**, `2.00E+02`. Other examples include `2.00E+08` and `3.00E+05`.
These resemble spreadsheet notation damage, but the cause and original IDs are
not authenticated. Decimal conversion or guessing the original hex would erase
source uncertainty. Legal hexadecimal such as `2e2` remains accepted as 0x2E2.

All input rows stay in diagnostic accounting. Only valid transport records are
decoded: **8,120** ID 0x112 frames and **90** ID 0x1FA frames. Selected ID
**0x426 is absent**. Its DBC's `DT_U_CELL` is a 56-bit raw field with no physical
voltage unit; it cannot be treated as a scalar cell voltage even if encountered.

The decoded startup maxima include **6,553.5 Volts**, **5,734.3 Amps**,
**409.5% SOC** and **205 C**. For the relevant signals these coincide with an
all-ones raw encoding. The review counts raw bit patterns and declared-range
departures separately; it neither authenticates them as invalid codes nor labels
them as physical extremes. For example, 51 voltage observations have raw 0xFFFF,
and the three relevant temperature fields each have three raw 0xFF observations.

DBC metadata also declares a nonnegative minimum for current despite its negative
offset and a comment describing negative current. Validly decoded current reaches
**-13 Amps**. This is retained, not clipped or discarded by an inconsistent range.
Declared-range observations alone are not a validity policy or battery diagnosis.

The capture has raw clock ticks, but their unit is unverified. Review validates
nondecreasing ticks and preserves the range for valid records; it does not infer
seconds, charging duration, sample age or temperature/current alignment. A source
logger export convention or approximate clock correlation cannot substitute for
authenticated timing metadata.

## Tests and transfer decision

Thirty-two contract tests cover malformed width/ID/DLC/bytes/padding, hexadecimal E,
clock regressions even behind invalid or unselected IDs, multiline physical-line
provenance, fatal CSV grammar/header errors, unknown-selector partial returns,
frame-type mismatches, absent selected IDs, complete counting with bounded
examples, duplicate preservation, decoder disagreement (including bit-exact
56-bit integer comparisons), retained all-ones and
negative values, and staged output/no overwrite. No original field data are
modified and synthetic DBC tests are not physical fault experiments.

Final complete cloud regression: **2,321 passed, 46 skipped, nine warnings in
163.76 s** on Python 3.12.14. Skips are 44 GUI/display cases and two actual
optional MF4 backend cases; warnings are existing deliberate overflow probes.
Whole-tree Ruff check and formatting passed. Native Windows/Tk and physical
adapter capture were not run. This final run includes the integer precision
hardening and supersedes the earlier 2,289-pass multiplex checkpoint.

Both reviews report `analysis_preparation_eligible: false`. This reviewer is
intentionally a diagnostic tool: it has no interface that establishes a complete
canonical mapping, units, invalid-code policy or acquisition alignment, so even
a clean transport-only review cannot approve native BatteryLog preparation.

The next transfer gate needs a timestamped BMS capture plus complete, source-matched
signal definitions, documented clock units and validity codes. Cell identity and
acquisition/cycle timing must be justified before assembling multiplex data.
These two captures remain useful negative compatibility fixtures and arithmetic
references, while the earlier limited Model 3 bridge remains the only tested
native CAN-to-BatteryLog path. Live adapter/Windows/reconnect/long recording,
CAN FD/ISO-TP, application counters/CRC and physical fault-label validation remain
separate outstanding work. No production status, GUI, schema, release, merge,
public push, workflow activation or license change is included.
