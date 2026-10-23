# Failure targets and precharge observation contract

Private Research study, 14 October 2026. Based on `f8c274d3cb81c7950747891c1665068433d5645a`.
This is an observational engineering review, not failure prediction, component
diagnosis, a production validation rule, or a vehicle-control interface.

## Small failure-mode matrix

This is an FMEA starting table, not a completed safety FMEA. No occurrence,
severity, detectability score or RPN is assigned without system evidence.

| Failure hypothesis | Observable symptom | Required evidence / context | Competing explanation / attribution limit | Current or proposed work |
| --- | --- | --- | --- | --- |
| Open/high-resistance precharge path | DC-link voltage rises slowly or not at all; current differs from the specified response | Pack/DC-link voltages, relevant current, explicit phase; known load state and reference response | Different capacitance, initial bus voltage, other loads or sensor timing can resemble a path problem | Proposed declared-curve review; no cause identification |
| Downstream short/leakage during precharge | Voltage difference persists or current does not fall as expected | Same synchronized signals plus controlled downstream loads and topology | Intended auxiliary load or bad voltage/current measurement can look similar | Proposed declared-curve review; lab confirmation required |
| Contactor response inconsistent with command | Independent feedback disagrees; bus voltage does not follow the expected transition | Separate command/feedback, voltages on identified electrical nodes, timestamps | Feedback/sense fault, retained DC-link energy or another power source; no automatic welded-contact diagnosis | Existing command/feedback timing; voltage corroboration remains separate |
| Cell or connection resistance larger than peers | Load-relative measured cell voltage drop differs from peers | Controlled current step, branch current, identified voltage sense points, SOC/temperature/rest context | Cell polarization, wiring/sense placement, imbalance and asynchronous acquisition | Existing relative sag; cell vs connection separation needs additional measurements |
| Voltage/current sensing inconsistency | Pack/cell sum or known-state current differs from reference | Complete topology, alignment, independently established state or reference sensor | Omitted cells, sensor offset, ZOH and incorrect mapping can produce similar observations | Existing plausibility/unloaded checks and source triage |

Mattijs's reply identifies the full precharge current/voltage/time response as an
interesting extension beyond his BMS's existing limits/timing checks. It does
not confirm that these channels are exported independently or that an expected
response is already available. Do not infer a validated customer requirement,
fault dataset, logging format or successful hardware integration from the reply.

## Inputs and the declared reference

Review one captured activation per call. Input arrays retain the producer's row
order and aligned numeric samples:

- Finite numeric time in seconds on one producer-established time basis.
- Independent precharge-active 0/1 flag, with a preceding observed inactive sample.
- Measured pack voltage and DC-link voltage in V on identified electrical nodes.
- Current in A from the circuit intended by this procedure. Comparing magnitude
  does not establish current direction or isolate precharge from other loads.
- An explicit positive maximum observation gap selected for the acquisition.
- A caller-supplied envelope: rows of `(elapsed_s, min_abs_current_a,
  max_abs_current_a, min_voltage_gap_fraction, max_voltage_gap_fraction)`.
  Signed relative voltage gap is `(pack_v - dc_link_v) / pack_v`; pack voltage must
  be positive to define it. Elapsed time is relative to the **first observed active
  sample**, not a reconstructed physical switch instant.

Envelope times start at zero, strictly increase and have a finite positive final
horizon. Bounds are finite and ordered; current-magnitude bounds are nonnegative.
Voltage-gap bounds may be negative when the declared reference permits DC-link
overshoot. The sign is preserved so overshoot and undershoot are not conflated.
Linear interpolation is
allowed **only between declared reference bounds**; it never fills missing source
measurements. The operator must justify that reference and its tolerances for
the actual procedure. There is no universal precharge curve or automatic RC fit.

Initial DC-link voltage, pack voltage, connected capacitance/load state and sensor
latency/uncertainty must match the declared reference or be covered by its bands.
The observed activation bracket is timing evidence, not permission to compare a
narrow reference against an unknown physical switch instant.

The study returns independent facts: recorded deviations, reviewed sample count,
start bracket, last qualified elapsed time, source/episode incompleteness reasons
and whether the declared reference interval was covered. It does not emit Core
PASS/FAIL/NOT_EVALUATED or mutate result-v9. A deviation before an interruption
remains recorded; incomplete coverage cannot become a clean full-curve result.

## Qualification and coverage

- Source timing order and array shape are checked; strings, booleans used as
  measurements, complex values and non-finite timestamps are rejected.
- Original phase zero/one classification and original time ordering are checked
  before binary64 rounding can conceal unknown values or a descending timestamp.
  Calculations use binary64; collapsed ascending timestamps conservatively lose
  qualification. See the 14 October stress report for reproduced conversion bugs.
- Unknown phase, missing/non-finite active measurements, nonpositive pack voltage,
  duplicate time or a gap larger than the declared bound interrupt qualification.
  Later active samples cannot silently restore the lost episode.
- A capture beginning active has unknown activation timing. Its curve cannot be
  compared to the time-indexed reference until a separately observed activation.
- An observed early phase end or EOF before the reference horizon is incomplete.
  Source gaps are not bridged, nor are inactive samples used as active checkpoints.
- Qualified active samples at or bracketing the reference horizon complete
  **sampled interval coverage**. Only samples inside the reference interval are
  compared; a later endpoint is never extrapolated or substituted for a reading
  at the exact horizon. The actual horizon bracket is returned explicitly;
  this does not prove physical precharge completion, contactor closure, or behavior
  between samples. Behavior after the declared horizon is outside this study.
- Multiple observed activations must be reviewed separately; this first harness
  does not implement batch episode discovery or a general state-machine language.

## Controlled comparison plan

Compare the existing one-checkpoint current rule with this separate observer on:
normal declared response; slower but ultimately converging response; an early
current/voltage disturbance; interrupted phase; missing samples; left-censored
activation; and an implausible but finite voltage reading. These are generated
signals, not independently labeled physical faults.

The synthetic generator uses an ideal exponential response solely to supply
known test curves. Its RC-like shape does not validate a physical parameter fit
or make that response universal. Thresholds and bounds are illustrative.

Required checks: independent envelope arithmetic, exact boundary behavior,
continuity loss, retained earlier deviations, malformed references and immutable
inputs. Keep production code, schemas, license/dependencies and release unchanged.

## Source

[foxBMS precharging documentation](https://docs.foxbms.org/system/precharging.html)
describes decreasing current alongside decreasing battery/application voltage
difference, and the dependence on the resistor/load capacitance. This supports
reviewing both recorded signals, not uniquely attributing a component fault.

## Executed synthetic study

The reference is a generated ideal exponential response with a 1 s time constant,
400 V pack and 8 A initial current; reference knots are 0.25 s apart with +/-0.2 A
and +/-0.02 signed voltage-gap-fraction bands (the synthetic lower gap bound is
clipped to zero). Samples are 0.1 s apart; the observation-gap bound is 0.2 s.
All these choices are illustrative software settings. The generator supplies a
self-consistent synthetic 96S context solely for the required Core input fields.
Only the existing precharge-current model is configured in that comparison;
its PASS is not a full-pack safety/health result.

The legacy checkpoint is explicitly configured at 4 s with initial magnitude
at least 8 A and required current drop at least 6 A. The new observer does not
replace that rule or convert recorded curve deviations into a Core FAIL.

| Generated scenario | Existing current checkpoint | Declared interval covered | Outside-envelope samples |
| --- | --- | --- | ---: |
| Declared normal response | PASS | yes | 0 |
| Slower 2.5 s response, ultimately sufficient current drop | PASS | yes | 40 |
| Early current/voltage disturbance, recovered by the checkpoint | PASS | yes | 3 |
| Phase interrupted before the declared horizon | NOT_EVALUATED | no | 0 |
| Missing source interval during the phase | NOT_EVALUATED | no | 0 |
| Capture starts active | NOT_EVALUATED | no | 0 |
| One finite DC-link reading at 1200 V | PASS | yes | 1 |

These differences show additional sampled information available to a curve
review. They are not a measured physical-fault detection advantage: a changed
capacitance, initial voltage, load or reference could legitimately change the
response. No false-alarm or failure-prediction rate is inferred.

### Verification

- Final source-matched new-curve and existing-precharge subset: 95 passed,
  comprising 39 new tests and 56 existing tests.
- New tests include 80 independently computed reference-interpolation scenarios,
  signed overshoot/undershoot, unknown/missing observations, retained earlier
  deviations, bounded examples, source immutability, horizon bracketing, multiple
  activation rejection and finite-input arithmetic overflow.
- A broader model/oracle/temporal subset passed 224 tests with one existing
  overflow warning before the final synthetic-96S fixture cleanup. The final
  fixture is exercised by the source-matched 95-test subset above.
- Whole-tree Ruff check/format, mypy 1.19.1 over all 48 Core files and dependency
  consistency passed. Complete hosted Linux/Windows/MF4/package CI passed;
  physical commissioning data was not evaluated.
- One boundary defect was reproduced and fixed: a complete first interval could
  hide a second activation later in the supplied capture. The whole input now
  rejects multiple observed activations before returning a review.

```sh
python -m batterylog_research.precharge_curve_review --output /path/to/new-summary.json
python -m pytest -q tests/test_research_precharge_curve_review.py tests/test_precharge_current.py
```

The CLI generates only this study; it does not ingest arbitrary CAN/MF4 or vendor
CSV files. The Python observer accepts producer-aligned numeric arrays and a
declared envelope. The JSON includes the exact reference/settings and script
SHA-256; exclusive output creation preserves an existing file. Source arrays
are held in memory; no streaming resource guarantee is claimed.

Next physical gate: obtain exported phase/current/pack/DC-link channels, their
measurement locations and timing uncertainties, plus a justified test reference.
Before then keep this as an independent Research observation tool.

## Hosted closure

Draft [PR #4](https://github.com/CANWECAN/BatteryLog-Research/pull/4) is stacked on
the temperature/sag study branch. Source commit
`6c2bce5eda663ca22b10ee472686cb9bcecb7a35`, tree
`f1745c9f7b54c1545302ac356a606dfbb3bd8e86`, matches the locally tested source tree.
[Run 38525520486](https://github.com/CANWECAN/BatteryLog-Research/actions/runs/38525520486)
completed SUCCESS with all 12 jobs passing: Linux Python 3.11–3.14, minimum
runtime, Windows, five MF4 combinations and package verification.

Inspected Linux 3.12/3.13 jobs each report 2,558 passed, two skipped, nine warnings,
coverage 96.23%; minimum runtime has the same pass/skip counts and coverage with
ten warnings. Hosted Windows 3.13 reports 2,556 passed, four skipped, nine
warnings, coverage 96.21%. Both inspected Linux 3.12 and Windows MF4 jobs report
175 passed. The existing 95% coverage gate passed.

This closure edits documentation only; observer, generated results and test blobs
remain those of the specifically successful source commit. A closure-triggered
run is a separate record. Physical validation was not performed.
