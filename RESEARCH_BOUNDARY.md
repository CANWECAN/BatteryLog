# BatteryLog experimental boundary

BatteryLog is one Apache-2.0 product. The `batterylog_research` namespace is
retained for experimental offline tools and source-review code. It is included
in the same batterylog wheel and source distribution, with no companion package
or separate evaluation license for this revision.

## Source and license history

The published v0.10.0 baseline is ad051793a9d3b72af8a5647234ea968bd4387b18.
Previously public PRs #115, #116 and #117 retain their existing Apache rights.
The owner selected a unified Apache-2.0 product on 19 October 2026. This candidate
replaces former proprietary notices for first-party experimental code while
preserving copyright, NOTICE and third-party terms. See [inventory](docs/LICENSING.md).

## Distribution

The root pyproject builds one distribution at 0.11.0.dev0. Base installation
includes Core, desktop interfaces, experimental precharge HTML and offline replay.
The optional [can] extra enables DBC-backed preparation/review. The root command
exposes `batterylog experimental can|precharge|replay`. Historical two-wheel
0.1.0a1/alpha2 candidates are retired.

First-party source, tests and authored examples remain in the sdist.
Raw third-party data/DBCs, internal BUG_HUNT notes and the retired evaluation
template are excluded. The original Model 3 MIT notice is retained both in
distribution metadata and in the installed experimental package.

## Engineering scope

Timing, topology, missingness and qualification limits remain applicable.
Held samples are not independent acquisitions. Precharge output records
observations, not a calibrated physical PASS or safety decision.
Software/package tests do not establish physical fault-detection accuracy.

The public development tree contains the reviewed source snapshot; the former
private repository history is not imported. Internal notes and retired evaluation
templates are not part of the public tree. Existing tag-only release controls are
retained, including full verification, matching versions and artifact checksums.
The last published release remains v0.10.0; development integration does not
establish current graphical-session or native Windows qualification.
