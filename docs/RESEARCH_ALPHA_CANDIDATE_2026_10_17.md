# Research alpha candidate — 17 October 2026

> Historical record: licensing and package descriptions below refer to the recorded
> revision. The current unified Apache-2.0 package is defined in [LICENSING.md](LICENSING.md).
> Engineering evidence and qualification limits retain their original scope.

Candidate: `batterylog-research 0.1.0a1`, private offline evaluation scope.
Target integration branch: `research/dev`. Public Core remains frozen at v0.10.0.
This document prepares a candidate; it does not merge branches, publish a release,
grant external access, or execute the access-terms draft.

## Included work and provenance

The candidate starts at draft #18, a7d77d01f474f20bb2600a17e79bad7208bc47ff,
which includes the stacked #9–18 lineage and its ancestors. Draft #8 is a sibling.
Exactly these four nonconflicting paths were restored byte-for-byte from #8
(f94209379382570ff6b668815279601a4e81b862):
- batterylog_research/precharge_can_source_audit.py
- batterylog_research/precharge_can_source_audit_results_20261014.json
- docs/RESEARCH_PRECHARGE_CAN_SOURCE_ELIGIBILITY_2026_10_14.md
- tests/test_research_precharge_can_source_audit.py

The current CURRENT_STATE/work map supersede #8's older copies; they were not
replaced. This is content integration on an isolated candidate branch, not a
merge of #8's ancestry. Existing draft PRs remain open for owner review.

H4 adds 27 targeted negative cases: 18 invalid profiles rejected before stream
output, six corrupted/nonfinite decoder values with no published partial
directory and unchanged inputs, and three source/DBC/profile mutation cases
rejected before final publication. Targeted preparation/source-audit run:
155 passed, 2.09 seconds; can_prepare combined statement/branch coverage 94.84%
(277/292 statements; 127/134 branches). No decoder production change was needed.

## License and distribution map

| Material | License / boundary | Candidate handling |
| --- | --- | --- |
| Published Core v0.10.0 and previously public draft code | Existing Apache-2.0 permissions and notices remain | Root Core metadata stays Apache-2.0; separate companion build |
| Eight selected, explicitly marked private Research Python modules | Existing RESEARCH_LICENSE.md, all rights reserved | Separate batterylog-research distribution, LicenseRef-BatteryLog-Research |
| Two authored precharge examples | Same private Research evaluation scope | Included as software examples, never physical reference data |
| Third-party packages | Their own licenses | Declared dependencies; no source vendoring |
| Downloaded datasets and third-party DBCs | Original source terms | Excluded from both the Research add-on and pilot examples |
| RESEARCH_ACCESS_TERMS_DRAFT.md | Unexecuted template | No automatic access grant or binding agreement |

Selected modules: __init__, can_prepare, can_replay, can_capture_review,
can_multiplex_audit, precharge_curve_review, precharge_capture_review,
precharge_file_review. Every selected Python file already carries the explicit
Berk Ozfiliz all-rights-reserved notice. These paths are absent from both the
frozen public Core tree ad051793a9d3b72af8a5647234ea968bd4387b18 and the
previously public draft tree 310e4294ca7b57bf7d517bb6e5f8b68d7533120a.
Git provenance is evidence of repository history, not a substitute for ownership
confirmation or an executed license agreement.

The add-on depends on batterylog==0.11.0.dev0. The pilot therefore needs the
separately supplied Apache companion wheel from this source checkout; the
public v0.10.0 package cannot satisfy this requirement. This does not release a
new public Core version. Retain LICENSE and NOTICE in the companion and add-on.
Do not relabel previously published Apache code as exclusively proprietary.
Do not add compulsory contribution/assignment obligations to Apache recipients.
Any such obligations for new Research access require an expressly accepted,
separate agreement.

## Build and acceptance

```text
python batterylog_research/packaging/build_candidate.py <new-external-staging-dir>
python -m build <staging-dir> --outdir <private-dist-dir>
python -m twine check --strict <private-dist-dir>/*
python batterylog_research/packaging/verify_candidate.py --artifacts <private-dist-dir>
```

Default staging refuses dirty source and existing destination directories.
BUILD_PROVENANCE.json embeds exact source revision and SHA-256 for each input.
The archive audit requires an exact allowlist, the proprietary license expression,
all three license/notice files, matching provenance, and the exact Core dependency.
Core's existing distribution exclusion check remains separate and unchanged.

Research CI additionally installs both add-on wheel and source distribution
with the local Core companion into fresh environments outside checkout.
Each install exercises all three actual console commands: precharge file review,
exact-clock replay, and DBC preparation on authored bytes. No raw third-party
source is needed. Artifacts remain private GitHub Actions artifacts.

## Merge and pilot decision

Candidate acceptance requires exact-source CI, native verification and review of
package contents, provenance and license metadata. The private Research add-on
and public Core distribution remain separate.

External pilot distribution additionally needs a named recipient, permitted use,
users/machines/sites, duration and an accepted written agreement. The existing
terms draft leaves material commercial/legal details open. No public PyPI upload
or release automation is enabled by this change.

Physical precharge steps 7–8 remain OPEN; adapter step 9 is deferred.
H5–H10 can follow the pilot rather than delaying an accurately scoped alpha.
Clean-source Core/add-on wheel and sdist builds, twine, allowlist/license/hash
audits and two fresh add-on installs pass on Windows. Each install passes all
three real console commands. Three deliberately corrupted archive variants
(extra data, Apache relabel and dirty provenance) all reject.
The initial full native run passed 3,042 tests and failed one CI/template parity
check; the omitted matching template was synchronized and all nine template
tests pass. Final full-suite and exact-head CI closure is recorded in draft #19
and the final report. Historical measurements are in
batterylog_research/research_alpha_validation_20261017.json.

References: Apache License 2.0, sections 2 and 4–5
(https://www.apache.org/licenses/LICENSE-2.0);
Apache licensing FAQ (https://www.apache.org/foundation/license-faq.html);
PEP 639 license-expression metadata (https://peps.python.org/pep-0639/).
