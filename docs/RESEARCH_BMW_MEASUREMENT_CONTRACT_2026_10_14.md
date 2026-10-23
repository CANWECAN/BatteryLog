# BMW precharge measurement contract — step 4, 14 October 2026

**Contract specification and source audit complete; physical acceptance remains blocked.**
This specifies what a future BMW preparation must prove before it can feed the
existing Research curve observer. It is a review document, not a new runtime
configuration, Core schema or production model. No aligned capture is produced.

## Evidence and what it can establish

- Pinned candidate DBC: [EV-CANlogs BMW-i3-PT-CAN2.dbc](https://github.com/dalathegreat/EV-CANlogs/blob/9cbfc24528d9dfb2923c532f987ce1f3c278908f/BMW%20i3/BMW-i3-PT-CAN2.dbc),
  64,000 bytes, SHA-256 `667a43048f80fc6eb71a212bd90494379347a073d632056705374974eef73626`.
  This defines candidate bytes/units/labels. It does not authenticate OEM firmware.
- Pinned CSV and original log identities remain those in
  [the clock provenance audit](RESEARCH_BMW_CLOCK_PROVENANCE_2026_10_14.md).
  Clock units and the 42,949,672-tick jump remain unresolved.
- [BMW-authored I01 training manual, mirrored copy](https://bmwrepairguide.com/virtual-library/technical-training/ST1403b%20I01%20High-voltage%20Battery%20and%20Maintenance.pdf),
  section 2.4.1 / printed p43 and section 2.5.1 / printed p45 (PDF pages 50/52).
  The cover/header references ST1825/ST1403b and 2013/2014 information dates.
  It is historical architecture context, not a 2017 capture/DBC/firmware binding.
  No manual or diagram is redistributed.
- [Battery-Emulator BMW implementation](https://github.com/dalathegreat/Battery-Emulator/blob/127801268ccfe26ab40a8d4c45800962fd9b46f4/Software/src/battery/BMW-I3-BATTERY.cpp),
  pinned commit `127801268ccfe26ab40a8d4c45800962fd9b46f4`.
  Its author-observed startup behavior and practical decoding are corroborating
  implementation evidence. They are not an OEM invalid-code specification or
  authenticated policy for this capture. No third-party code is copied here.

The BMW-authored manual places a current sensor in the negative battery-terminal
path and describes separate voltage sensing in the S-box. It describes a
resistive startup path bypassing the positive main contactor, with the negative
contactor closing first. These facts explain why node/path identity matters.
They do not bind any one CAN field to a particular sensor, prove current
exclusivity to precharge, or establish this vehicle's procedure and tolerances.

## Candidate signal identities

Little-endian unsigned fields, same recorded CSV bus 1, standard IDs:

| Role | Candidate field / frame | Bits | Decode | Encoding increment |
| --- | --- | --- | --- | --- |
| Battery-current candidate | Battery_Current / 0x112 | 0–15 | raw / 10 - 819.2 A | 0.1 A |
| Battery-voltage candidate | Battery_Volts / 0x112 | 16–31 | raw / 10 V | 0.1 V |
| DC-link candidate | DC_link / 0x112 | 56–63 | raw * 4 V | 4 V |
| Reported switch-state candidate | ST_DCSW_HVSTO / 0x1FA | 12–13 | 0 OPEN, 1 PRECHRG, 2 CLOSED, 3 SNA | discrete |

These increments are encoding steps, **not** calibrated accuracy, noise bounds,
round-to-nearest guarantees or sensor bandwidth. Do not automatically assign
+/-0.05 A, +/-0.05 V or +/-2 V tolerances from them.

Current, pack and DC-link share one transport frame. This proves co-publication,
not simultaneous ADC sampling: source ages, filtering, update cadence and latency
may differ. Pack voltage could represent dedicated sensing or another
calculation; the exact node/derivation is unresolved. DC_link's name/comment does
not establish its electrical endpoints or relation to the intended capacitors.
Current sign is retained; positive charge/discharge direction is unverified.

Reported state is neither the close command nor independent mechanical feedback.
The DBC also contains RQ_DCSW_HVSTO_CLO in 0x10B and Contactor_Con in 0x3E9;
neither is promoted to a phase truth or validated command/feedback pair here.
The latter's four-bit field even declares an Invalid choice of 21, outside its
representable 0–15 range. A label table alone is insufficient acceptance evidence.

## Validity contract and a concrete metadata contradiction

All analog values retain raw codes and source indices until an authenticated
validity rule is supplied. A DBC range departure is review evidence, not an
automatic invalid-code decision.

| Candidate channel | Count | All-ones codes | Outside DBC-declared physical range |
| --- | ---: | ---: | ---: |
| Battery_Current | 8,120 | 19 | 438 |
| Battery_Volts | 8,120 | 51 | 51 |
| DC_link | 8,120 | 20 | 20 |
| ST_DCSW_HVSTO | 90 | 0 | 0 |

For Battery_Current, the DBC's range says 0 to 819.2 A, while its comment includes
negative current and the offset produces signed candidate values.
**419 recorded samples decode negative**, in addition to 19 all-ones codes above
the maximum. Blindly filtering the declared range would discard those 419 samples.
Their physical correctness is not proved, but negativity alone cannot establish
invalidity. No values are removed, clipped, sign-flipped or replaced.

Battery-Emulator notes startup 0xFFFF battery-voltage observations and ignores
raw pack readings >=10000, retaining its prior state variable. That is the
implementation's operational heuristic, not a rule adopted by BatteryLog.
A retained previous reading must not become a fresh measurement in preparation.
This finding adds corroborating startup context to #8's all-ones inventory;
it does not authenticate analog SNA codes for all three fields.

SNA state 3 is explicitly labelled invalid by the candidate DBC; it remains
unknown phase, never open/inactive by default. OPEN/CLOSED may be candidate
inactive labels only at their actual report points, with the report identity
retained. No continuous binary phase truth is inferred between reports.
The original log's opaque Flags=E and CSV metadata loss remain separate issues.

## Acquisition and phase contract

Native full-source probe independently matched 24,450 candidate values across
8,210 selected frames against cantools, preserving the 2,304 malformed CSV IDs
as unrepaired omissions from selection. Physical acceptance is not implied.

The DBC comments describe 0x112 as 10 ms and 0x1FA as 1 s. Observed raw-tick
spacing is predominantly 10 (7,705 electrical intervals) and 1000 (59 state
intervals), respectively. There are also short/event-spaced state intervals
and the known large clock jump. These counts are consistent candidate-cadence
clues; they cannot authenticate tick units, prove regular acquisition, or
authorize a maximum interpolation/hold age.

The two PRECHRG reports remain one recorded progression. State onset and end
are observation brackets, not exact switching instants. Phase latency/jitter
and sensor age must be bounded for the actual reference. The earlier nearby
electrical frames remain neighbours, not aligned phase/current/voltage rows.
No ZOH, nearest-neighbour assignment, interpolation, sorting or clock repair is
authorized by this contract.

A future producer must preserve each selected source's identity, original
line/frame index, raw timestamp, raw code and validity reason, plus acquisition
time/age and alignment method/evidence. A shared reported timestamp does not
satisfy that evidence by itself. A gap, duplicate-time ambiguity, unknown phase
or missing/invalid active measurement must remain visible to the existing
observer's conservative qualification logic.

## Acceptance gates for a real curve

| Gate | Needed evidence | Current decision |
| --- | --- | --- |
| Clock | Exact logger/exporter units, clock source and jump/reset handling | Unresolved; seconds conversion blocked |
| Mapping | Vehicle, hardware and firmware bound to this DBC selection | Unresolved |
| Nodes/current path | Pack/DC-link endpoints, current sensor/sign, parallel load contributions | Architecture context found; field binding unresolved |
| Raw validity | Analog unavailable/error codes, range semantics, stale/update policy | Contradictions recorded; not accepted |
| Phase/command/feedback | Meaning and latency of reported state; independent command/feedback where required | Candidate labels only; not accepted |
| Acquisition | Sensor update times, filtering/latency, synchronization and allowed source-age/gap bounds | Unresolved |
| Reference | Initial bus/pack voltage, actual procedure, capacitance/load, SOC/temperature and independently justified bands | None selected |

Do not choose an envelope or RC fit while these gates are unresolved. The
manual's approximate overall startup-time description is not a universal
precharge-duration limit or reference curve for this dataset.

## Reproduce and retained checks

With existing Research CAN dependencies and pinned inputs outside git:

```sh
python -m batterylog_research.bmw_measurement_contract_probe \
  --csv /path/to/bmw-charge.csv \
  --dbc /path/to/BMW-i3-PT-CAN2.dbc
```

This small evidence probe emits JSON; it does not normalize data, implement
the contract as runtime policy, or alter Core results. Inputs are hash-pinned
before use. Independent raw extraction/Decimal arithmetic is compared with
cantools at absolute tolerance 1e-12, relative tolerance zero.

[Retained results](../batterylog_research/bmw_measurement_contract_results_20261014.json)
include parsed definitions/comments/choices, raw-code counts, signed examples
and complete selected-frame raw-delta histograms.
Probe SHA-256: `0a36a043ecb396699323e088b78914319333208814bf55532a242311b62935c3`.
Native Kali complete-source probe and focused Ruff checks passed.
The full Core suite was not manually rerun for this evidence-only study;
hosted verification of the saved draft is recorded separately in its PR.

Step 4's **specification/source-audit scope** is complete, with seven physical
acceptance gates explicitly unresolved. Step 5 can implement the minimal file
interface against authored aligned fixtures. It must not bypass these gates or
claim that BMW is accepted. Steps 6–8 retain their source/reference dependencies.
No new Core behavior, production schema, dependency, license, release, merge or
live transmission.
