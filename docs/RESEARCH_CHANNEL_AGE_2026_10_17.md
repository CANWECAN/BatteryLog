# H5 — authored sampling and channel-age sensitivity

> Historical record: licensing and package descriptions below refer to the recorded
> revision. The current unified Apache-2.0 package is defined in [LICENSING.md](LICENSING.md).
> Engineering evidence and qualification limits retain their original scope.

Scope: software observability experiments, not physical precharge validation.
Core thresholds, failure models and CAN preparation behavior are unchanged.

Run from a source checkout with the Research CAN verification dependencies:
```text
python -m batterylog_research.channel_age_sensitivity --output <new-report.json>
```

The report uses authored classic CAN bytes and a tiny authored DBC. A one-second
source combines same-frame 3.5 V anchors and independently sampled temperature.
It checks 576 combinations: three anchor periods, four context periods, two
phases, six age budgets, two signal shapes and both equal-time source orders.
Each prepared row is compared with a brute-force earlier-record oracle for
source identity, sample age, missingness and independently computed raw units.
No look-ahead or replacement of expired values is permitted.

## Measured illustrative cases

| Case | Observation |
| --- | --- |
| Linear temperature ramp, 10 ms anchors / 100 ms context | 101 prepared rows, 11 independent context frames, 90 reused rows; maximum age 90 ms |
| Same ramp on its context clock | Core 1200 C/min example rate gate PASS |
| Same samples held on the anchor clock | Core example rate gate FAIL, ten events around 6000 C/min |
| Zero allowed age, context first at equal timestamps | 11 usable rows |
| Zero allowed age, anchor first at equal timestamps | No usable temperature rows; later equal-time records are not backfilled |
| 40 ms authored 80 C pulse, 100 ms context, phase zero | No sampled pulse; maximum prepared value 20 C |
| Same pulse, context phase 50 ms | Pulse observed; ten prepared rows exceed the illustrative 55 C line |

The authored linear slope is 600 C/min. Holding and then updating on a faster
clock can create a tenfold adjacent-row rise. This reproduces an interpretation
hazard; it is not a physical false-positive measurement or a calibrated limit.
The phase example similarly demonstrates missing observability and repeated
past measurements, not a manufacturer's diagnostic accuracy.

Reducing age can remove rows or break an evaluated interval. That is not
automatically better signal reconstruction. A high retained-row fraction does
not authenticate sensor synchrony or recover events between source samples.
Derivatives require an explicit acquisition/preparation policy; supplied CSV
rows alone do not establish independent measurement instants.

15 new experiment checks plus existing preparation regressions: 154 targeted
passes. Native exact-source campaign, combined full test and hosted Fast
profile closure are recorded in the draft PR and shared report after completion.

The CLI publishes a new report via a no-overwrite hard link. It bundles no
third-party source, dataset or DBC and is not added to the frozen alpha allowlist.
Original physical precharge 7-8 remain open; adapter 9 remains deferred.
H6 is still bounded dataset qualification; no physical reference was created here.
