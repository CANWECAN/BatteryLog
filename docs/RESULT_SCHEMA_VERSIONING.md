# Result schema versioning

BatteryLog has two independent versioned contracts:

- the YAML validation configuration schema
- the machine-readable analysis result schema

They do not need to use the same version number.

## Configuration schema

The YAML configuration schema remains at version 1:

```yaml
schema_version: 1
```

This version identifies the structure accepted by the validation-config parser.

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

The schema is strict and rejects unknown fields.

## Versioning policy from v2 onward

Package versions and result-schema versions are independent.

A package release may keep result schema version 2 when implementation changes do not alter the machine-readable contract.

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
