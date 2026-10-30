# Interpretation limits

The development-only `batterylog.interpretation.InterpretationReport` API keeps
the engineering status supplied by its caller separate from three physical
claims. It is an initial result contract, not a diagnostic algorithm or a new
CLI/report workflow. Existing result-v8/v9 schemas and engine behavior are
unchanged.

```python
from batterylog.interpretation import InterpretationReport

# result is an existing engineering result produced by BatteryLog.
limits = InterpretationReport(engineering_status=result["validation_status"])
payload = limits.to_dict()
```

## Current behavior

| Field/claim | Meaning |
| --- | --- |
| `engineering_status` | Exact caller-supplied `PASS`, `FAIL` or `NOT_EVALUATED`; no recomputation. |
| `diagnostic_claim` | Always `false`. |
| `CELL_SOC_IMBALANCE` | Physical SOC imbalance has not been estimated. |
| `PARALLEL_BRANCH_FAULT_LOCATION` | A faulty physical parallel branch has not been localized. |
| `SENSOR_VS_CELL_FAULT_ISOLATION` | Sensor and cell fault causes have not been distinguished. |

Each physical claim is `NOT_EVALUATED`, independently of engineering status.
Reasons are machine-readable and do not imply an inspection that was not run:

- `MEASUREMENT_CONTEXT_NOT_ASSESSED`: this API has not inspected topology,
  branch measurements, chemistry, SOC, acquisition or operating state. It does
  not assert that those data are absent from the original measurement source.
- `SOC_IMBALANCE_MODEL_NOT_AVAILABLE`: this API supplies no conversion from
  voltage spread to SOC imbalance.
- `BRANCH_LOCALIZATION_MODEL_NOT_AVAILABLE`: this API supplies no method that
  identifies a faulty physical parallel branch.
- `FAULT_ISOLATION_MODEL_NOT_AVAILABLE`: this API supplies no method that
  distinguishes sensor faults from battery faults.

The object is frozen. `to_dict()` returns a new JSON-compatible dictionary and
new nested lists on every call. It does not retain or modify the engineering
result. Engineering evidence must still be validated by its existing producer
and consumers. Passing a status string is not validation of a result, its
measurements, sensor accuracy or source identity.

This initial payload has no source, result or context hash. It must not be
published as a source-bound evidence report. A later opt-in workflow needs to
bind all three before generating per-file output. Ordinary analysis does not
automatically produce this payload.

## Requirements for context-aware extensions

Future extensions must retain the following separation:

| Observation | Context/interpretation restriction | Engineering outcome |
| --- | --- | --- |
| Configured cell-voltage spread limit exceeded | Chemistry, SOC and operating conditions do not yet justify an SOC-imbalance estimate. | Retain the threshold violation and its evidence. |
| Common terminal voltage and total pack current | Ideal parallel branches can be observationally indistinguishable under permutations of physical cell identities. | Pack-level checks can still run; do not name a faulty branch. |
| Branch-current channels and topology declared | Channel presence alone does not establish validity, alignment, identifiability or a validated localization method. | No automatic promotion to a physical diagnostic claim. |
| Temperature/voltage anomaly observed | A sensor problem and a battery problem may remain indistinguishable without further evidence and a suitable method. | Retain the observation without assigning a cause. |
| No configured limit exceeded | This establishes only the scope of the configured engineering checks. | Do not convert PASS to proof of battery health or a negative physical diagnosis. |
| Insufficient context for a physical claim | The context deficiency applies to that claim. | Never replace or suppress an existing engineering FAIL. |

Topology and channel identities must be explicit. A channel named `cell_7_v`
does not establish a physical cell position or a parallel-branch identity.
Declared metadata and verified measurement properties need separate evidence.
Chemistry/SOC alone are not sufficient for an SOC estimate; branch currents
alone are not sufficient for localization. Contact resistance is not an
implemented identification method.

Strict [declared context parsing](MEASUREMENT_CONTEXT.md) is now available as a
separate development API. It does not run per-claim prerequisite checks or
change this report. Source/context binding, CLI, HTML and independently labeled
field-data evaluation are subsequent work.
The separate [parallel-branch declaration review](PARALLEL_BRANCH_CONTEXT.md)
now reports instrumentation inventory and context limits; it does not change
the three statuses in this result contract.
The separate [voltage-spread context review](VOLTAGE_SPREAD_CONTEXT.md) now
explains missing chemistry, SOC provenance, operating and acquisition context
without converting voltage spread to physical SOC imbalance.
No physical accuracy, field utility or safety qualification follows from the
software tests for this initial contract.
