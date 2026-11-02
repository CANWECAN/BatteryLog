# Declared measurement context

The development API in `batterylog.measurement_context` reads a small, strict
JSON declaration. Parsing validates its structure and internal references. It
does not verify the physical measurements or run an interpretation policy.
Existing analysis, configuration and result-v8/v9 contracts are unchanged.

```python
from batterylog.measurement_context import load_measurement_context

context = load_measurement_context("context.json")
assert context.evidence_level == "DECLARED"
assert context.measurement_properties_verified is False
```

`load_measurement_context_bytes(data)` accepts UTF-8 JSON bytes, with an optional
BOM. The file loader reads at most 1 MiB plus one byte to detect oversize input.
Both loaders apply the packaged `schema/measurement-context-v1.json` and the
cross-field checks below. Direct `MeasurementContext` construction applies the
same checks; subvalue dataclasses are validated when assembled into the context.

## Minimum declaration and missing information

```json
{"measurement_context_schema_version": 1}
```

Only the exact integer version is mandatory. Missing topology, chemistry, SOC,
operating state, channel units and physical identities remain unknown. Empty
channel/branch lists are not evidence of a complete selection. No names, units,
SOC values, topology or physical cell positions are inferred from source names.

| Field | Declaration | Restriction |
| --- | --- | --- |
| `topology.kind` | `unknown`, `series`, `parallel`, `series_parallel` | A declared kind is not a verified electrical graph. |
| `topology.branch_ids` | Unique explicit parallel-branch labels | Partial inventories are permitted; `series` cannot declare parallel branches. |
| `channels[].source` | Exact source-column/channel name | One source can supply only one declared role. |
| `channels[].role` | Cell/branch/pack voltage, branch/pack current, temperature | No signal decoding or measurement preparation is performed. |
| `channels[].unit` | Optional unit appropriate to the role | V/mV for voltage, A/mA for current, degC/K for temperature; preserved without conversion. |
| `channels[].branch_id` | Optional reference to a declared branch label | Unknown references are rejected; pack signals cannot be assigned to one branch. |
| `channels[].cell_id` | Optional physical label for cell voltage or temperature | Labels are explicit declarations, not positions derived from numeric channel names. |
| `channels[].time_basis` | Optional source clock/time-basis label | Matching labels do not establish physical simultaneous acquisition or latency. |
| `channels[].acquisition` | `unknown`, `simultaneous`, `asynchronous`, `previous_sample_hold` | All modes are unverified declarations. Held rows are not new acquisitions. |
| `chemistry` | Optional explicit label | No electrochemical parameters or limits are selected automatically. |
| `soc.value_percent` | Optional finite number in [0, 100] | No conversion from fractions/strings or estimation; zero is a valid supplied value. |
| `soc.source` | Optional description of the SOC source | A value without a known source stays explicitly unsourced. |
| `operating_state` | `unknown`, `rest`, `charge`, `discharge`, `mixed` | A rest declaration does not prove equilibration or segment the recording. |

Mappings must be unambiguous: repeated source names, two channels for the same
declared branch-current/branch-voltage role, or two channels for the same
declared `(role, branch_id, cell_id)` are rejected. Redundant sensors require an
explicit selection before this narrow contract is used. Missing identities are
permitted; they are not filled from the other channels.

## Strict parsing and immutable values

Unknown fields, duplicate JSON keys (including identical repeated values),
unsupported versions, non-finite numbers, boolean/string SOC values, control
characters and invalid Unicode labels are rejected. `1.0`, `true` and `"1"`
are not accepted as schema versions. Channel and branch arrays are bounded at
4096 entries; nesting is bounded at 16 levels. JSON Schema describes structural
constraints; exact version typing, finite values, unit/role compatibility and
reference uniqueness also require the Python checks.

`MeasurementContext` and its subvalues are frozen, with tuple collections.
`to_dict()` returns a detached JSON-compatible copy containing declarations
only. Verification attributes are derived and cannot be set through the JSON
or constructor. There is no user-controlled `verified` or confidence field.

The authored [example](../examples/measurement_context.json) illustrates these
fields. It is not bound to a measurement file or a physical reference test.
Its held-sample declarations and common clock label do not establish alignment.

## Current boundaries

Loading context does not check whether named channels exist in a recording,
whether samples are fresh/aligned, or whether topology and branch currents are
sufficient for identification. No unit conversion, state segmentation, SOC
estimate, physical diagnosis or safety decision is performed. Context/source
hash binding and snapshot handling are available in the separate opt-in
[review workflow](INTERPRETATION_REVIEW.md).

The separate [parallel-branch context review](PARALLEL_BRANCH_CONTEXT.md) can
inventory these declarations and report missing fields. It does not verify
source samples or physical identifiability.
The separate [voltage-spread context review](VOLTAGE_SPREAD_CONTEXT.md) reports
chemistry, SOC-source, load/rest and cell-acquisition limits. Neither review
changes the parser's declarations into verified measurements or a physical
diagnosis.

The [interpretation result contract](INTERPRETATION_CONTRACT.md) still returns
`NOT_EVALUATED` for physical claims. This parser does not change a measured
engineering PASS or FAIL. The opt-in review CLI accepts this context and shows
its declaration limits in a separate HTML/JSON bundle.
