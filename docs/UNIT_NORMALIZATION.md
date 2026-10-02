# Explicit unit normalization

Prepare one CSV/MDF/MF4 measurement in standard units, then analyze the result:

```sh
batterylog source.csv --normalize --time-unit ms --cell-voltage-unit mV \
  --temperature-unit K --output-dir prepared/run-001
batterylog prepared/run-001/normalized.csv --cell-max-v 4.2 --report report.html
```

Normalization creates `normalized.csv` and `conversion.json` in a new output
directory. It does not modify the source or evaluate engineering rules.
Successful preparation returns exit code `0`, even when later analysis will FAIL.
Errors return `4`; incomplete or conflicting CLI options return `2`.

## Supported declarations

| Role | Source units | Output unit |
| --- | --- | --- |
| Timestamp | `s`, `ms`, `us` | `s` |
| Cell voltage | `V`, `mV` | `V` |
| Temperature | `degC`, `K` | `degC` |
| Pack current | `A`, `mA` | `A` |
| Pack voltage | `V`, `mV` | `V` |

Declare time, cell-voltage and temperature units explicitly. Declare
`--pack-current-unit` and `--pack-voltage-unit` exactly when those channels are
selected. Every channel of one role must share its declared unit. Mixed units
within a role, Fahrenheit, arbitrary gains/offsets and automatic unit detection
are outside this feature. Unit symbols are case sensitive (`mV` is not `MV`).

CSV has no trustworthy unit metadata: the declarations are the caller's
responsibility, even if a column name ends in `_v` or `_c`. Naming a column does
not verify its unit. Normalizing twice with incorrect declarations can produce
incorrect data; keep the conversion record and declare the prepared units if
preparing an already normalized file.

For MDF/MF4, declared sensor units must match metadata before decoding. Existing
V/A/degC aliases are accepted for canonical units; `mV`, `mA` and `K` metadata
must match those exact symbols after trimming surrounding whitespace. Missing,
incompatible or ambiguous selected channels are rejected. MDF master time is
already returned in seconds, so `--time-unit s` is mandatory for MDF/MF4. No
interpolation or new alignment policy is introduced.

## Mapping and subsequent analysis

Use `--config mapping.yaml` to select vendor channel names with the existing
signal mapping. Its required-channel checks still apply; thresholds are always
expressed in standard units. Normalization does not evaluate those thresholds.
The prepared CSV contains only selected channels, with canonical names.

For subsequent analysis, use CLI thresholds or a validation YAML **without the
original vendor `signals` mapping**. That mapping refers to the source names,
which have been replaced. The original config schema v6 and analysis result v8
remain unchanged.

All selected measurements must be real, finite numeric values. Normalization is
strict even if the supplied config asks analysis to exclude invalid rows. It
does not exclude rows, replace invalid values, flip current signs, zero time,
sort rows, infer cell topology or check physical plausibility. Source and
converted timestamps must be non-decreasing across chunks; duplicates remain.
If multi-group MDF extraction yields missing aligned samples, preparation fails.

## Conversion evidence and limits

`conversion.json` is a separate `normalization_schema_version: 1` envelope with
`analysis_performed: false`. It records source SHA-256 and size, captured config
evidence when provided by the CLI, output CSV SHA-256, rows written, package
version and each source/canonical channel's source unit, target unit, divisor
and offset. The computation is `output = source / divisor + offset`: milli units
divide by `1000`, microseconds by `1000000`, and Kelvin subtracts `273.15`.

Calculations use binary64 and normal CSV numeric parsing; this is not an exact
decimal or bit-preserving transport. Nonzero values that underflow to zero
during division are rejected. Values that merely round remain subject to normal
binary64 precision. A source snapshot is used and its original SHA-256 is checked
again before publication. Failures and interruptions remove temporary files.
The two files are staged together and the prepared directory is then published;
do not run concurrent writers for the same destination.

Keep the conversion record with the prepared CSV and analysis report. Analysis
report provenance identifies the prepared CSV; it does not automatically embed
the original source or conversion record. SHA-256 evidence is unsigned and does
not certify calibration, metadata accuracy or battery safety.

## Python API

```python
from dataclasses import replace
from batterylog import AnalysisService, SourceUnits, load_validation_config, normalize_measurement

config = load_validation_config("mapping.yaml")
prepared = normalize_measurement(
    "source.mf4",
    "prepared/run-001",
    units=SourceUnits(timestamp="s", cell_voltage="mV", temperature="K"),
    config=config,
)
analysis = AnalysisService(replace(config, signals=None)).analyze_path(
    "prepared/run-001/normalized.csv"
)
```

The API accepts a config object; it does not infer its original YAML bytes.
`config_evidence` is optional caller-supplied evidence for that captured config.
Conversion iterates through CSV/MDF chunks; input channel count and backend
metadata also consume memory. Snapshots and prepared output require additional
disk space proportional to input/output. This is not a fixed process-memory cap.
