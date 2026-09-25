# Result schema versioning

BatteryLog has two independent versioned contracts:

- the YAML validation configuration schema
- the machine-readable analysis result schema

They do not need to use the same version number.

## Configuration schema

The current YAML configuration schema is version 3:

```yaml
schema_version: 3
```

Configuration schema 2 adds the optional `data_quality` block and its explicit `strict` / `exclude_invalid_rows` mode. Configuration schema 3 adds optional scalar `signals.pack_current` and `signals.pack_voltage` source names. Configuration schemas 1 and 2 remain accepted with their historical behavior: schema 1 is strict fail-fast and rejects `data_quality`; schema 2 accepts `data_quality` but rejects the new pack-signal mapping keys.

This version identifies the structure accepted by the validation-config parser and is independent from the result-schema version.

## Result schema history

### Result schema version 1

`schema_version: 1` was introduced before BatteryLog had a formally frozen JSON Schema artifact.

During the 0.4.x through 0.6.x development line, the result payload evolved additively while continuing to report version 1. Examples include:

- 0.5.x added `analysis_options`
- 0.6.x added `signal_mapping`
- later 0.7 development added `comparison_policy`

For that reason, BatteryLog does not claim that one strict JSON Schema can describe every historical result that reports `schema_version: 1`.

A strict `result-v1.json` artifact was briefly introduced on the unreleased 0.7 development branch. The historical mismatch was identified before the 0.7.0 release, so that artifact was withdrawn and the first frozen contract was promoted to version 2 instead.

Result schema version 1 should be treated as a legacy, pre-formal marker.

### Result schema version 2

Result schema version 2 is the first formally frozen BatteryLog result contract.

Its Draft 2020-12 JSON Schema is:

```text
batterylog/schema/result-v2.json
```

The schema is strict and rejects unknown fields. The frozen v2 artifact remains packaged for consumers of the 0.7 contract.

### Result schema version 3

Result schema version 3 is the frozen BatteryLog machine-readable result contract for the 0.8 release line. Its Draft 2020-12 JSON Schema is:

```text
batterylog/schema/result-v3.json
```

Version 3 adds structured required-data quality evidence and explicit row accounting:

- `data_quality.mode`
- grouped `data_quality.events`
- `rows_input`
- `rows_excluded`
- `rows_analyzed` may be zero when every input row is excluded
- measured extrema may be `null` only when no rows were analyzed

The validation-status invariant also changes: `FAIL` may now be justified by one or more engineering-rule violations, one or more structured data-quality events, or both. `PASS` and `NOT_EVALUATED` cannot contain data-quality events. Non-empty data-quality evidence requires at least one excluded row, and zero analyzed rows cannot contain engineering-rule violations.

Draft 2020-12 validation does not establish every cross-field arithmetic relationship in the contract. BatteryLog's producer additionally guarantees `rows_input == rows_analyzed + rows_excluded`; each data-quality event satisfies `1 <= start_row <= end_row <= rows_input`; and `affected_values` equals the inclusive row span multiplied by the number of signals. Consumers that accept results from untrusted or independent producers should apply these semantic checks in addition to validating against the JSON Schema.

### Result schema version 4

Result schema version 4 introduced optional pack-level electrical measurement evidence for the 0.9 development line. Its frozen Draft 2020-12 JSON Schema is:

```text
batterylog/schema/result-v4.json
```

Version 4 adds:

- `signal_mapping.pack_current_source`
- `signal_mapping.pack_voltage_source`
- `max_pack_current_a` and `min_pack_current_a`
- `max_pack_voltage_v` and `min_pack_voltage_v`

Canonical provenance uses the exact names `pack_current_a` and `pack_voltage_v`; absent signals use `null`. Explicit provenance records the configured vendor source name. A selected signal has numeric extrema whenever at least one row was analyzed, while absent signals and all-excluded inputs use `null`.

### Result schema version 5

Result schema version 5 introduced explicit pack-current validation evidence for the 0.9 development line. Its frozen Draft 2020-12 JSON Schema is:

```text
batterylog/schema/result-v5.json
```

Version 5 adds explicit pack-current validation evidence:

- rule codes `PACK_CHARGE_OVERCURRENT` and `PACK_DISCHARGE_OVERCURRENT`
- applied limits `pack_charge_max_a` and `pack_discharge_max_a`
- applied polarity `pack_current_positive_direction`
- ampere violation evidence with the measured current sign preserved
- signed `limit_value` evidence derived from the configured non-negative magnitude and explicit positive-current direction

When either pack-current limit is active, `pack_current_positive_direction` is `charge` or `discharge`; it cannot be `null`. Runtime analysis also requires a selected `pack_current_a` signal when either overcurrent rule is active.

The v2, v3, v4, and v5 artifacts remain frozen and packaged for existing consumers.

### Result schema version 6

Result schema version 6 introduced explicit temperature-spread validation evidence for the 0.9 development line. Its frozen Draft 2020-12 JSON Schema is:

```text
batterylog/schema/result-v6.json
```

Version 6 adds explicit temperature-spread validation evidence:

- rule code `TEMPERATURE_SPREAD_HIGH`
- applied limit `temperature_spread_max_c`
- exact measured metric `max_temperature_spread_c`
- peak sensor evidence containing the hottest and coldest temperature signal(s)

Temperature spread is evaluated per analyzed row as maximum temperature minus minimum temperature. The configured limit and measured maximum are non-negative. The v2, v3, v4, v5, and v6 artifacts remain frozen and packaged for existing consumers.

### Result schema version 7

Result schema version 7 is the frozen BatteryLog machine-readable result contract for 0.9.0. Its Draft 2020-12 JSON Schema is:

```text
batterylog/schema/result-v7.json
```

Version 7 enriches every engineering violation event with:

- `sample_count`: number of violating analyzed samples represented by the event
- `duration_s`: elapsed timestamp span from event start to event end; single-sample events and duplicate timestamps may produce zero
- `peak_excursion`: non-negative absolute threshold distance at the event peak, in the event unit

These fields do not change any threshold, comparison, grouping, first-equal-peak tie-break, or validation-status semantics. Streaming event merges sum `sample_count`, recompute `duration_s` from the merged endpoints, and preserve the `peak_excursion` belonging to the selected worst peak.

### Result schema version 8

Result schema version 8 adds an opt-in pack-voltage versus cell-voltage-sum plausibility rule. The frozen v7 artifact remains packaged. Its Draft 2020-12 JSON Schema is:

```text
batterylog/schema/result-v8.json
```

Version 8 adds `PACK_VOLTAGE_CELL_SUM_MISMATCH`, the nullable `pack_voltage_cell_sum_peak` result with the source values and signed error at the earliest worst sample, and `limits_applied.pack_voltage_cell_sum_max_delta_v`. Mismatch events require their own pack measurement, cell sum and signed error at the event peak. A configured threshold requires a selected pack-voltage signal. The new rule uses the existing binary64 guard, contiguous-row grouping and optional event-gap splitting.

## Versioning policy from v2 onward

Package versions and result-schema versions are independent.

A package release may keep its current result-schema version when implementation changes do not alter the machine-readable contract.

A new result schema version is required when a release changes the wire contract, including:

- adding or removing a result field
- renaming a field
- changing a field type
- changing required/optional status
- changing an enum domain
- changing the documented meaning of a field
- changing nested object structure
- changing status invariants encoded by the schema

Internal implementation changes, performance improvements, bug fixes that preserve the result contract, and report-only presentation changes do not by themselves require a result schema bump.

## Compatibility

Consumers should branch on the result payload's `schema_version`.

Consumers that require the first strict, machine-verifiable contract should require result schema version 2 or later.

The YAML configuration `schema_version` is a separate namespace and must not be interpreted as the result schema version.
