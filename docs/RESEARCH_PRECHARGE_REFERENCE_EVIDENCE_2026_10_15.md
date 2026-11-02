# Step 7: independent normal-reference evidence - 15 October 2026

**Step 7 is not complete. No physical normal reference was accepted.**
This checkpoint audits a second pinned BMW capture and documents why it cannot
yet be used as the normal envelope. It does not reopen the unrelated Windows/Tk
investigation or manufacture an RC baseline.

## Source and reproducibility

Environment: Windows. Source parent: e8cb99dcf3e621fbcd792fa1f5bdbc88bde7b3e6.
This study adds documentation and compact qualification evidence.

The separate candidate is BMW i3/2017-60AH-REX-PT-CAN2-startup, from
[EV-CANlogs at 9cbfc245](https://github.com/dalathegreat/EV-CANlogs/tree/9cbfc24528d9dfb2923c532f987ce1f3c278908f/BMW%20i3).
The root README only describes a collection of CAN data from EV projects.
A different filename does not authenticate a separate healthy experiment.

| Input | Bytes | Git blob | SHA-256 |
| --- | ---: | --- | --- |
| startup.csv | 6,129,617 | 5fbdb1e92836f0b88548736505be08d0a3daf48a | fde91ff7dab0230746788c72c21fa8baf8408a4a20556381c1727bf083acf8ae |
| startup.log | 11,386,333 | 7f1b025e71b4f2ba4eb1b056ebcf87206799c656 | bf8aed7e9c252c39a36aa1e155a7fecdad3d1dbc0e638567e73cd6f2cae98b1e |

DBC remains the previously pinned BMW-i3-PT-CAN2.dbc,
SHA-256 667a43048f80fc6eb71a212bd90494379347a073d632056705374974eef73626.
Downloads were bounded to the expected size plus one byte; lengths and Git
blob hashes were checked before saving. Input SHA-256 hashes were rechecked
after analysis. Third-party raw files and the DBC remain outside git.

The one-off native audit script uses independent csv readers for ordinal
timestamp/DLC/payload comparisons, original log IDs for selection, and manual
bit extraction compared with cantools for every selected signal. It does not
call or weaken the production pinned BMW builder.
Audit script SHA-256:
92c6106b3169a346bd5c37ae09677d43d9330264836ff37d8a88b58df5a70cf6.
Script and inputs are retained in the native batterylog-step7-reference-20261015-evidence directory.
Compact results: [candidate JSON](evidence/bmw_startup_reference_candidate_20261015.json).
Source indices are zero-based; physical file lines are one-based.

## Actual candidate findings

- All 153,055 ordinal timestamps, DLCs and payloads match between original log
  and CSV. The 150,439 parseable CSV IDs match; 2,616 malformed scientific-looking
  CSV ID tokens remain unrepaired.
- 9,389 electrical frames (0x112) plus 102 reported-state frames (0x1FA);
  28,269 manual byte/DBC value comparisons, zero mismatches.
- Reported state counts: 12 OPEN, two PRECHRG, 88 CLOSED. This is one observed
  OPEN -> PRECHRG -> CLOSED progression, not two activations or a healthy label.
- PRECHRG reports occur at physical lines 12,601 and 12,970, raw ticks
  2,473,902 and 2,474,122. First CLOSED is line 13,058, tick 2,474,173.
- Around the first PRECHRG report the neighboring electrical rows have
  candidate pack 390.6 V / DC link 40 V / current 0 A. Around first CLOSED
  they have pack 390.5 V / DC link 392 V / current -0.1 A.
  These are separate source rows, not simultaneous or aligned phase samples.
  They are not authenticated activation initial conditions.
- Raw ticks span 2,466,116 to 2,560,000, with 83,155 adjacent duplicates,
  no backward deltas and largest adjacent delta 10. Unlike startcharge, this
  candidate has no large adjacent jump. That does not establish tick units.
- Raw all-ones counts: current 19, pack 50, DC link 20. All are retained.
  DBC range departures: current 8,625 (8,606 negative candidates plus 19 above
  the declared maximum), pack 50, DC link 20. Negative current is not removed.
- Metadata still says Default Parser, channel 0 -> CSV bus 1, Extended=0
  throughout, with one opaque Flags=E row. Logger identity/version, physical
  units, acquisition age/filter bounds and exact sensor validity remain open.

The prior startcharge candidate had neighboring DC-link candidate 0 V at its
first PRECHRG report; startup has 40 V. Similar pack voltage is insufficient
for comparability. Neither neighboring value is assumed to be the actual
switch-on initial voltage. We do not fit one capture and call the fit an
independent reference for that same capture.

## External primary-source review

[Sensata, How to Design a Precharge Circuit](https://www.sensata.com/sites/default/files/a/sensata-how-to-design-precharge-circuits-evs-whitepaper.pdf),
PDF pp. 5-6 and 10-11, relates resistive charging to circuit parameters and
requires validation over operating conditions and component tolerances.
It is useful design guidance, not a normal BMW capture or a universal band.
Its example values and five-time-constant convention are not adopted as BMW
acceptance limits.

[TI TIDA-050063, TIDUF21A Rev. A](https://www.ti.com/lit/ug/tiduf21a/tiduf21a.pdf),
PDF pp. 2-5 and 13-17, documents an active buck precharge design and measured
400/800 V, 2 mF scope examples. The guide distinguishes input and output
current. Inference: this different topology and measurement path do not supply
a comparable BMW resistive-precharge normal envelope. The inspected guide
provides figures rather than the aligned raw channel export required here;
no curve was digitized or treated as a population tolerance band.

[BMW I01 training, ST1403b](https://bmwrepairguide.com/virtual-library/technical-training/ST1403b%20I01%20High-voltage%20Battery%20and%20Maintenance.pdf),
PDF p. 52 / printed p. 45, describes negative contactor closure followed by a
resistive positive parallel path. This architecture context does not bind the
2017 capture to a particular sensor/firmware revision or normal tolerance.

These conclusions apply to the inspected artifacts; they are not a claim
that suitable evidence cannot exist elsewhere.

## Required physical reference evidence

A producer or controlled laboratory export must supply the following evidence
for the particular target system. Existing measurement-contract gates still apply.

| Evidence | Required content |
| --- | --- |
| Provenance and normal qualification | Original immutable channels; run identity; exact system/firmware; independently justified healthy designation for a measured reference |
| Initial conditions | Measured pack and bus voltages before activation; SOC/temperature ranges and reset/discharge state |
| Circuit and procedure | Actual topology, resistance/capacitance or measured load characterization, enabled parallel loads, start/stop procedure |
| Time and channels | Logger units/version, phase/feedback semantics, measurement nodes and current sign/path, validity/update/filter/age and synchronization bounds |
| Reference construction | Independent design/component evidence or separately qualified reference runs; declared applicability range; justified variability and measurement uncertainty; frozen envelope and source hashes before evaluating the held-out run |

No numeric tolerance, required run count or sampling rate is invented here.
Those must follow the intended operating range, instrumentation and shortest
feature to be resolved. A single successful startup cannot establish a general
normal population band. A controlled export from another system can qualify
only that explicitly documented scope; it does not qualify BMW by analogy.

Existing software file-review context declarations are not authentication.
Do not fill the context with unverified claims, reuse the synthetic exp(-t)
fixture as measured evidence, repair unknown clock units, or interpolate raw
samples to bridge missing coverage.

## Validation and remaining state

All 24 existing numeric-control regressions passed (1.71 s). No new full-suite
native run or physical curve evaluation was performed for this documentation.
Parent CI 38802396896 passed at e8cb99d; it is prior-source evidence.

The raw trace is complete in its software scope. Physical alignment and normal
reference acceptance remain unqualified, so physical curve review cannot start.
The separate single-process native Tk setup issue remains unresolved.

## Alternative-source follow-up - 16 October 2026, Europe/Istanbul

Physical reference acceptance requires independently documented acquisition,
comparable normal bounds and a qualified evaluation capture. File availability
alone does not establish those conditions.

| Inspected source | Finding | Decision for this checkpoint |
| --- | --- | --- |
| Infineon REF-SSBD800VDCJCQJ1, UG-2025-14 Rev. 1.0 (2026-02-12), PDF pp. 6, 12 and 29-30 | The GUI supports CSV export, but the precharge unit is optional and outside the supplied demonstrator; calibration scaling is adjustable | Export capability is not an available qualified precharge experiment |
| foxBMS 2, pinned repository below; precharging documentation 1.12.0 | Design/state guidance; dimensioning section explicitly incomplete. Inspected plot and ETL examples do not supply the required target capture/context | Not accepted as an independent physical normal reference |
| Alain Stas, EV Battery Pre Charge Simulated in Qspice with PTC (2023-09-19) | The author's page explicitly describes simulation output, including its downloadable raw simulation data | Simulation cannot close the first real-curve review gate |

Source links:
- [Infineon guide](https://www.infineon.com/assets/row/public/documents/non-assigned/44/infineon-solid-state-battery-disconnect-unit-demonstrator-usermanual-en.pdf)
- [foxBMS precharging](https://docs.foxbms.org/system/precharging.html)
- [foxBMS pinned repository](https://github.com/foxBMS/foxbms-2/tree/73dbde670f7e9ec59afc33855bcf27576bd874de)
- [Qspice author's project](https://www.hackster.io/alainstas/ev-battery-pre-charge-simulated-in-qspice-with-ptc-6940f4)

foxBMS master was resolved from repository metadata, then pinned to
73dbde670f7e9ec59afc33855bcf27576bd874de (6 October 2026).
Its complete returned tree has 3,790 paths, truncated=false. A path/suffix
inventory identified 204 candidates: 200 CSV, one TRC, one ZIP, one RST and one
Draw.io file. This is a bounded inventory of that commit, not an assertion about
every release, branch, attachment, arbitrary file format or dataset elsewhere.

The apparently useful candidates were read:
- docs/tools/fox/plot/img/example_data.csv: 98 data rows, columns Test Time,
  Step Time(ms), Voltage(V), Current(A); voltage 3.8668-4.1996 V. It has neither
  a second voltage channel nor a precharge phase channel.
- tests/fox-cmds/etl/test_graphtec.csv and its converted companion: a ten-row
  ETL fixture. Header metadata declares 4,297 points for the original session;
  that complete session is not present in this ten-row file. Instrument header:
  GL820, 100 ms. The displayed channel configuration identifies temperature
  channels. No qualified pack/DC-link/phase mapping or healthy reference is
  supplied by these inspected artifacts.
- tests/fox-cmds/etl/can-log.trc: nine raw transport rows in an ETL fixture,
  not a documented independently qualified precharge reference.
- docs/system/measured-voltages-and-current-in-the-pack.csv is a terminology
  table, not time-series measurement data.

No third-party source or simulation code was imported into BatteryLog.
No physical envelope, guessed time unit, normal label or numeric threshold was
added. This documentation follow-up changes no executable code; the existing
native 24-case and hosted 12/12 results at 80fbae4 remain historical verification
of that exact head. A newly triggered hosted run must be recorded separately.

Practical next dependency: obtain original pack/DC-link/current/phase channels
with authenticated time/acquisition context, initial state and actual load/
procedure, plus independently justified reference bounds. Another documented
system can support a scoped first review, but cannot qualify BMW by analogy.

## Broader data search and actual download - 16 October 2026

A larger search covered published EV/CAN collections, data repositories,
laboratory capacitor charging experiments, and English/Chinese source terms.
The bounded results below do not assert that no suitable dataset exists elsewhere.

### Downloaded experimental candidate

[Mendeley Data, DOI 10.17632/8smzhh6mxm.1](https://data.mendeley.com/datasets/8smzhh6mxm/1),
version 1, published 9 September 2026 by zutao zhang, declares CC BY 4.0.
It describes energy-harvesting experiments for a freight-train sensing system,
including BQ25570 capacitor charging/cold start. This is a different circuit
scope, not vehicle/BMW evidence.

The public inventory lists 13 root files totaling 113,664,182 bytes. Only
README.md and 05_Capacitor_charging.zip were downloaded. The ZIP has 24,759 bytes,
SHA-256 7a58d14c96203f6d23c072ca4f3a37f2393f99903ff6f137e31d4c0470e36dbe.
The README has 4,112 bytes, SHA-256
45a847b17aab5856a8931de6fc289567b46fa8c3c3d7448ec9b794cffb8b9ca6.

Five CSV files contain 3,309 data rows. Each has exactly Time(s), CH1V columns:
RigolDS122 879 rows, 123 776, 124 521, 125 581 and 126 552.
The source summary workbook associates these files with nominal 1000, 2200,
100, 47 and 22 uF labels respectively. These labels are not independent
capacitance calibration. Source voltage, current and phase channels are absent
from the inspected files; the physical voltage node and probe scaling are not
authenticated by the column name alone. Normal reference and curve eligibility
both remain false.

Strict CSV parsing, two-column width, finite Decimal values and strictly
increasing timestamps passed for all five files. Original negative time offsets
and negative voltage samples remain unchanged. There was no smoothing, clipping,
differentiation-based fabricated current, guessed phase, fit or envelope.
The archive hash was rechecked after inspection. Raw third-party files and the
source workbook remain outside git. Only owned compact inventory/qualification
evidence is saved:
[dataset search JSON](evidence/precharge_dataset_search_20261016.json).

### Other concrete leads

- [Chalmers thesis 543724](https://research.chalmers.se/publication/543724/file/543724_Fulltext.pdf),
  Paper E, PDF pp. 151 and 165: six Lynk & Co PHEVs, over 1 TB collection, nominal
  20 ms pack voltage/current. Its resource statement says release will follow
  manuscript review. A current direct raw-data download was not verified.
  DC-link/phase channels and independent precharge bounds were not verified.
  The paper's interpolated 0.5/1 s processed series is not assumed to preserve
  the startup transient. No terabyte transfer is proposed without a signal
  inventory and a small original startup segment.
- [Circuit-Analysis-and-Characterization](https://github.com/abdelachbani/Circuit-Analysis-and-Characterization/tree/6cab12744975433595be5230232fda414a3647a8):
  the 380-byte capacitor_rc_transients.csv contains summary time constants and
  derived capacitance rather than the raw curve its filename might suggest.
- [Faure et al., arXiv:2501.12028v1](https://arxiv.org/html/2501.12028v1):
  a documented 1296-ohm/47-uF laboratory experiment with roughly 50,000 values
  per record is described. No raw trace download was identified in the inspected
  article. Its experimental fit/error discussion is not adopted as a BMW band.
- Access to the inspected MDPI full-text endpoints was blocked (403); these
  papers were not treated as checked raw datasets or as proof of data absence.

### Steps 7-10 and current boundary

7. Qualify a comparable independent normal reference, including initial
   voltages, actual load/procedure and justified tolerances/uncertainty.
8. Evaluate a separate qualifying real capture against that frozen reference,
   reporting deviations, incomplete coverage and timing uncertainty separately.
9. Exercise passive physical CAN-adapter recording: disconnect/reconnect,
   sustained capture and preservation of recorded evidence. Offline datasets
   cannot complete the physical lifecycle requirement.
10. Assemble and test an explicitly reviewed private integration candidate,
    then obtain an engineer pilot's independent workflow feedback. Merge and
    release remain separate final decisions.

The latest prior documentation head 00cc8f1 passed hosted run 38807130061:
all 12 job conclusions were inspected. Its executable sources are unchanged.
This data-search checkpoint adds only documentation and compact evidence;
scope, whitespace, strict JSON and downloaded-input invariants are checked.
It adds no new executable code and no new native full-suite claim.
New-head hosted status is recorded separately in the draft PR.

## Ioniq CCS protocol candidate - 17 October 2026

Pinned source: [uhi22/Ioniq28Investigations,
208c0e95d0078fe0b351e541f026701495cae862](https://github.com/uhi22/Ioniq28Investigations/tree/208c0e95d0078fe0b351e541f026701495cae862/CCM_ChargeControlModule_PLC_CCS).
Six source files were actually downloaded with expected-size-plus-one bounds,
expected lengths and Git blob SHA-1 checks; SHA-256 was rechecked after inspection.
Raw third-party inputs and owned audit scripts stay outside git. The saved
[compact qualification](evidence/ioniq_precharge_qualification_20261017.json)
contains pins, hashes, counts and explicit false acceptance flags.

The Compleo raw SPI CSV is 22,762,729 bytes / 644,965 data rows, all five columns
(name, type, start_time, mosi, miso). The author's README describes a Saleae
digital SPI recording at 50 MS/s. This digital sampling rate is not an analog
current/voltage sensor sampling rate.

| Published decoded export | Packet objects | PreChargeReq / Res | EVTargetCurrent in Req | EVSEPresentCurrent in Res |
| --- | ---: | ---: | --- | ---: |
| Compleo full charge | 2,308 | 11 / 11 | 1 A command in all 11 | 0 |
| Alpitronic file named twoSessions | 874 | 12 / 12 | 1 A command in all 12 | 0 |

Both files contain one nonempty published decoder-error object. Parsing the
published JSON is not independent EXI decoding; no raw-decoder reproduction is
claimed. The twoSessions filename is not proof of two independent normal tests.
All 7,012 entries in the two values exports parse with finite Decimal values;
per-field timestamps never move backwards. Publisher floating-point artifacts
such as 388.70000000000005 are preserved, not silently normalized.

The 23 PreCharge requests contain current/voltage targets; the 23 responses
contain EVSEPresentVoltage but no EVSEPresentCurrent. CurrentDemand response
current later in the session cannot fill precharge current. EVTargetVoltage
cannot become measured pack voltage. EVSEPresentVoltage cannot become a proven
inverter DC-link node. No current, phase, measurement time, alignment, normal band
or physical pass/fail was manufactured.

This source therefore does not qualify for steps 7-8. Charger-side CCS precharge
also cannot establish normal BMW pack-to-inverter precharge behavior. Analog
sample clock, update age/filter/synchronization, node/current-path mapping,
load/initial conditions, calibration and independent healthy bounds are missing.

### Minimum additional acquisition evidence

Before any large download, request an original startup segment and its signal
inventory from the producer/laboratory. A documented low-voltage laboratory
capture can be considered under its own explicit scope if BMW acquisition facts
remain unavailable. Required package:

- Original measured pack/source voltage, relevant DC-link/capacitor voltage,
  current with path/sign, and observed precharge state or command/feedback.
  Include pre-activation samples and sufficient post-activation coverage.
- Logger/time units, vehicle or circuit/hardware/firmware binding, DBC/channel
  definitions, invalid/stale behavior, update/filter delays, synchronization and
  measurement uncertainty. Keep native asynchronous rows where alignment is
  not independently justified.
- Actual initial voltages, load/capacitance evidence, procedure and relevant
  temperature/SOC conditions; do not infer these from neighboring CAN rows.
- Separate qualified normal experiments or independent design/component
  evidence that justifies applicable bounds and their uncertainty. Freeze the
  reference before evaluating a different real capture.

The file CLI requires timestamp_s, precharge_active, current_a, pack_voltage_v
and dc_link_voltage_v with a complete context declaration. These names do not
authenticate a physical capture. The Ioniq commands cannot substitute for measured
channels or justify invented alignment. Access to the Chinese traction-capacitor
article remains unverified; that is not evidence that raw data does not exist.

### Verification boundary

At df9cf68b1b213e246bd90aa857fb4552b880832a, hosted run 38810085613 has
completed successfully; all 12 job conclusions were inspected on 17 October.
This is the previously pending run, not a new test run. The new source audit
checks bounded downloads, hashes, strict CSV widths, finite values, decoded
object parsing and repeatability. No executable source changed and no new
native full-suite run was needed. The local single-process Tk issue remains
open; source qualification does not close it. Steps 7 and 8 remain incomplete.

## Source qualification continuation - 17 October 2026

Environment: Windows. Source parent 3d4a3ce6 changes documentation/evidence
only relative to df9cf68b. Parent CI 38810085613 passed all 12 jobs at df9cf68b;
it does not validate a later documentation revision. Adapter capture remains
deferred pending hardware.

### Dortmund charging data: inventory downloaded, internal precharge unproven

[Published v2 record](https://zenodo.org/records/14065331) and its
[Data Descriptor](https://doi.org/10.1038/s41597-025-05524-5) describe laboratory
charging experiments. Both small dictionaries were actually downloaded on
Windows; the published MD5 values match and SHA-256 was rechecked after inspection:

| File | Bytes | MD5 | SHA-256 |
| --- | ---: | --- | --- |
| parameters.csv | 76,991 | 55a479a1a34114a81da6bbc233cda419 | 16c60ab66160c0c04d869e6fdff31c8597ca18d791e6eeb0ff2dbc86b37e173c |
| measurements.csv | 20,133 | 332378d8e25b2edf808f3f05a610fdc1 | 3f5030134f0ef40abf9716fb0301f16ab64af71d9ca688e2282de66164ae029f |

Strict semicolon CSV widths and unique headers passed. There are 883 parameter
rows and 142 trials over eight named vehicle models. Counts by dictionary type:
C=27, E=42, G=32, shared G/C timestamp=1, H=781. No parameter description/name
matches precharge, contactor or DC-link terms. Manual review of the relevant
dictionary entries identifies charger output and external CCS/CHAdeMO plug
voltage/current, rather than a documented internal pack/DC-link pair, current
measurement path and precharge phase. Absence of a term alone is not the decision.

Inference: these measurements can support charging/grid work, but the inspected
metadata do not qualify the internal precharge target. Neither the 389.8 MB raw
archive nor the 207.7 MB merged archive was downloaded; source-level absence in
every waveform file is not claimed. No physical envelope is derived from them.

### The one-terabyte PHEV lead needs raw startup data

[Chalmers thesis](https://research.chalmers.se/publication/543724/file/543724_Fulltext.pdf),
PDF pages 151, 165-166, describes nominal 20 ms pack voltage/current collection
but a different processing pipeline for the aging study: driving channels are
linearly interpolated to 0.5 s and charging channels to 1 s. That pipeline also
removes some default-valued vehicle-initialization samples. The thesis reports
about 1 TB raw input reduced to 5.6 GB after processing.

Inference: the processed aging output cannot be assumed to preserve a faithful
precharge opening transient, original gaps or unknown values. It is not accepted
for steps 7-8. A current public raw-download link remains unverified. Ask for a
small unmodified startup subset plus signal/timing/measurement documentation
before considering a full transfer. A large download alone does not close the gate.

### A separate 2026 fleet-data lead

[Rico-dicp repository](https://github.com/Rico-dicp/Ev-battery-cell-to-cell-inconsistency)
was inspected at dc1dd9226d2c01450b1afb1c8a378b7eb293c291. Pinned README,
DATA_LINK and preprocessing-source lengths/Git blobs were independently verified.
The source lists 40 NMC and 20 LFP Parquet parts via a public external link.
The inspected consumer selects pack total voltage/current, vehicle/charging status,
cell measurements, SOC and temperatures. It does not establish the internal
DC-link/precharge-path/phase channels required here.

This is a separate publication; equivalence to the six-PHEV thesis dataset is
not established. Linked Parquet files were not downloaded and their full schema
is unverified;
additional columns cannot be ruled out. No external code was executed.

### Existing parser boundary and continuity

The five actual Mendeley voltage-only CSVs and both Dortmund dictionary CSVs
were passed unchanged to the existing aligned-CSV header parser: seven expected
rejections, all reporting the exact required-header error, zero observer calls.
This checks input format only; it does not authenticate producer declarations,
test full CLI publication, or create a physical curve. Mendeley ZIP SHA-256
remained 7a58d14c96203f6d23c072ca4f3a37f2393f99903ff6f137e31d4c0470e36dbe.

Both existing focused files passed on native Windows: **83 passed in 3.68 s**
(file interface and numeric-control boundary regressions). No new full native
suite, coverage percentage, GUI-stability result or physical accuracy is claimed.

Owned compact evidence is
[evidence/precharge_source_qualification_20261017.json](evidence/precharge_source_qualification_20261017.json).
Bounded download/audit scripts, original source bytes, parser results and focused
test log are retained outside git in native sibling directory
batterylog-step78-data-20261017-evidence. Third-party files/code are not copied
into Research. Only documentation and compact evidence change in this checkpoint.

**Steps 7 and 8 remain open. Step 9 is deferred for unavailable hardware.**
The next useful input is a small documented raw precharge capture and a separate
qualified normal reference or independent design bounds, with original channel
timestamps, both voltage nodes, measured current path and phase evidence.
