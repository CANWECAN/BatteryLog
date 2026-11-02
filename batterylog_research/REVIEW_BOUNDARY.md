# Research evaluation boundary — peer-relative voltage steps

External specialist feedback: sudden/unexplained voltage or temperature
changes and engineering cutoffs are a useful observational boundary;
attribution of degradation, internal resistance or failure mechanisms
requires a model and separate supporting data.

The experimental observable is:
    delta_v[i] = v[i,t] - v[i,t-1]
    reference = median(delta_v)
    supporters = count(abs(delta_v[i] - reference) <= configured_threshold)
    if supporters <= floor(number_of_cells / 2): reference is AMBIGUOUS
    else: candidate[i] if abs(delta_v[i] - reference) > configured_threshold

The threshold and maximum time gap are user-selected, not calibrated.
The implementation rejects malformed/non-finite input and duplicate
cell indices, prevents comparisons across time gaps, retains signed
per-cell and median changes, records observed pack-current deltas and
bounds output examples. Strict-majority peer consensus is mandatory before
individual candidates are reported; otherwise the eligible pair increments
`ambiguous_peer_reference_pairs` and emits no cell candidates. An empty
candidate list does **not** mean the measurement was healthy. No PASS/FAIL
status or physical diagnosis.

Critical blind spots: a genuine pack-wide common-mode voltage event
can cancel from this metric; legitimate differential cell response to
load pulses can be flagged; asynchrony, mux timing, stale sensor values
and zero-order hold can produce spurious events. A three-cell median
is not a guarantee of reliability.

The bundled synthetic failure-model example yields two threshold
crossings for cell_3_v, at t=3s and t=9s. Both coincide with 100 A
current transitions and therefore do not establish two faults.

Before Core integration: obtain synchronized source data and topology
provenance, separately label benign load changes, acquisition artifacts
and known/injected faults, characterize false positive rates, run full
Research regression, and require a defensible device-specific threshold.
Until then, keep this an opt-in experimental forensic observer without physical diagnostic claims.

The complete longer-form engineering review and 44-test suite are in
the cloud review package; they have not yet been uploaded into the
private repository owing to a repository test-file write failure.

## Independent consensus-hardening experiment (2026-10-12)

Adversarial counterexample: with four cells, two dropping -300 mV and two
remaining stable, the earlier median-only detector placed the reference
halfway between these groups and attributed *four* cell outliers.
The updated observer **abstains** when no strict majority of cells lies
within the engineer's configured step-review threshold of the median.
It retains `eligible_sample_pairs` and separately records the number
of `ambiguous_peer_reference_pairs`. It does not silently count those
pairs as clean observations.

This is a **conservative reporting policy**, not a statistical proof
that a majority is correct, and it may suppress true differential
anomalies when a clear majority is absent.

An independently seeded simulation exercised 3, 4, 5, 8, 16 and 96
cell populations, 500 trials each of five regimes (15,000 synthetic
one-step comparisons): noise, uniform common-mode load change,
single-cell outlier, split population and opposed outliers.
The single-cell case was detected in all 3,000 simulated instances;
uniform load and small noise produced no flags. For even equal splits,
the observer abstained rather than flagging all cells. This **does not
estimate field sensitivity or false-positive rates**.

Counterexample retained for acquisition timing: a physically common
voltage step arriving one row late in a multiplexed/ZOH cell channel
produces two apparent cell-step observations even with the consensus
guard. Cell synchronization and source-channel timestamps are still
mandatory; they cannot be inferred from this canonical CSV.

Verification:
- Isolated local Python 3.13: 87/87 focused tests passed, including
  the original detailed 47-case test collection and 40 pytest cases
  now under the repository's top-level `tests/` directory.
- 300 seeded independent numerical oracle scenarios are covered by
  both the detailed and the collected regression sets.
- A 20,001-row x 96-cell synthetic streaming run completed with ~0.046
  MiB traced peak allocations in this observer (Python tracemalloc);
  ~27.5 s **with tracing enabled**, not a realistic application SLA.
- The full Research test suite, native GUI tests, Ruff, mypy, CI and
  real synchronized source-data validation are still outstanding.

## Adversarial source-file line provenance (2026-10-12)

CSV permits quoted metadata fields containing physical line breaks.
The original observer reported `csv_row` by enumerating *logical*
CSV records, which silently pointed engineers to the wrong location.
The new observer uses the CSV reader's physical `line_num` to identify
the beginning of each logical record, including records spanning
multiple lines. The same correction applies to malformed-input
diagnostics. A single-line CSV keeps identical `csv_row` values.

Reproducer: in the test fixture, a metadata quote occupies physical
source lines 2 and 3 and the next row contains a peer-relative
voltage step on physical line **4**. Old output claimed `csv_row=3`;
new output accurately reports `csv_row=4`.

Verification: 94/94 focused Python tests in the isolated cloud environment,
including 1,000 seeded variations over 3, 4, 5, 8, 16, 48 and 96 cells
with independently varied multiline metadata fields. The 120,001-row,
96-cell local stress fixture (~45.9 MiB, ~6.26 s processing, ~93.7 MiB
whole-process peak RSS on one host) counted all 120,000 engineered
step observations. The stress fixture is generated and discarded, not
committed to the repository.

This fixes evidence *location*, not the unresolved physical
synchronization/diagnostic limitation. A real BMS dataset and full
CI/Linux/Windows regression remain required before integration.
