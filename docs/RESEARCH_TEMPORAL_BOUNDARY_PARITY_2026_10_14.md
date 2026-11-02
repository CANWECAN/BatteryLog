# Research temporal boundary parity — 14 October 2026

The three retained generated CORA rejections now have an identified cause and
a corrected Research comparison. Core configuration, estimators, event decisions
and numerical tolerance are unchanged.

## Reproduction on the exact retained inputs

The source fixtures are retained in
batterylog_research/kali_step2_validation_results_20261014.json.
Each has exactly one adjacent temperature interval of
0.24999999999999956 seconds (binary64 0x1.ffffffffffff0p-3).

| Original generated case | Right-hand source row index | Core eligible count | Previous helper count | Corrected helper count |
| --- | ---: | ---: | ---: | ---: |
| 98 | 6 | 47 | 46 | 47 |
| 109 | 7 | 52 | 51 | 52 |
| 135 | 7 | 18 | 17 | 18 |

Core's scalar math.isclose uses the larger magnitude of its two arguments.
NumPy isclose scales by the second argument. The helper expressed the minimum
interval test through above(min_interval, dt); at this exact lower tolerance
edge it scaled by the smaller dt and rejected a pair accepted by Core.

The correction makes the Research above function symmetric by considering
NumPy isclose in both argument orders. For finite inputs this reproduces the
same max-magnitude relative guard as Core's scalar comparator. The tolerance
remains eight binary64 machine epsilons with zero absolute tolerance. No limit,
minimum interval or model guard is relaxed.

This shared helper also applies to Research load/settling and window-boundary
descriptions. Tests cover both lower load and settling edges in addition to the
three exact retained source fixtures. Core's own comparator and source files
were not changed.

## Independent verification

- The original error was reproduced before the correction on all three exact
  retained fixtures and on a minimal constant-temperature capture.
- A 462-element signed/magnitude boundary comparison matches the independently
  calculated scalar math.isclose policy.
- All three full retained fixtures now return finite reports with matching
  temperature and sag counts. The recorded 655.28-degree sample is retained.
- A separate 1,000-capture before/after comparison (seed 20261014; 43,324 rows)
  had 61 guard rejections with the old asymmetric comparator and zero with the
  corrected comparator. Some boundary intervals were deliberately injected.
- All 939 previously accepted reports remained exactly equal. Inputs remained
  unchanged and all corrected reports serialized as strict finite JSON.

These are controlled software checks, not fault-detection or false-alarm rates.
The new campaign is distinct from the earlier 200-capture campaign; only its
three retained exact fixtures were re-executed here. Historical reports and their
source hashes were preserved.

The raw new summary is
batterylog_research/cora_boundary_campaign_results_20261014.json.
The executable native campaign and logs are retained in the separate Windows
batterylog-file-review-20261014-evidence directory. Source hashes identify the
exact helper tested; full native/hosted verification belongs to the current
draft's source identity.

## Recheck of the original prepared CORA branches

The same pinned P1/P2/P3 Cycle 229 WLTP CSVs were found under the existing
Windows validation directory and rerun after correction. Each has 16,365 rows;
all three input SHA-256 values matched the earlier report before and after.
Every returned branch fact matched the saved report exactly, including Core
statuses/counts and the endpoint-window/sag descriptions. P3 sag remains
NOT_EVALUATED with 1,046 evaluated samples and 68 incomplete intervals.

The separate evidence is cora_boundary_real_recheck_20261014.json. This is three
prepared branch observations at 16,365 unique times, not three independent
drives or a rerun of the historical 33 whole-cycle branches. Original raw
data and labels were not changed or copied into git.
