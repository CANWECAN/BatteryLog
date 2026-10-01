# Measurement adapter contract

This documents the existing measurement boundary used by early 0.10 development.
It does not add a config/result schema, infer battery topology, or convert units.
`MeasurementLoader` remains a structural protocol yielding pandas DataFrames;
the analysis engine is the authority for canonical mapping, required-value
validation, timestamp ordering and engineering evidence.

## Signals and physical units

| Role | Canonical identity | Required physical unit | Availability |
| --- | --- | --- | --- |
| Time | `timestamp_s` | seconds on one measurement time basis | required |
| Cell voltage | `cell_<n>_v` | volts | at least one required |
| Temperature | `temp_<n>_c`, or legacy `temp_c` | degrees Celsius | at least one required |
| Pack current | `pack_current_a` | amperes | optional; required by an active current rule |
| Pack voltage | `pack_voltage_v` | volts | optional; required by an active pack/cell-sum rule |

Numeric indices identify channels and determine ordering; they do not establish
physical cell positions, a contiguous stack, or a series-cell count. Duplicate
logical indices and mixed legacy/indexed temperature names are rejected.
Explicit mapping assigns source names to the same roles and does not convert
units. One source cannot supply multiple mapped roles.

CSV and custom adapters must supply the units above; the engine cannot verify
units from a CSV name. MDF/MF4 validates selected channel metadata against its
supported V/A/degC aliases and rejects missing or incompatible units. Automatic
unit conversion is unsupported. Current-rule configuration must declare which
direction positive source current represents; result evidence preserves the
source sign, including signed current limits.

## Values and row alignment

Adapters yield scalar real-number measurements, or preserve invalid/missing
values for the engine's data-quality policy. CSV numeric tokens are parsed by
pandas; supported computations and comparisons use binary64. This is not an
exact decimal or arbitrary-precision API. Boolean values are invalid required
measurements, even though Python treats bool as numeric. Do not turn booleans,
missing values or non-numeric tokens into valid zeroes.

The selected timestamp, every selected cell and temperature, and each present
pack signal participate in required-value validation even when their rules are
disabled. In strict mode an invalid required value aborts analysis. Exclusion
mode records the defect and excludes the entire row; it never silently drops
only the bad sensor. Present pack channels with no analyzed rows therefore have
null extrema. An absent optional pack signal does not activate a rule.

Each row represents channels already placed on one time basis by the source
preparation. Finite timestamps must be non-decreasing across chunks; duplicate
timestamps are allowed and retained. A valid timestamp on a row excluded for
another channel still participates in ordering checks. An event gap is used
only when configured; exclusion breaks engineering-event row contiguity.

MDF/MF4 time comes from the measurement master, not a separately named data
channel. With explicit mapping, `signals.timestamp` names that synthetic time
column. Selected channels sharing a group must have the same master. The
multi-group path retains a no-interpolation union of timestamps; non-aligned
samples remain missing and follow data-quality handling. Neither path proves
physical simultaneous acquisition, calibration, or sensor latency.

## Chunk and lifetime responsibilities

`iter_chunks(signal_mapping=...)` yields source-named frames in source row order;
the engine applies mapping. Adapters must not pre-rename explicitly mapped
columns. MDF/MF4 may use the mapping to select channels before yielding them.
Selected canonical channel identities must remain stable across non-empty
chunks, including optional pack channels. Empty frames are skipped; a source
with no data rows fails. Chunk boundaries must not change rows, defect evidence,
peaks, event grouping or status.

Adapters must preserve defects and row order rather than interpolating,
forward-filling, sorting or silently dropping source rows. Built-in file
adapters rewind a caller-owned seekable binary handle and leave it open. Path
adapters manage their own handles. Analysis consumes a loader once and closes
its chunk iterator, when it exposes `close()`, on success or failure. This runs
generator `finally` blocks even when the caller retains an error traceback.
Custom adapters must put their resource cleanup in that lifetime boundary;
iterators without `close()` remain supported. Loader reusability remains the
adapter's responsibility. Closing an iterator must not close a caller-owned
input handle.

## Pack/cell topology and provenance

The pack/cell-sum rule is meaningful only when selected cell channels cover the
complete synchronized series stack corresponding to the pack-voltage sensor.
The operator must verify this preparation before enabling the rule. The tool
cannot establish it from channel names, equal row counts or a PASS result.
Parallel-cell voltage channels, incomplete selections and multiplexed BMS data
need a justified reconstruction/alignment step outside this boundary.

Analysis alone does not authenticate a source or bind a result to file hashes.
The CLI evidence-report workflow still analyzes a private file snapshot and
records its provenance. See [the analysis service](ANALYSIS_SERVICE.md),
[technical reference](REFERENCE.md) and [report-series contract](REPORT_SERIES.md).
