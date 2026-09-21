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

Result schema version 4 is the current BatteryLog machine-readable result contract for the 0.9 development line. Its Draft 2020-12 JSON Schema is:

```text
batterylog/schema/result-v4.json
```

Version 4 adds optional pack-level electrical measurement evidence:

- `signal_mapping.pack_current_source`
- `signal_mapping.pack_voltage_source`
- `max_pack_current_a` and `min_pack_current_a`
- `max_pack_voltage_v` and `min_pack_voltage_v`

Canonical provenance uses the exact names `pack_current_a` and `pack_voltage_v`; absent signals use `null`. Explicit provenance records the configured vendor source name. A selected signal has numeric extrema whenever at least one row was analyzed, while absent signals and all-excluded inputs use `null`.

The v2 and v3 artifacts remain frozen and packaged for existing consumers.

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
