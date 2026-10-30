# Voltage-spread context review

`batterylog.voltage_context.VoltageSpreadAssessment` reviews the immutable
measurement-context declaration for the physical claim `CELL_SOC_IMBALANCE`.
It describes missing or qualified context. It does not read samples, compute
voltage spread, estimate SOC differences or assign a physical fault cause.

```python
from batterylog.measurement_context import load_measurement_context
from batterylog.voltage_context import VoltageSpreadAssessment

context = load_measurement_context("context.json")
review = VoltageSpreadAssessment(context).to_dict()
assert review["status"] == "NOT_EVALUATED"
assert review["diagnostic_claim"] is False
```

Omitting context reports `MEASUREMENT_CONTEXT_NOT_SUPPLIED`. Dictionaries must
first pass the strict measurement-context parser. The version-1 output has
scope `declared_measurement_context_only`. It must not be presented as a review
of a particular recording: source/result/context hash binding is subsequent work.

## Observation and interpretation

Existing result fields `max_delta_v`, `limits_applied.imbalance_max_v` and
`CELL_IMBALANCE_HIGH` describe the configured engineering voltage-spread check.
The existing violation code is preserved for compatibility. Its name does not
establish physical SOC imbalance, a particular faulty cell or sensor accuracy.

| Existing engineering observation | Independent physical review |
| --- | --- |
| 0.20 V peak spread exceeds a configured 0.05 V limit | Retain `FAIL` and the complete original violation. SOC imbalance remains `NOT_EVALUATED`. |
| The same recording is accompanied by LFP, SOC and rest declarations | Retain the same engineering result. These labels do not supply an implemented voltage-to-SOC model or verified equilibrium. |
| The configured spread limit is not exceeded | Retain the engineering `PASS`. Do not turn it into evidence of equal physical SOC or battery health. |
| No engineering limits are configured | Retain the engineering `NOT_EVALUATED`; this context review does not enable a limit or a physical estimate. |

No engineering result is accepted or modified by this API. Combining these two
outputs with traceable source identities belongs to the later opt-in workflow.
This API introduces no chemistry-specific thresholds, OCV curve, universal
mV-to-SOC conversion or SOC/SOH estimator. Even complete metadata leaves the
physical claim unevaluated.

## Declarations and limits

The export echoes chemistry, SOC value/source and operating state exactly as
declared. SOC zero is a supplied value. Chemistry and SOC-source labels are
opaque text: spelling, a familiar chemistry name or the label `unknown` selects
no electrochemical model and establishes no source validity. An absent label
is reported as missing. Operating state has the parser's explicit `unknown`
enum, which is reported as unspecified.

Only explicitly declared `cell_voltage` channels are inventoried. Pack and
branch terminal-voltage channels are not substituted for them. Each inventory
entry retains source name, source unit, physical cell/branch labels, time basis
and acquisition mode without conversion. The source name supplies no missing
identity. A missing declaration is not proof that a channel or fact is absent
from the recording.

Issues concerning acquisition apply to these cell-voltage declarations only.
Current/temperature signals are not verified here. An operating-state label
is not segmented against current samples or applied to particular intervals.
Partial cell inventories and cross-branch comparison groups remain unverified.
Matching clocks and `simultaneous` declarations do not certify synchronization,
freshness or calibration. Held rows are not treated as new acquisitions.

Every issue includes `code`, `field`, optional `source`, and an explanation.
`reason_codes` is the sorted unique set of issue codes.

| Reason | Meaning in this review |
| --- | --- |
| `MEASUREMENT_CONTEXT_NOT_SUPPLIED` | No context object was supplied. |
| `CHEMISTRY_NOT_DECLARED` | No chemistry label was supplied. |
| `SOC_VALUE_NOT_DECLARED` | No numeric SOC context was supplied. |
| `SOC_SOURCE_NOT_DECLARED` | No source for the SOC context was supplied; a numeric value alone is unsourced. |
| `OPERATING_STATE_NOT_DECLARED` | Load/rest conditions are absent or explicitly unknown. |
| `UNDER_LOAD_OPERATION_DECLARED` | Charge, discharge or mixed operation was declared; the review does not separate load response from SOC differences. |
| `REST_EQUILIBRATION_NOT_VERIFIED` | A rest label does not establish relaxation duration, equilibrium or OCV measurements. |
| `CELL_VOLTAGE_CHANNELS_NOT_DECLARED` | No cell-voltage sources are declared in this context. |
| `CELL_IDENTITY_NOT_DECLARED` | A cell-voltage source has no explicit physical cell label. |
| `CHANNEL_UNIT_NOT_DECLARED` | A cell-voltage source has no declared unit. |
| `CHANNEL_TIME_BASIS_NOT_DECLARED` | A cell-voltage source has no declared clock label. |
| `CHANNEL_ACQUISITION_NOT_DECLARED` | A cell-voltage acquisition mode is absent or unknown. |
| `ASYNCHRONOUS_ACQUISITION_DECLARED` | Asynchronous cell acquisition was declared; alignment is unverified. |
| `PREVIOUS_SAMPLE_HOLD_DECLARED` | Holding was declared; repeated rows do not establish new acquisitions. |
| `MULTIPLE_TIME_BASES_DECLARED` | Multiple cell-voltage clocks were declared; their relationships are unverified. |
| `CELL_INVENTORY_NOT_VERIFIED` | Labels do not establish a complete inventory or valid comparison group. |
| `OPERATING_CONTEXT_NOT_VERIFIED` | Chemistry, SOC provenance and operating conditions have not been verified against the recording. |
| `MEASUREMENT_PROPERTIES_NOT_VERIFIED` | Source existence, units, calibration, freshness and alignment have not been verified. |
| `SOC_IMBALANCE_MODEL_NOT_AVAILABLE` | This review implements no validated SOC-imbalance method or voltage-to-SOC conversion. |

The last four reasons are always retained. They describe what this review has
not established, rather than asserting that no external method or evidence can
exist. Missing declarations are descriptive limits, not a universally necessary
or sufficient instrumentation/model checklist.

The assessment and its context are frozen. Exports are detached JSON-compatible
copies, with deterministic source, clock and issue ordering. Reordering
declarations leaves the entire export unchanged. No numeric SOC difference,
faulty-cell selection or confidence score is produced.

This separate development API does not change `InterpretationReport`, the
analysis engine, result-v8/v9 schemas, CLI or HTML. See the [interpretation
contract](INTERPRETATION_CONTRACT.md), [context parser](MEASUREMENT_CONTEXT.md)
and [parallel-branch review](PARALLEL_BRANCH_CONTEXT.md). Its software regressions
are not physical-diagnosis validation or a safety qualification.
