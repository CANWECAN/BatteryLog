# Parallel-branch context review

`batterylog.parallel_context.ParallelBranchAssessment` reviews the existing
immutable measurement-context declaration. It reports branch instrumentation
and missing/qualified declarations. It does not read measurement samples,
identify a faulty branch or certify sufficient observability.

```python
from batterylog.measurement_context import load_measurement_context
from batterylog.parallel_context import ParallelBranchAssessment

context = load_measurement_context("context.json")
review = ParallelBranchAssessment(context).to_dict()
assert review["status"] == "NOT_EVALUATED"
assert review["diagnostic_claim"] is False
```

No context is also supported: `ParallelBranchAssessment().to_dict()` explicitly
reports `MEASUREMENT_CONTEXT_NOT_SUPPLIED`. Unvalidated dictionaries or other
objects are rejected; parse them through the measurement-context loader first.

## Outcome and scope

The version-1 payload has scope `declared_measurement_context_only` and claim
`PARALLEL_BRANCH_FAULT_LOCATION`. Its physical status is always `NOT_EVALUATED`.
Branch inventory, measurement properties and localization-method availability
are never marked verified/available by this review. These fields describe what
this review establishes, not whether another system has such evidence.

Each declared branch lists current, branch-terminal-voltage and cell-voltage
source names separately. Cell-voltage channels are not silently substituted
for branch-terminal voltage. Partial branch inventories remain unverified.
Source names are never interpreted as physical branch assignments.

Missing current and voltage entries are **inventory notes**, not a universal
instrumentation requirement. This API does not assert that both are necessary,
that either one is sufficient, or that a complete declaration supports diagnosis.
A suitable method and verified measurement evidence are still absent.

## Structured reasons

Every issue includes `code`, `field`, optional `branch_id`/`source`, and a short
description. `reason_codes` is the sorted unique set of issue codes.

| Reason | Meaning in this review |
| --- | --- |
| `MEASUREMENT_CONTEXT_NOT_SUPPLIED` | No context object was supplied. |
| `PARALLEL_TOPOLOGY_NOT_DECLARED` | Topology is absent or explicitly unknown. |
| `NON_PARALLEL_TOPOLOGY_DECLARED` | Declared series topology is outside this parallel review; no parallel counterexample is applied. |
| `BRANCH_IDENTITIES_NOT_DECLARED` | No explicit parallel-branch labels are supplied. |
| `ELECTRICAL_CHANNELS_NOT_DECLARED` | No electrical source channels are declared. |
| `BRANCH_ASSIGNMENT_NOT_DECLARED` | A branch/cell electrical source lacks an explicit branch assignment. |
| `BRANCH_CURRENT_NOT_DECLARED` | A declared branch has no assigned current source. |
| `BRANCH_TERMINAL_VOLTAGE_NOT_DECLARED` | A declared branch has no assigned terminal-voltage source. |
| `CHANNEL_UNIT_NOT_DECLARED` | A source unit is missing. |
| `CHANNEL_TIME_BASIS_NOT_DECLARED` | A time-basis label is missing. |
| `CHANNEL_ACQUISITION_NOT_DECLARED` | Acquisition mode is absent or unknown. |
| `ASYNCHRONOUS_ACQUISITION_DECLARED` | Asynchronous acquisition is declared; no alignment was verified. |
| `PREVIOUS_SAMPLE_HOLD_DECLARED` | Holding is declared; held rows do not establish new acquisitions. |
| `MULTIPLE_TIME_BASES_DECLARED` | Multiple electrical-channel clock labels exist; no clock relationship was verified. |
| `COMMON_TERMINAL_DATA_PERMUTATION_AMBIGUITY` | Only common pack electrical signals are declared for a parallel topology, with no branch-linked source. Under ideal parallel assumptions, branch identities can be permuted without changing common voltage/total current. |
| `BRANCH_INVENTORY_NOT_VERIFIED` | Declared labels do not establish physical inventory completeness. |
| `MEASUREMENT_PROPERTIES_NOT_VERIFIED` | This declaration review did not verify source existence or physical measurement properties. |
| `BRANCH_LOCALIZATION_MODEL_NOT_AVAILABLE` | This API implements no validated branch-localization method. |

The common-terminal reason is a conditional ambiguity/counterexample. It does
not prove that real contact resistances are zero or that a particular physical
system is unidentifiable under every possible model. Contact-resistance-based
identification is not implemented. Matching clock labels or a declaration of
simultaneous acquisition do not remove the verification limits.

## Preservation and reproducibility

The assessment and its context are immutable. Every export contains fresh nested
lists/dictionaries. Branches, channel lists, clocks and issues have deterministic
ordering. Reordering declarations does not change the payload; renaming physical
branch labels consistently moves the same inventory/gaps without selecting a
faulty branch.

No engineering result is accepted or modified by this API. Existing threshold
violations and pack-level checks retain their original behavior, independently
of this physical `NOT_EVALUATED`. The sum/permutation regression is a logical
counterexample, not a calibrated battery model or physical validation campaign.

The standalone review does not alter InterpretationReport and has no
source/context hash binding. The separate opt-in
[review workflow](INTERPRETATION_REVIEW.md) now includes this payload in its
source-bound JSON/HTML; this standalone payload must not be presented as
source-bound evidence. See [context declarations](MEASUREMENT_CONTEXT.md) and the
[interpretation contract](INTERPRETATION_CONTRACT.md).
