# Research capability and qualification map

> Historical record: licensing and package descriptions below refer to the recorded
> revision. The current unified Apache-2.0 package is defined in [LICENSING.md](LICENSING.md).
> Engineering evidence and qualification limits retain their original scope.

This map separates implemented software from the source evidence needed for a
physical interpretation. Validation results remain attached to their exact source
revisions in the linked notes; test totals from different environments are not combined.

| Capability | Implementation | Qualification requirement |
| --- | --- | --- |
| Temperature and sag characterization | Window and reference-eligibility studies | Source cadence, validity and acquisition context |
| Precharge curve/capture review | Single and multiple spans; declared reference bounds | Independently justified reference and measured current/voltage topology |
| Aligned CSV review | Explicit five-column input, context hash and bounded reads | Producer-authenticated alignment and phase semantics |
| Decimal clock handling | Exact CSV differences before binary64 conversion | Original logger units remain a producer requirement |
| BMW raw trace | Paired-source verification and source-indexed candidate values | Clock, channel mapping, validity and measurement path |
| CAN preparation | Explicit profile and raw-code policy; per-row age evidence | OEM signal semantics and suitability of selected channels |
| CAN replay/recording | Ordered files, bounded queue and loss/error accounting | Live-adapter and sustained hardware behavior unverified |
| Common file command | Preparation, supported analysis and staged output publication | Independent workflow usability review |
| Alpha packaging | Eight allowlisted modules, authored examples and three commands | Distribution/license terms and clean artifact verification |
| Precharge HTML | Source-tree plots, source links and explicit display bounds | Independent workflow/usability review and qualified physical input |

## Source qualification

Physical precharge review requires documented logger units; state/phase meaning;
pack and DC-link measurement nodes; current direction/path; validity and filtering;
acquisition alignment/uncertainty; and an independent, comparable normal reference.
A field name, DBC label or successful parser call does not establish these facts.

BMW's source audits preserve raw evidence without assuming seconds or manufacturing
an aligned capture. The inspected charging datasets remain candidates rather than
accepted physical references. Adapter capture is deferred pending hardware.

## Technical evidence

- [CORA temporal observations](RESEARCH_NATIVE_CORA_2026_10_14.md)
- [BMW clock provenance](RESEARCH_BMW_CLOCK_PROVENANCE_2026_10_14.md)
- [BMW signal contract](RESEARCH_BMW_MEASUREMENT_CONTRACT_2026_10_14.md)
- [BMW source trace](RESEARCH_BMW_RAW_SOURCE_TRACE_2026_10_14.md)
- [Precharge file interface](RESEARCH_PRECHARGE_FILE_REVIEW_2026_10_14.md)
- [Precharge reference-source review](RESEARCH_PRECHARGE_REFERENCE_EVIDENCE_2026_10_15.md)
- [CAN replay](RESEARCH_CAN_OFFLINE_REPLAY_2026_10_17.md)
- [Sampling/channel-age study](RESEARCH_CHANNEL_AGE_2026_10_17.md)
- [Dataset schema inspection](RESEARCH_DATASET_ACCESS_2026_10_17.md)
- [Common file command](RESEARCH_OPERATOR_2026_10_17.md)
- [Software roadmap](RESEARCH_HARDWARE_FREE_ROADMAP_2026_10_17.md)

## Integration boundaries

PR #19 consolidates the #18 lineage and four source-audit paths from sibling #8.
The common command and later sampling studies extend that source without changing
the alpha allowlist. Core and Research distributions retain separate contents and
metadata; see [the boundary](../RESEARCH_BOUNDARY.md).
