# Precharge observation HTML

> Historical record: licensing and package descriptions below refer to the recorded
> revision. The current unified Apache-2.0 package is defined in [LICENSING.md](LICENSING.md).
> Engineering evidence and qualification limits retain their original scope.

The Research operator writes a self-contained report.html alongside review.json
when reviewing an explicitly aligned precharge CSV:

```powershell
python -m batterylog_research.operator precharge --csv aligned.csv --context context.json --output-dir reviews\precharge-001
```

Open index.html or report.html in a browser. Rendering adds no dependency,
network resource or client script. Narrow screens scroll each plot horizontally.

## Interpretation

Each active span has current-magnitude and relative voltage-gap plots. Voltage
gap is (pack voltage - DC-link voltage) / pack voltage. The envelope is piecewise
linear between caller-declared reference knots. Measured values are points;
they are not interpolated or connected across missing intervals.

Blue points are the observer-qualified prefix. Gray points were not compared.
Red rings identify stored departure examples for that metric; a current
departure does not mark an in-band voltage gap as a departure. Examples may
be capped independently of the complete departure count.

Missing/invalid values use crosses. Source gaps and duplicate times are marked.
Gray background identifies the reference tail not covered by the existing
observer. Human-readable incomplete reasons, exact decimal source times,
activation brackets and CSV-line examples remain visible. Coverage is the
observer's sampling rule, not a reconstruction between measurements or a
physical acceptance decision. Time zero is the first recorded active sample.

The existing review JSON and observer algorithms are unchanged. Rendering
checks the CSV byte hash and row count before parsing it for display. The HTML
records capture, context and exact review JSON hashes. The operator manifest
also hashes the HTML and its implementation.

## Display bounds

All observed spans are summarized. Charts are limited to the first12 spans;
each selects approximately600 points plus metric extrema, qualification edges
and up to five stored examples. At most50 source interruptions are marked per
span. These display bounds do not alter review counts or stored observations.
If the envelope exceeds4,096 knots, charts are omitted explicitly rather than
approximating its bounds. Complete observations and reference knots remain
available in review.json. Only the declared reference window is plotted.

Rendering uses the existing aligned-file input bounds and in-memory parser.
A rendering failure or source mutation prevents publication of the operator
output directory. The source-tree command is outside the frozen alpha add-on
allowlist; distribution packaging is separate.

## Verification

21 display/orchestration regressions cover independent geometry, metric-specific
examples, Decimal epochs, gaps/duplicates/missing/unknown phase, unobserved starts,
horizon bracketing, display bounds, extreme values, escaping and source hashes.
The combined HTML/operator/file-review target has103 passing tests.
Browser checks exercise desktop and390px layouts, SVGs, source anchors and
horizontal chart scrolling. Fixed-source native and hosted qualification is
recorded in the PR and CURRENT_STATE.

Fixed-source acceptance at44bb79e20c11fe48a127cda4445453c607f8d463:
Windows Python3.13.14 with real Tk required and actual MF4 installed:
3,172 passed, two skipped, nine existing warnings in186.76s; Core96.67%.
HTML targeted combined statement/branch coverage99.53% (154/154 statements,
57/58 branches). Ruff/format, Core mypy, pip consistency and whitespace pass.
Core and observer source differences are empty. Subsequent acceptance-only
documentation retains the tested runtime and test bytes.
