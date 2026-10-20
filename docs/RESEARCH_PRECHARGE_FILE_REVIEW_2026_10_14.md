# Explicit aligned-file precharge review — 14 October 2026

The Research observer now has a file interface. It accepts an explicitly aligned
five-column CSV plus a separate JSON declaration containing the reference and
measurement context. This does not import vendor CAN/MF4 files, construct phase
truth, synchronize channels or authenticate physical measurements.

## Run the authored example

From the private source checkout with the existing runtime dependencies:

```sh
python -m batterylog_research.precharge_file_review \
  --csv batterylog_research/fixtures/precharge_aligned_example.csv \
  --context batterylog_research/fixtures/precharge_aligned_example.context.json \
  --output /path/to/new-precharge-review.json
```

The bundled example is authored software input. Its values and bands are not
recommended physical limits. Output is a complete new JSON file; an existing
name, including a concurrent publisher, is refused. Encoding or validation
failure creates no output. Publication links a closed staged file on the
destination filesystem; filesystem failure raises rather than falling back to
an overwriting write. Crash/power-loss durability is not claimed.

## CSV contract

The header must be exactly this ordered list:

```text
timestamp_s,precharge_active,current_a,pack_voltage_v,dc_link_voltage_v
```

- Units are seconds, amperes and volts. No inferred conversion or column aliases.
- Preserve original source order. Exact decimal timestamp tokens are compared
  before conversion so binary64 rounding cannot hide a backward clock.
- Timestamp intervals and elapsed times use exact decimal subtraction before
  conversion of durations to binary64. Large clock origins do not hide gaps or
  round the reference horizon early. Measurements/reference calculations remain
  binary64; overflow and nonzero timestamp underflow are rejected. True duplicate
  timestamps still interrupt qualification; no artificial time is inserted.
  See [the clock correction](RESEARCH_PRECHARGE_CSV_CLOCK_2026_10_17.md).
- Phase numeric zero/one is classified before conversion. Empty or other numeric
  phase values remain unknown, including values just above one. Text state names
  are rejected. This is a prepared binary phase interface, not a state decoder.
- Empty analog measurements remain missing. Other fields require numeric tokens;
  textual NaN/Infinity, booleans and malformed records are rejected.
- Every CSV record has five fields. Blank records and duplicate/extra headers are
  errors. UTF-8 BOM is supported; quoted multiline numeric records retain their
  physical source-line ranges.
- The existing capture observer decides span continuity and sampled coverage.
  Gaps, unknown phase and invalid active measurements cannot be healed by later
  samples. Earlier deviations remain evidence. Multiple spans use one explicitly
  justified reference; incompatible procedures need separate calls.
- Bounds are 64 MiB of CSV bytes, 1,000,000 data records and 1 MiB of context
  bytes. They raise without truncation. Inputs stay in memory; this is not a
  streaming or constant-memory guarantee.

## JSON declaration

The example context is the complete format reference. Required top-level keys:

| Field | Meaning |
| --- | --- |
| format | Exactly batterylog-precharge-aligned-v1 |
| capture_sha256 | Lowercase SHA-256 of the exact CSV byte snapshot |
| input_kind | authored_fixture or producer_aligned_capture |
| measurement_context | All nine nonempty textual declarations listed below |
| same_reference_for_all_spans | Literal JSON true; caller justification is required |
| max_gap_s | Existing observer's finite positive maximum source gap |
| envelope | Existing five-column declared reference, beginning at elapsed zero |

Optional max_spans and max_examples retain the existing defaults of 1,000 and
five per span. Unknown keys, missing declarations and duplicate JSON keys at
any depth are rejected. Nonstandard JSON NaN/Infinity are rejected; timing,
reference and output values must satisfy the existing finite numerical rules.

measurement_context contains exactly: time_basis, alignment_basis, phase_basis,
current_path_and_sign, voltage_nodes, validity_policy, acquisition_uncertainty,
procedure and reference_justification. These are caller declarations, not a
proof that physical acquisition is suitable. The output always labels them
caller_declarations_not_authenticated. Supplying text cannot qualify BMW,
resolve an unknown logger clock, or turn a software fixture into field evidence.

The reference columns are elapsed_s, min_abs_current_a, max_abs_current_a,
min_voltage_gap_fraction and max_voltage_gap_fraction. Voltage gap is signed
(pack - DC-link) / pack. Interpolation is confined to reference bounds; source
measurements are never interpolated. Time zero is the first observed active
sample with a qualified preceding inactive observation, not a physical switch
instant.

## Evidence and boundaries

Reports contain the exact input-byte hashes and sizes, declarations, implementation
file hashes, unchanged capture-observer facts and physical CSV lines for retained
examples/span bounds. Input files are read into bounded byte snapshots; the
reported hash identifies what was analyzed, not authentication of its producer or
a guarantee that another process has not subsequently changed the named path.

The BMW measurement/clock gates in
[the measurement contract](RESEARCH_BMW_MEASUREMENT_CONTRACT_2026_10_14.md)
remain unresolved. Raw BMW CSV is not accepted by this header contract. No
source-specific BMW alignment, normal envelope, physical failure label,
Core decision/schema, dependency, GUI or package entry point is added.

Tests exercise the real CLI, original numeric precision, unknown/missing data,
physical source lines, reference reuse and limits, context binding, strict JSON,
output failures and a competing publisher. Native campaign/full-suite evidence
is recorded in CURRENT_STATE and the draft PR with exact source identities.

## Native verification checkpoint

Native Windows with actual Tk and installed MF4: 2,842 passed / two skipped /
nine existing warnings, Core coverage 96.67%. Whole-tree Ruff check/format,
Core mypy (48 files) and dependency consistency passed. The final source and
new tests are fingerprinted in precharge_file_native_validation_20261014.json.

The final wrapper campaign checked 500 generated captures / 37,665 rows /
7,076 active spans against the original array observer; all results matched.
Input hashes stayed unchanged. A separate 100,001-row CSV reviewed 100,000
active samples with exactly one authored deviation in 1.43 seconds on this
Windows host. Whole campaign process peak working set was 154.02 MiB; this
includes imports, source generation and both profiles, not just review memory.
See precharge_file_campaign_results_20261014.json for exact measurements.

These authored measurements are software evidence, not a physical precharge
accuracy claim. Hosted verification is tracked on the draft's exact commit.
