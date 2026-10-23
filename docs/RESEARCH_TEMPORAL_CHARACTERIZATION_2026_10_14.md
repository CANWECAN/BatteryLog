# Temporal characterization — 14 October 2026

## Scope and restored baseline

Private Research source snapshot: `083344f2119f5e94c2f444a4eec0dbc418cc1e57`.
All 253 tracked blobs and the complete source tree
`4877c58f923eb4182cbeabddb1e99cca4e0db88a` were byte-verified before work.
The cloud materialization has a separate local snapshot commit; it is not a
claim that the private Git history was cloned. New remote commits must use the
original private source commit as their parent.

The existing temperature triage and field episode review were inspected and
retained. This work adds a separate investigative harness, not another production
detector. It does not change Core calculations, statuses, result schemas, thresholds,
balancing behavior, licensing or a release.

## Temperature comparison

The harness compares the existing adjacent-sample rate against original-sample
endpoint secants with 1, 2 and 5 second horizons. It requires a continuous block
of finite temperatures and positive adjacent timestamp intervals no greater than
the selected gap. Invalid temperature rows, duplicate times and excessive gaps
break candidate window continuity. No interpolation or physical-value filtering
occurs. A window is an alternative sampled statistic, not a reconstruction of
sensor freshness, internal temperature, or physical thermal behavior.

Synthetic settings: 0.32 s sample interval, 1 s maximum gap, 0.25 s minimum
adjacent interval, 10 degC/min comparison threshold. Quantization is explicitly
0.1 degC; the ZOH scenario refreshes a known 12 degC/min ramp every 2 s. All are
software-characterization settings, not recommended engineering limits.

| Injected source behavior | Adjacent peak degC/min | 5 s endpoint peak degC/min | Observation |
| --- | ---: | ---: | --- |
| Constant 25 degC | 0 | 0 | Neither statistic exceeds the example threshold |
| Linear 12 degC/min ramp | 12 | 12 | First exceedance 0.32 s vs 5.12 s from capture start |
| Same ramp quantized to 0.1 degC | 18.75 | 12.890625 | Window reduces peak distortion; coverage and warmup must be reported |
| Same ramp held for 2 s | 75 | 14.0625 | Window does not reproduce the underlying ramp exactly |
| Single 0.1 degC step | 18.75 | 1.171875 | Example adjacent threshold exceedance disappears under the window |
| Short 0.5 degC pulse | 93.75 | 5.859375 | A known short injected change is missed by the 5 s alternative |
| Short source pulse reaching 655.28 degC | 118177.5 | 7386.09375 | Averaging does not make implausible source values physically valid |

The last two pulses start at declared time 5 s and are present in samples at
5.12 and 5.44 s. The first sampled indication therefore has a 0.12 s sampling
delay. The linear ramp begins at capture start: its window delay includes
initial warmup and is not a universal steady-state latency claim.

Counts are exceeding **observations**, not faults or grouped events. Adjacent
eligible and exceeding counts are checked against actual BatteryLog evaluated
samples and summed event sample counts. A smaller output count is not a success
criterion. No method is selected for production by this study.

## Sag eligibility

An independent source trace records load episodes, reference age at load onset,
and the observed low-current sample span before that reference. That sample span
does not prove electrochemical relaxation. No minimum resting-duration rule is
introduced. The supplied trace currently requires finite current/time arrays;
it is an investigative helper, not a general CSV adapter or invalid-row policy.

| Synthetic episode | Existing Core outcome | Observed explanation |
| --- | --- | --- |
| Two seconds of observed low current, then load | PASS | One qualified reference and load observation |
| Load resumes after a 1 A intermediate stage | NOT_EVALUATED | The first reference was consumed; second load has no new qualifying reference |
| One low-current sample, then load | PASS | Accepted reference has zero observed low-current span; relaxation remains unknown |
| Six-second-old reference with a five-second age limit | NOT_EVALUATED | Reference is stale |

These examples use identical constant cell voltages to isolate eligibility.
They do not test physical sag or healthy/faulty-cell discrimination. Episode
reason counts are separate from Core incomplete_intervals, which can additionally
include interruption accounting.

The pinned CORA summary records 2,129 incomplete sag intervals per profile.
Those historical counts belong to its recorded source identity. Fresh retrieval
returned publisher bot-check HTML, so this study did not repeat the raw-data
campaign. Per-cycle reasons and observed low-current distributions require the
pinned source files.

## Verification and reproduction

- New focused tests: 22 passed. Independent enumeration covers 160 randomized
  window traces; 80 seeded dynamic-current traces match Core eligible counts.
- Existing focused model/oracle/triage suite: 130 passed, one existing numeric
  overflow warning.
- Full cloud Python 3.12 suite: 2,475 passed / 46 skipped / nine existing overflow
  warnings in 261.95 s. The coverage command exited nonzero: 89.26% is below the
  unchanged 95% gate, primarily because no display is available for desktop tests.
  This is not a passing coverage run. Hosted Linux/Windows display/MF4 CI remains
  the required gate; a system Xvfb installation attempt was unavailable in this
  restricted cloud container and no coverage threshold was lowered.
- Whole-tree Ruff check/format, pinned mypy 1.19.1 for all 48 Core source files,
  and dependency consistency passed. The generated JSON script SHA-256 matches
  the tested final script. Native execution was not performed for this source revision.

Run from a private Research checkout:

```sh
python -m batterylog_research.temporal_characterization --output /path/to/new-summary.json
python -m pytest -q tests/test_research_temporal_characterization.py
```

Output uses exclusive creation and preserves an existing file. The full-array
comparison uses memory proportional to the supplied arrays; no streaming-memory
guarantee, physical labels, real false-alarm rate or new Windows-local run is
claimed. The original source and final result contracts remain unchanged.

## Next decision

Keep the current adjacent statistic until explicit source-resolution/update-rate
requirements and acceptable missed-change/latency tradeoffs justify a separate
windowed mode. Reuse existing triage for suspect evidence. Measure real sag
reference spans and episode eligibility before adding resting-time parameters.

## Hosted verification closure

Exact tested source commit: `6de2873fc651fe9930011f0c5d126e6e0b7de9dd`.
[Research CI run 38521164177](https://github.com/CANWECAN/BatteryLog-Research/actions/runs/38521164177)
completed SUCCESS with all 12 jobs successful: four Linux Python versions,
minimum runtime, hosted Windows, five actual MF4 jobs and package verification.

Inspected job logs: Linux Python 3.12 and 3.13 each 2,519 passed / two skipped /
nine existing warnings, coverage 96.23%; hosted Windows 3.13: 2,517 passed / four
skipped / nine warnings, coverage 96.21%. The unchanged 95% gate passed on the
screen-enabled runners. Package verification succeeded. These hosted results do
not change the earlier local no-display coverage failure.

Draft PR #3 is stacked against the still-unmerged PR #2 branch. This closure edits
documentation only; the script, tests and result-summary blobs are identical to
the successful source commit. A closure commit can trigger a separate CI run;
the run above remains evidence for its specifically named source commit.
