# Hardware-free roadmap - 17 October 2026

> Historical record: licensing and package descriptions below refer to the recorded
> revision. The current unified Apache-2.0 package is defined in [LICENSING.md](LICENSING.md).
> Engineering evidence and qualification limits retain their original scope.

This roadmap covers software qualification without a physical adapter. Its
items do not establish physical precharge reference/capture acceptance. Adapter
capture remains deferred pending hardware.

| Item | Work | Completion criterion | Current checkpoint |
| --- | --- | --- | --- |
| H1 | Measure Research operational coverage separately | Select scope, measure statements/branches, prioritize material missing behavior | Complete for six initial modules; eight Decimal clock rejection regressions added; remaining older CAN guards listed in coverage evidence |
| H2 | Ordered file-based CAN replay | Preserve exact parsed time, source order, identifier type and payload; pause/stop/EOF are explicit | Complete in pull-based software scope; 118,053 pinned real frames independently compared twice |
| H3 | Simulated recording lifecycle | Bound queue; account for loss, interruption and writer failure; prevent false completion | Complete in single-owner software scope; 53 regressions plus 600 independent batch scenarios and 500k stress |
| H4 | Targeted decoder/profile fault injection | Independent expected outcomes for malformed payload, profile, signedness, bus and multiplex cases | Complete for selected CAN preparation scope: 27 new profile/decoder/source-mutation cases, 155 targeted passes; combined statement/branch coverage 94.84%; earlier payload/signedness/bus/multiplex regressions retained |
| H5 | Sampling and channel-age sensitivity | Identify when prepared inputs cannot support a comparison | Authored scope complete: 576 age/phase/period/source-order cases and 15 new checks; measured held-row derivative and missed-pulse examples; no physical calibration |
| H6 | Bound remaining dataset qualification | Inspect small OSF/Parquet schema samples and acquisition/reference evidence | Bounded pass done: OSF API 200, 74,232 archive range bytes and two actual CSV headers inspected; physical context and Parquet schema remain explicit open dependencies |
| H7 | Thin common operator workflow | Supported preparation/review/output stages runnable without manual script sequencing | Source-tree CAN preparation/Core HTML+JSON and strict precharge review share one command; source/age/coverage evidence retained; fixed-source acceptance recorded separately |
| H8 | Readable precharge HTML report | Curves, declared bounds, gaps and source-linked examples distinguish incomplete coverage from departure | Implemented in the source-tree operator: self-contained current/gap SVGs, exact source links, coverage and missingness; 21 new regressions and browser layout checks |
| H9 | Engineer pilot package | Permitted examples, expected results, instructions and review questions work independently | Alpha packaging brought forward for publication priority: separate allowlisted add-on, authored examples, three installed commands; external terms and actual distribution remain pending |
| H10 | Final combined technical review | Appropriate native/hosted checks and exact-source evidence with current state/docs | Per-period checks completed for H1-H3; full roadmap closure remains later |

## H1-H3 checkpoint

Source 83e37c34 has 12/12 hosted success. The Windows replay validation used
required real Tk and actual MF4. Its full suite: 3,000 passed, two skipped, nine existing warnings,
168.76 s, Core coverage 96.67%. Selected Research scope is measured separately;
the replay module reaches 98.96% combined statement/branch coverage including
six actual CLI invocations. This is software confidence, not physical validation.

Independent batch campaign: 600 cases, 96,224 offered frames, 43,013 intentional
overflow drops, zero outcome/record mismatches. Both complete Model 3 replays
(capacity one and 1,024) preserve all 118,053 frame fields and produce identical
22,582,719-byte journals. Raw source/derived files stay outside git.
500,000 authored frames: 4.913 s, peak process RSS 35.95 MiB, peak pending 32.
Pause/source failure/disk error tests do not imply real adapter/HIL qualification.

See RESEARCH_CAN_OFFLINE_REPLAY_2026_10_17.md and compact evidence
batterylog_research/can_offline_replay_validation_20261017.json.
Exact saved-head hosted closure is recorded in the corresponding draft PR.
