# Report time-series reduction

BatteryLog prepares plot data separately from the machine-readable `AnalysisResult`. The report-series layer is presentation support only: it must not recalculate validation status, rule decisions, violation intervals, limit values, or worst-case event markers.

## Series contract

Each retained point contains the original global data-row index and timestamp plus five row-level metrics already computed by the streaming analyzer:

- minimum cell voltage
- maximum cell voltage
- cell-voltage delta (`max - min`)
- minimum temperature
- maximum temperature

`AnalysisResult` schema v2 is unchanged. Plot limits and violation markers must continue to come from `AnalysisResult`, while the report series supplies only time-series geometry.

## Deterministic downsampling

The default report budget is 2,400 retained points. Inputs at or below the configured budget are preserved losslessly.

When the source exceeds the budget, BatteryLog switches to `extrema-preserving-v1` reduction:

1. Source rows remain ordered by their original global row index. Reduction never uses loader chunk boundaries as bucket boundaries.
2. Rows are summarized into fixed, globally aligned base blocks. A block retains its first and last row plus the row containing the minimum and maximum of each of the five plotted metrics.
3. Duplicate candidate rows are collapsed by original row index and retained in source order.
4. When too many summarized buckets accumulate, adjacent buckets are merged. A merged bucket applies the same first/last plus per-metric min/max rule to the candidates from its children.
5. Recursive merging is safe because the minimum or maximum of a union must be one of the child minima or maxima. The reducer therefore does not need discarded interior rows to preserve the extrema invariant.
6. The final number of retained points is bounded by the configured point budget. Equal extrema use the earliest source row as the deterministic tie-break.

The reducer is deliberately independent of measurement-loader chunk sizes. Tests require identical report-series output for the same canonical samples split into different chunk boundaries.

## Violation evidence

Downsampling can omit a non-global local shape feature inside a summarized interval. It must therefore never be the source of violation evidence. Report renderers must overlay violation intervals and worst-case markers from the existing `AnalysisResult["violations"]` events. This keeps PASS/FAIL semantics and auditable evidence independent from visualization decimation.

## Performance boundary

The streaming analyzer passes already-computed NumPy metric arrays to the collector by chunk. After reduction begins, only extrema candidates from small globally aligned blocks are materialized as Python point objects. This keeps retained memory bounded by the configured report budget plus reducer working state and avoids creating one long-lived plot point per source row.
