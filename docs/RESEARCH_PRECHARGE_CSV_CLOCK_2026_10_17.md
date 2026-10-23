# Precharge CSV clock precision - 17 October 2026

The aligned-file Research reviewer now subtracts decimal timestamps before
converting the resulting durations to binary64. Previously it converted absolute
timestamps first. At Unix-scale clock values this could hide a source gap, finish
a reference horizon early, or hide a departure from a time-varying declared band.
This is a software correction, not completion of physical steps 7 or 8.

## Reproduction and behavior

Base: 73b5389b9c6858b60cd76c150e8f86e5ceff0e96 (draft #16).
The same authored capture at clock origins zero, 1,800,000,000 and 10**12
seconds produced different decisions before this change:

| Encoded elapsed time | Declared limit | Required observation | Old large-origin result |
| --- | --- | --- | --- |
| 1.0000001 s | maximum gap 1 s | interrupted source interval | interval covered |
| 0.99999999 s | horizon 1 s, then phase ends | incomplete horizon | interval covered |
| 0.50000001 s | current upper bound 1 - elapsed, measured 0.5 A | one band departure | departure hidden |

CSV decimal values now survive span selection. Adjacent source intervals and
elapsed time from each observed activation use exact decimal subtraction in a
local context sized for the operands, then convert the duration to binary64.
A long inactive prefix cannot remove the precision available to a later
activation. The local arithmetic does not depend on caller decimal precision
or exponent settings. Measurements and reference interpolation retain their
existing binary64 behavior and tolerance.

Legacy numeric timestamp display fields remain source-clock binary64 values.
They can still display equal values for distinct high-resolution source times.
Additive string fields active_start_time_s_decimal, active_end_time_s_decimal
and observed_start_bracket_s_decimal carry the exact decimal endpoint values.
These are decimal values, not a promise to preserve the original token spelling.
The byte snapshot, hash and CSV line references still identify the original input.
Capture metadata states the arithmetic policy.

The ordinary floating-array API remains unchanged. It cannot recover precision
already lost before the caller supplies an array. Duplicate encoded timestamps
still interrupt qualification. No time scaling, clock-unit inference,
resampling, interpolation of source samples or physical reference fitting occurs.

## Independent authored checks

The external campaign compares old and new imports in separate processes, using
the same immutable CSV/context bytes and hand-declared expected outcomes. It
contains 1,200 boundary cases: four scenarios, 30 margins from 10**-5 to
3*10**-14, five positive/negative clock origins and two inactive-prefix forms.

| Scenario | Cases | Old disagreements | New disagreements |
| --- | ---: | ---: | ---: |
| Source gap beyond limit | 300 | 224 | 0 |
| Sample before reference horizon | 300 | 224 | 0 |
| Complete authored interval | 300 | 120 | 0 |
| Time-varying band departure | 300 | 224 | 0 |
| Total | 1,200 | 792 | 0 |

A separate 400 ordinary captures retain identical complete review objects after
removing only the new exact-decimal metadata. All 1,600 input hash pairs match
between runs; strict JSON round trips and unchanged inputs pass. Campaign runtime
is recorded as observational evidence, not a performance comparison: filesystem
cache and concurrent work were not controlled.

37 new parameterized regression cases cover the timing outcomes, exact endpoint
provenance, negative/large origins, inactive prefixes, immutable inputs, JSON
round trips and low-precision ambient decimal context. Existing tests are retained.
All fixtures are authored software cases; none supplies physical normal bounds.

Native stress/full-suite results and exact executable/log hashes are in
docs/evidence/precharge_csv_clock_validation_20261017.json.
Hosted CI belongs to the eventual exact saved head and is recorded in the draft PR.

## Additional source qualification

[Zenodo 4431657](https://zenodo.org/records/4431657) was checked beyond its title:
the 25,877-byte EVCharhger_Lab_Info_V2.docx was downloaded and its published MD5
verified (abbcba061358db0d05d5de5b6abc4edf). SHA-256:
37311a820c78762144972e003f14dac69b5e75099d9f1fdfeaac4d4805aa9b39.
The producer information sheet describes a single column of AC voltage,
two seconds at 1 MHz, from an EV charger laboratory power source. It does not
supply the internal precharge signal set or independent normal bounds.
The 37 MB CSV was not downloaded because this channel description already
excludes it from the required input contract.

The [OSF 94gkc](https://osf.io/94gkc/) candidate associated with
[the power-quality dataset paper](https://doi.org/10.1038/s41597-026-06768-5)
remains unqualified. Both direct public node/file API requests returned HTTP 503.
A 3,038-byte publisher response is not accepted as the full paper or data schema.
Access failure is not evidence that a required channel is absent. No data package
was downloaded or passed to the observer. Compact fetch facts are retained in
the validation evidence; third-party documents/raw data stay outside git.

## Scope

Steps 7 and 8 still need authenticated, aligned physical pack/source voltage,
DC-link voltage, measured relevant-path current, phase and acquisition context,
plus independently justified comparable normal bounds. Step 8 additionally needs
a separate qualified test capture. Step 9 remains deferred without a CAN adapter.

Only the three private Research observer modules and their tests/docs change.
Core decisions, schemas, thresholds, dependency/packaging contracts and licensing
are unchanged. Hardware behavior was not evaluated by this software campaign.
