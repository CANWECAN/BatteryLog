# Report time-series reduction

BatteryLog prepares plot data separately from the machine-readable `AnalysisResult`. The report-series layer is presentation support only: it must not recalculate validation status, rule decisions, violation intervals, limit values, or worst-case event markers.

## Series contract

Each retained point contains the global analyzed-row index and timestamp plus the row-level cell/temperature metrics, optional pack current, and optional pack voltage with its synchronized cell sum. Temperature spread is derived from the retained temperature envelope; it is not an additional reducer candidate metric. In `exclude_invalid_rows` mode, excluded source rows are omitted from the report series; their original 1-based source-row positions remain available in `AnalysisResult["data_quality"]["events"]`.

- minimum cell voltage
- maximum cell voltage
- cell-voltage delta (`max - min`)
- minimum temperature
- maximum temperature
- optional pack current
- optional absolute pack-voltage versus cell-sum mismatch

The report-series contract remains separate from the current `AnalysisResult` schema v8. Plot limits and violation markers must continue to come from `AnalysisResult`, while the report series supplies only time-series geometry. Structured data-quality evidence also comes exclusively from `AnalysisResult`; it is never inferred from decimated plot points.

## Deterministic downsampling

The default report budget is 2,400 retained points. Inputs at or below the configured budget are preserved losslessly.

When the source exceeds the budget, BatteryLog switches to `extrema-preserving-v1` reduction:

1. Analyzed rows remain ordered by their global analyzed-row index. Reduction never uses loader chunk boundaries as bucket boundaries.
2. Rows are summarized into fixed, globally aligned base blocks. A block retains its first and last row plus the row containing the minimum and maximum of each stored reducer metric. Derived temperature spread remains outside the candidates; optional pack mismatch becomes a candidate to preserve its worst peak. With both pack current and pack voltage, a bucket can contain up to 16 candidates. Downsampling with a budget below 16 raises a clear `ValueError` if the retained extrema cannot fit; budgets of at least 16 preserve the point limit.
3. Duplicate candidate rows are collapsed by original row index and retained in source order.
4. When too many summarized buckets accumulate, adjacent buckets are merged. A merged bucket applies the same first/last plus per-metric min/max rule to the candidates from its children.
5. Recursive merging is safe because the minimum or maximum of a union must be one of the child minima or maxima. The reducer therefore does not need discarded interior rows to preserve the extrema invariant.
6. The final number of retained points is bounded by the configured point budget. Equal extrema use the earliest source row as the deterministic tie-break.

The reducer is deliberately independent of measurement-loader chunk sizes. Tests require identical report-series output for the same canonical samples split into different chunk boundaries.

## Violation evidence

Downsampling can omit a non-global local shape feature inside a summarized interval. It must therefore never be the source of violation evidence. Report renderers must overlay violation intervals and worst-case markers from the existing `AnalysisResult["violations"]` events. This keeps PASS/FAIL semantics and auditable evidence independent from visualization decimation.

## HTML rendering

BatteryLog renders the report series directly as three baseline inline SVG plots inside the self-contained HTML evidence report, plus conditional plots when their source/rule is active:

- cell-voltage minimum/maximum envelope versus source timestamp
- cell-voltage delta versus source timestamp
- temperature minimum/maximum envelope versus source timestamp
- temperature spread versus source timestamp when the spread rule is configured
- pack current versus source timestamp when pack current is present
- pack voltage and cell sum, plus their absolute mismatch versus source timestamp, when pack voltage is present

No external JavaScript, image files, fonts, or plotting package is required. SVG coordinates are deterministically derived from the retained `ReportSeries` points.

The renderer does not infer engineering evidence from those points. Configured horizontal limit lines come from `AnalysisResult["limits_applied"]`. Shaded violation intervals, worst-case timestamps, worst-case measured values, and rule codes come from `AnalysisResult["violations"]`. Worst-case markers are rendered after the time-series geometry so they remain visually on top of downsampled lines/envelopes.

The renderer performs fail-closed consistency checks before emitting SVG: `source_rows` must match `AnalysisResult["rows_analyzed"]`, retained rows/timestamps must be ordered and finite, the declared point budget must be respected, first/last source rows must remain present, cell/temperature envelopes must not invert, each retained cell delta must agree with its voltage envelope, and the retained global extrema must match the extrema recorded in `AnalysisResult`. Structured violation evidence is also checked for finite numeric fields, ordered start/peak/end times, membership in the report-series time domain, and a known plot mapping for the rule code. These checks catch common mismatched or malformed series/result inputs, but they are not a cryptographic identity binding between two independently supplied objects. The CLI avoids that ambiguity by obtaining the result and report series from the same analyzer invocation over the same source snapshot. The report-series contract does not add plot geometry to the JSON result schema.

Instantaneous violation events are rendered as vertical markers rather than artificially widened duration rectangles. A one-row measurement renders explicit sample markers so its retained values remain visible even though an SVG polyline with one point has no visible segment.

## Performance boundary

The streaming analyzer passes already-computed NumPy metric arrays to the collector by chunk. After reduction begins, only extrema candidates from small globally aligned blocks are materialized as Python point objects. This keeps retained memory bounded by the configured report budget plus reducer working state and avoids creating one long-lived plot point per source row.
