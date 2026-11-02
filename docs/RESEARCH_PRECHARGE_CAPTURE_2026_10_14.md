# Precharge capture inventory and independent span review

Private Research, 14 October 2026. Based on
`f28b016e33d0e337b370ffa582bf40c8d5b6948a`, the precharge curve contract closure.
This extends the Python observation interface for captures containing more than
one active span. It does not add a Core rule, file importer or physical diagnosis.

## Input and reference contract

`batterylog_research.precharge_capture_review.review_precharge_capture` takes
the same aligned numeric arrays, declared envelope and `max_gap_s` as the
[single-interval observer](RESEARCH_PRECHARGE_CONTRACT_2026_10_14.md).
The original row order is preserved. Controls, the entire source and the
envelope are validated even when the capture has no active rows.

One envelope is reused only when the caller has justified it for each observed
activation: procedure, initial DC-link voltage, pack voltage, capacitance/load
state and acquisition uncertainty must be comparable or covered by the bands.
This helper does not choose a reference, normalize incompatible procedures or
identify RC parameters. Use separate calls/references for differing contexts.

## Spans and observed activations are different

A span is a maximal group of adjacent rows whose phase equals one. It is a
recorded row group, not proof of a unique physical episode. An unknown phase
sample separates spans; a later active span without a qualified preceding
inactive observation has an unobserved activation and zero reviewed samples.
Unknown values are counted separately. A gap or duplicate time within a known
active span does not create a new qualified onset or restore lost qualification.

Each review includes at most one preceding and one following row for boundary
evidence. The following inactive/unknown row distinguishes a phase end or
unknown state from an EOF. The single-interval observer still rejects multiple
observed activations; the capture helper dispatches independent row slices.

Output records:

- Original active/review row ranges, with exclusive stop indices.
- Original timestamps and observed inactive-to-active brackets.
- Per-span comparison facts, incompleteness reasons and reference-horizon bracket.
- Examples whose `sample_index` points into the **original capture**, not a slice.
- Separate totals for known active samples, unknown-phase samples, observed
  activations, unobserved active spans, covered reference intervals, reviewed
  samples and deviations. No aggregate PASS/FAIL is inferred.

An empty inventory has zero observed activations and zero covered reference
intervals; it is not a clean/complete precharge finding. Inactive measurements
are outside the observer's comparison scope. Behavior after the reference
horizon is not compared, even if the known-active span continues. The original
source ranges and capture-level unknown-phase count remain available.

## Output and resource boundary

`max_spans` defaults to 1,000 and must be a positive Python integer; booleans are
rejected. The complete span inventory is counted before any curve review. If it
exceeds this declared limit, the helper raises without returning a truncated
capture. `max_examples` retains the single-observer bound of 0–100, per span;
limiting examples never changes deviation counts.

All source arrays remain in memory. The helper bounds returned span/example
records, not total acquisition size or runtime, and offers no streaming or
constant-memory guarantee. It does not sort, fill missing samples, heal gaps or
invent switching times. It remains a Research Python interface, with no arbitrary
CAN/MF4/vendor-CSV ingestion or GUI integration.

```python
from batterylog_research.precharge_capture_review import review_precharge_capture

report = review_precharge_capture(
    times,
    phase,
    current_a,
    pack_voltage_v,
    dc_link_voltage_v,
    declared_envelope,
    max_gap_s=allowed_gap_s,
    max_spans=1000,
    max_examples=5,
)
```

## Verification and numerical correction

The local final focused suite has 131 passing tests: 35 new capture tests,
40 single-observer tests and 56 existing Core precharge tests. Capture checks
cover two independent activations, global source indices, unknown-phase
fragmentation, unobserved starts, gap/duplicate/invalid-measurement interruption,
early phase end versus EOF, horizon bracketing, immutable inputs, whole-capture
validation and limits that raise before partial evaluation.

A reproduced defect in the preceding observer allowed finite timestamps such
as `[-1.5e308, -1.4e308, -0.5e308, 0.5e308]` to produce an infinite elapsed-time
bracket and `declared_interval_covered=true`. JSON with `allow_nan=False` then
failed. Elapsed-time subtraction is now checked for finiteness before coverage
is considered; both interfaces raise a clear error. This is a numerical contract
correction, not a physical measurement claim.

Validation helpers are shared privately between the two Research modules. Core
code, statuses, thresholds, schemas and package configuration are unchanged.
The original seven-case generated curve observations remain exactly unchanged;
only their recorded script hash was refreshed for the corrected source.
Whole-tree Ruff check/format and mypy over the 48 Core files passed locally.
Full hosted CI passed on the corrected source; closure evidence is below.

The first hosted run stopped the Linux/Windows format gate on the Python example
in this document, which was added after the earlier local format check. The
example was corrected and whole-tree Ruff format/check passed on the complete
document-inclusive tree. Package and all five MF4 jobs succeeded in that run;
the initial failed run is not full-suite verification.

```sh
python -m pytest -q tests/test_research_precharge_capture_review.py tests/test_research_precharge_curve_review.py tests/test_precharge_current.py
```

## Next gate: severe stress characterization

After this build closes, measure long captures, many spans near/over the output
bound, phase fragmentation, source discontinuities, multiple timing scales,
numeric extremes and retained evidence against an independent boundary/count
oracle. Record wall time and memory separately from correctness. Compare
repeated calls and equivalent separately reviewed source slices, and require
strictly finite JSON output or a declared exception. Do not infer physical
failure-detection accuracy from those software tests.

The real-data gate remains exported phase/current/pack/DC-link channels,
identified measurement nodes, timing uncertainty and a justified reference.

## Hosted build closure

Draft [PR #5](https://github.com/CANWECAN/BatteryLog-Research/pull/5) is stacked
on the precharge curve contract branch. Initial code commit
`abbe91cf69255962e70d3681e81be7d8bc8193f1` is followed by documentation correction
`999770f5a5c41367bc4c6da12f9229ead72003a5`, tree
`fc99f896b01b05c91e1078fe6248e7a429ab4bd0`, identical to the local tree.
Code, tests and generated observations did not change in that correction.

[Run 38528409961](https://github.com/CANWECAN/BatteryLog-Research/actions/runs/38528409961)
completed SUCCESS with all 12 jobs passing: Linux Python 3.11–3.14, minimum
runtime, Windows, five MF4 combinations and package verification. Inspected
Linux 3.12/3.13 jobs each report 2,594 passed, two skipped, nine warnings and
96.23% coverage. Minimum runtime has the same pass/skip counts and coverage with
ten warnings. Windows 3.13 reports 2,592 passed, four skipped, nine warnings and
96.21% coverage. Inspected Linux 3.12 and Windows MF4 jobs each report 175 passed.
The existing 95% coverage gate passed.

This closure is documentation-only; a newly triggered closure run is separate
from the verified corrected-source run. Severe stress characterization is planned
above and has not been executed in this build. Physical performance was not evaluated.
