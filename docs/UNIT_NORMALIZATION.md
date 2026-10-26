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
does not exclude rows, replace invalid values, flip current signs, sort rows,
infer cell topology or check physical plausibility. Source time is retained
unless relative-time preparation is explicitly requested below. Source and
converted timestamps must be non-decreasing across chunks; duplicates remain.
If multi-group MDF extraction yields missing aligned samples, preparation fails.

## Optional relative time for CSV clocks

Large absolute clocks, such as epoch seconds, can lose short intervals when
converted to binary64 before subtraction. For CSV, explicitly prepare elapsed
time from the first source row:

```sh
batterylog source.csv --normalize --relative-time --time-unit s \
  --cell-voltage-unit V --temperature-unit degC --output-dir prepared/elapsed
```

The Python equivalent adds `relative_time=True` to `normalize_measurement`.
This subtracts the first raw decimal timestamp from every raw timestamp using
exact rational arithmetic, divides by the declared time-unit divisor, then
converts the elapsed value to binary64 seconds. The origin is fixed for the
entire file, including chunk boundaries. Duplicate timestamps and real gaps
remain; rows are never sorted, interpolated or removed. Negative source origins
are allowed; the first output time is zero. A backwards source clock fails.

Relative-time preparation uses `normalization_schema_version: 2`; default unit
normalization retains version 1. The version-2 `time_basis` field records
`mode: relative_to_first_sample`, the exact `source_origin` token in
`source_unit`, its integer `divisor`, `output_unit: s`, and
`arithmetic: exact_decimal_difference_then_binary64`. For this mode the timestamp
conversion is `elapsed_s = (source_timestamp - source_origin) / divisor`, rather
than the per-channel unit formula alone. To relate an event back to the source,
use `source_timestamp = source_origin + elapsed_s * divisor`; use decimal or
rational arithmetic when reconstructing large absolute clocks. Event/report
times refer to the prepared elapsed clock, not to epoch time. Keep the conversion
record beside those reports. Original and prepared file hashes remain separate.
The analysis report does not automatically embed this conversion record.

This option requires raw CSV timestamp tokens. It rejects MDF/MF4: master-time
precision already lost by a binary64 backend cannot be recovered by subtraction.
Timestamp tokens are limited to 256 characters, decimal exponent and adjusted
exponent within -128 to 128. A positive source-time step that collapses to the
same binary64 elapsed value is rejected, including across chunks; split such
long recordings into shorter time spans. Preserving distinct timestamps does
not guarantee exact interval arithmetic at every span or threshold. Measurements,
prepared times and subsequent engineering calculations still use binary64.
Ordinary analysis and default normalization do not change their time basis.

## Conversion evidence and limits

`conversion.json` is a separate version-1 (default) or version-2 (relative-time) envelope with
`analysis_performed: false`. It records source SHA-256 and size, captured config
evidence when provided by the CLI, output CSV SHA-256, rows written, package
version and each source/canonical channel's source unit, target unit, divisor
and offset. The computation is `output = source / divisor + offset`: milli units
divide by `1000`, microseconds by `1000000`, and Kelvin subtracts `273.15`.

Except for the explicit raw-clock subtraction above, calculations use binary64
and normal CSV numeric parsing; this is not an exact decimal or bit-preserving
transport. Nonzero values that underflow to zero
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
