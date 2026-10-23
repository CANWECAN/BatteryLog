# First real CAN-to-BatteryLog bridge — 2026-10-13

Baseline: `61359ea7d71713612c7f6e8d7c60ce252e6bf830`.
Private branch: `audit/cloud-balancing-spread-20261012`.

## Delivered scope

The Research checkout now has a runnable **classic CAN candump + DBC preparation
command**, an explicit three-brick Model 3 profile, and a reproducible cloud
verification campaign. The resulting canonical CSV is consumed by the existing
native CSV loader and analysis engine. No public API, GUI, production dependency,
result schema, engineering rule or release was changed.

This is a file-based integration proof. The first real recording contains
**118,053 frames over 301.621602 recorded seconds**, but the selected same-frame
brick group occurs only **six times**. These counts must not be confused: there
are six prepared measurement rows, not 118,053 complete battery snapshots.

Accepted transport syntax is compact candump data: `(timestamp) bus ID#HEX`,
with three hexadecimal ID digits for standard frames and eight for extended
frames, and at most eight data bytes. CAN FD, remote/error frames, comments and
other text log layouts are rejected rather than guessed or silently skipped.

## Sources and byte identity

| Input | Pinned source | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Model 3 battery CAN recording | [`dalathegreat/EV-CANlogs`, commit `9cbfc24528d9dfb2923c532f987ce1f3c278908f`](https://github.com/dalathegreat/EV-CANlogs/blob/9cbfc24528d9dfb2923c532f987ce1f3c278908f/Tesla/Model%203/tesla-model3-battery-only.log.log) | 5,323,360 | `709dd42efa4c43cc97cfc5cd05a488641b22949c9db3697c11c4b0cd588c36b4` |
| Community Model 3 DBC | [`joshwardell/model3dbc`, commit `c56c113c353d09b1a5dd57677461f02fe8b7c6ca`](https://github.com/joshwardell/model3dbc/blob/c56c113c353d09b1a5dd57677461f02fe8b7c6ca/Model3CAN.dbc) | 322,430 | `d54df533fc82f3dab11ddd0f5ae4d846f22c0a24b111d8cba2b93e79caf60151` |

Downloads matched the GitHub tree's blob SHA-1 values:
`30dc20c125a60ce5615b55238eb8fbb9008f4f7a` and
`2e030e798dc32b076794e2f57e36d620e3d4775a`, respectively. Source files and DBC
were not committed. The log repository declares GPL-3.0; the DBC is MIT,
copyright 2019 Josh Wardell. DBC attribution is retained under
`batterylog_research/third_party_model3dbc_NOTICE.txt`.

The source labels this as a Model 3 battery recording. Exact vehicle firmware,
hardware calibration and the DBC's compatibility with that firmware are not
independently established. Two decoders agreeing on a DBC is mathematical evidence,
not authentication of its physical meaning.

## Explicit measurement selection and alignment

| Canonical channel | DBC signal | Frame | Association |
| --- | --- | --- | --- |
| `cell_25_v` | `Brick24` | 0x401, selector 8 | Same anchor frame, V |
| `cell_26_v` | `Brick25` | 0x401, selector 8 | Same anchor frame, V |
| `cell_27_v` | `Brick26` | 0x401, selector 8 | Same anchor frame, V |
| `temp_1_c` | `BattBrickTempMax332` | 0x332, selector 0 | Previous reported pack/brick maximum, C; age <=2.1 s |
| `temp_2_c` | `BattBrickTempMin332` | 0x332, selector 0 | Previous reported pack/brick minimum, C; age <=2.1 s |
| `pack_current_a` | `SmoothBattCurrent132` | 0x132 | Previous frame, A; age <=0.05 s |
| `pack_voltage_v` | `BattVoltage132` | 0x132 | Previous frame, V; age <=0.05 s |

Brick channels represent series voltage groups, not separately measured individual
parallel cells. Canonical indices preserve the DBC label plus one; they do not
establish physical cell positions. The two temperature fields are **aggregate BMS
extrema**, not two fixed local sensors. They are not appropriate input for a local
temperature-rise diagnosis.

The age limits are declared research association bounds, not manufacturer limits.
All cell voltages must come from the same anchor frame. Other selected signals may
use only an earlier record within the explicitly declared bound. This is a separate
source preparation operation, **not hidden filling inside a MeasurementLoader**.
The maximum accepted logged-frame age in this source was **0.010064 s** for
pack voltage/current and **0.938039 s** for temperature. These are differences of
recorded CAN timestamps, not proof of physical sensor acquisition age.

`alignment.jsonl` stores each anchor's raw source line and recorded timestamp plus
each selected measurement's source line, timestamp, age and usable/missing state.
Missing or expired values stay blank in the CSV. Source chronology, duplicate
anchors and source order are preserved; future messages are never used to repair
earlier anchors. Input timestamps are subtracted as Decimal values before export
to float seconds, retaining the original nanosecond-resolution ordering checks.

The complete transport record is inspected. Unselected identifiers, multiplex
groups and other buses are explicitly counted rather than treated as complete
battery rows. Application checksums/counters and the meaning of `StatusFlags`
are not inferred. The DBC has definitions extending beyond the observed usable
brick groups: 20 source frames at selectors 32–35 have zero status and zero brick
values. These are not turned into 12 additional physical cell channels. We also
do not assemble a time-spanning sweep into a claimed synchronous complete pack.

## Native engine result

Preparation retained all six selected anchor frames. The first precedes the first
selected temperature report, so both temperature fields are missing.

- **Strict mode rejects** that first row consistently at CSV chunk sizes 1, 7 and
  65,536, with the same missing-temperature error and row evidence.
- Explicit `exclude_invalid_rows` mode analyzes **5 of 6 rows**, records one
  excluded row and two missing temperature values, and returns **FAIL because of
  the input data-quality defect**. There are **zero engineering violation events**.
- The illustrative active profile is 2.5–4.2 V, spread <=0.1 V and temperature
  <=55 C. This small partial selection does not establish full battery health.
- Accepted-row extrema: brick voltage **3.5088–3.5118 V**, maximum within-frame
  selected-brick spread **0.0009 V**, reported temperature extrema **7.5–9.5 C**,
  recorded smooth current **4.2–4.5 A**, pack voltage **336.69–336.93 V**.

No pack/cell-sum rule is enabled for this incomplete three-brick selection.
The existing result still contains a pack/sum diagnostic peak even with that rule
disabled; its approximately 326 V difference is expected for a partial selection
and **must not be interpreted as a physical mismatch fault**. Current direction
is not authenticated, so charge/discharge rules are disabled. Temporal failure
models are not enabled on these aggregate/asynchronous channels.

Full-frame and native CSV-stream results match **exactly** at all three chunk
sizes, including row accounting, extrema, quality events and statuses. The result
passes **result-v8 Schema and semantic validation**. Serialized analysis SHA-256:

`b701f75d100f3fac58ec094e0a639ec8601c9b4eaed97e3679c03b32c9892e38`

## Independent and hostile checks

1. All **118,053 raw frames** matched `python-can`'s independent candump reader
   on identifier, standard/extended type, payload and floating representation of
   the recorded timestamp.
2. `cantools` and `canmatrix` independently decoded **30,632 frames** at 0x132,
   0x332 and 0x401. Signal-name sets matched; **123,312 signal values** agreed
   under predeclared absolute tolerance 1e-12 and zero relative tolerance.
   Maximum observed difference was **9.103828801926284e-14**. The tolerance
   addresses binary64 arithmetic, not sensor calibration uncertainty.
3. Direct little-endian byte extraction independently reconstructed all **48
   canonical entries** (6 rows x 8 columns, including missing values). It did
   not use either DBC decoder. Those field formulas are specific to this pinned
   DBC and do not independently verify the manufacturer's encoding.
4. A separate mutation at source line **65,536** moved time backward. Preparation
   rejected it at that exact source line; it did not reorder or unwrap time.
5. A selected payload truncated at source line **149** failed with byte-length
   and line evidence. No partial successful output was published.
6. Removing all **151 selected temperature messages** in a separate synthetic
   mutation retained six anchor rows with missing temperatures. The engine
   analyzed zero rows, excluded six and returned FAIL; it did not fabricate data.
7. A byte-different DBC was rejected against the profile's pinned SHA-256 before
   decoding. This guards unintended DBC versions, not an incorrectly authored
   profile which deliberately selects an inappropriate DBC.

The 32 authored unit/contract tests additionally cover exact expiry at a one-second
boundary followed by one nanosecond, duplicate timestamp ordering, no look-ahead,
bus separation, standard/extended ID collision, multiplex separation, malformed
frames, incompatible units/profiles and failed-output cleanup. An initial test
assertion was corrected to use the already declared binary64 comparison tolerance;
decoded values were not rounded or changed to make it pass.

## Reproduce from a Research checkout

Install the isolated research dependencies, obtain the pinned sources above and
use a **new** destination directory:

```bash
python -m pip install -r batterylog_research/requirements-can.txt
python -m batterylog_research.can_prepare \
  model3-battery.log Model3CAN.dbc \
  batterylog_research/can_model3_profile.json prepared-can
python -m batterylog_research.can_cloud_validation \
  model3-battery.log Model3CAN.dbc \
  batterylog_research/can_model3_profile.json can-validation
```

Verified backend versions: cantools 44.2.1, canmatrix 1.2, python-can 4.6.1,
pandas 2.2.3 and NumPy 2.3.5. `cantools` supports DBC multiplexing and strict
message-length decoding; its
[official documentation](https://cantools.readthedocs.io/en/latest/) was consulted.
No new backend was added to the Core package's dependency list.

The preparation command stages outputs and publishes its directory only after a
complete successful parse and before/after source/DBC/profile hash checks.
It produces `canonical.csv`, `alignment.jsonl` and `preparation.json`.
The verification command additionally creates `analysis.json` and `summary.json`.
Aggregate evidence is committed as
`batterylog_research/can_cloud_summary_20261013.json`. Test-suite and formatting
results are recorded in `CURRENT_STATE.md`: **2,263 passed / 46 skipped** in the
complete cloud suite, including all 32 new CAN tests. The skips remain 44
GUI/display-dependent cases and two actual-MF4 cases with unavailable optional
backends. Nine NumPy overflow warnings came from existing adversarial arithmetic
probes. Whole-tree Ruff checks and formatting passed.

## Next gates

The first offline bridge and basic malformed/missing-input checks are complete.
Broader BMS recordings and verified per-channel semantics should expand the
selection before interpreting full-pack behavior. Full-stack multiplex alignment,
application counter/checksum validation, CAN FD/ISO-TP and other log formats
require their own source-specific validation; none is silently inferred here.

Live adapter capture, disconnect/reconnect, sustained recording and native
driver behavior were not verified by this file-based campaign.
