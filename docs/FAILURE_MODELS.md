# Opt-in failure models (development branch)

These deterministic checks describe measured log behavior. They do not diagnose a
weak cell, a bad connection, a faulty sensor, or the cause of a balancing result.
No SOC estimator, energy estimator, calibration, internal resistance measurement,
expression language, or general state-machine framework is included.

The pack-versus-cell-sum check already ships in v0.10.0. Enable it with
`limits.pack_voltage.cell_sum_max_delta_v`; its event, signed error and measurement
chain are unchanged. It assumes all series cells and the pack measurement are
mapped correctly and synchronized. It cannot independently prove cell completeness.

## Try the five-model synthetic example

```bash
python -m batterylog examples/failure_models_demo.csv \
  --config examples/failure_models.example.yaml \
  --json-out result.json --report report.html
```

The expected result is FAIL, exit code 1. The example parameters are illustrative,
not safety recommendations. Choose thresholds, sampling bounds, and test durations
for the measured system. Omitted or null model groups are disabled. Every enabled
group requires all its parameters; unknown keys, booleans as numbers, non-finite
values, negative times, and contradictory parameters are rejected.

Configuration schema version 7 introduces `failure_models`. Versions 1–6 retain
their existing parsing behavior and reject this new key. Legacy-only analysis
continues to emit the frozen result-v8 payload, byte-for-byte against the golden
corpus. Opting into a new model emits result-v9, including parameters, individual
outcomes, observation counts, reasons, incomplete intervals, and events. Existing
`rules_evaluated` and `violations` describe the original limit rules; new model
events live under `failure_models.evaluations[].events`. Use both collections.

## Observation and continuity contract

`failure_models.max_gap_s` is mandatory and positive. It bounds every interval
used for continuity, derivatives, resting references and balancing sessions.
Invalid measurement rows and larger gaps reset the state; no interpolation or
zero-order hold across missing observations is performed. Duplicate timestamps
do not add elapsed time. Rates need a positive qualifying interval; a duplicate
replaces the preceding sample and breaks a rate event. All comparisons use the
existing binary64 relative guard (8 epsilon, absolute tolerance zero). Peaks use
unrounded values and the earliest equal peak, across arbitrary chunk boundaries.

Durations measure the time between qualifying observed samples. This is evidence
of sampled persistence, not proof of what happened between those samples.
The algorithm retains only the latest sample/reference/session and event output;
it does not retain an entire log or concatenate chunks.

| Model | Exact observation | Eligibility / outcome |
|---|---|---|
| `CELL_IMBALANCE_SUSTAINED` | Cell max minus min strictly exceeds `max_delta_v` at every sample in a contiguous run spanning at least `duration_s`. | A shorter high excursion produces no event. At least one contiguous valid span of `duration_s` is needed for PASS. Event includes the whole high run, its peak cells and required duration. |
| `TEMPERATURE_RISE_HIGH` | Adjacent-sample rise `(T_now - T_previous) / dt * 60`, compared with `max_c_per_min`. The highest rate across sensors drives each event. | `min_interval_s <= dt <= max_gap_s`. No eligible pair means NOT_EVALUATED. Cooling is not a violation. The peak chain identifies the first sensor in `signals` when tied. |
| `CELL_SAG_UNDER_LOAD` | Per-cell drop from a frozen resting reference, minus the median drop across cells; compare the largest excess with `excess_sag_max_v`. | At least 3 cells and pack current. Reference current magnitude at most `baseline_max_abs_current_a`; load discharge magnitude at least `load_min_discharge_a`. Reference must precede load onset and be no older than `baseline_max_age_s`. Evaluate after `settling_s`; hold the reference for that load episode. No qualified episode means NOT_EVALUATED. Unqualified load episodes also prevent PASS. |
| `BALANCING_INEFFECTIVE` | At the first still-active sample at or beyond `evaluation_s`, initial spread minus current spread must reach `min_improvement_v`. | Requires an observed inactive-to-active edge and initial spread at least `min_start_delta_v`. Evaluate once per episode; a shorter/interrupted eligible episode is incomplete. A spread already below the start bound is ineligible, not a failure. |
| `BALANCING_ACTIVE_TOO_LONG` | Observed active elapsed time strictly exceeds `timeout_s`. | Requires an observed activation edge. Emit once at the first crossing, preserving detection-time evidence, not a later session-end peak. A complete shorter session can pass. An unfinished session with no crossing is incomplete. |

Cell sag reports an observed excess drop, not internal resistance or a resistance
proxy. Uniform sag does not fail this relative check. It is not a replacement for
undervoltage validation. The sign convention is explicit in the sag configuration;
if a pack-current limit also specifies a convention, those conventions must agree.

Balancing needs the explicitly named `active_source`, as a separate source column
or MDF channel. Boolean values and numeric 0/1 are accepted; text `true`/`false`
and `0`/`1` represent those values in CSV. Other states are rejected in strict
mode. In `exclude_invalid_rows` mode, malformed balancing status interrupts only
balancing observation, increments incomplete intervals, and prevents its PASS.
It does not become a numeric required-measurement DQ event. A missing status
signal, a log starting active, or an unobserved activation produces NOT_EVALUATED;
balancing is never inferred from changing cell voltages. Cell-level flags and
multi-state balancing enums must be normalized to an explicit pack-level boolean
by the data producer, outside this first implementation.

CSV and MF4 share the collector. For MF4 the selected balancing channel must be
dimensionless, unique, and aligned with the measurement time. The loader preserves
invalidation and disabled interpolation. It does not forward-fill status across
asynchronous channel timestamps. Custom measurement loaders must include the
named source column themselves. Explicit sensor mapping does not discard status.

When these models are configured during unit normalization, the named balancing
status is retained as 0/1 under its original name with a dimensionless identity
conversion record. Normalization remains strict, preserves all rows, and performs
no engineering evaluation. Analyze the resulting canonical CSV without the original
sensor mapping; retain the failure-model parameters and balancing source name.

The two balancing checks are observations of active time and spread improvement,
not proof that balancing hardware is defective. Load, temperature and the chosen
test conditions can affect spread; interpret the evidence with the test procedure.

## Real-data characterization

See [the real-data model campaign](REAL_FAILURE_MODEL_VALIDATION.md) for source
eligibility, independent arithmetic checks, illustrative threshold sensitivity and
a reproducible technical demo. Real-data observation is separate from physical
fault diagnosis and threshold calibration.

## Overall status and evidence validation

Any original limit violation, required-measurement DQ defect, or model event yields
FAIL. Otherwise, any configured model with no eligible observations or incomplete
intervals yields NOT_EVALUATED, even if other rules passed. PASS requires all enabled
models to pass. Missing data never silently disables a requested model.

The HTML report shows individual model outcomes, their parameters and measurement
chains. The CLI, analysis service, batch workflow, Python frame/bytes/file APIs, and
report-series APIs pass the same effective configuration through to the collector.
No GUI change or existing desktop PR modification is included.

Validate strict JSON against `batterylog/schema/result-v9.json`, then call
`validate_result_semantics`. Structural validation checks required fields, status
shape, units, enabled codes and original limit-rule provenance. Semantic checks
also verify configuration relationships, code order/uniqueness, overall status,
event timing, threshold direction and arithmetic in the recorded chains. This
does not authenticate the source or prove the measured median/peaks are correct;
the original log and existing SHA-256 provenance remain necessary.
