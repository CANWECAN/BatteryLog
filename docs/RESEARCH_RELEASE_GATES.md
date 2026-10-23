# Unified BatteryLog release gates

Current candidate: 20 October 2026. One Apache-2.0 distribution includes Core and
experimental workflows. See [licensing inventory](LICENSING.md).

Source integration may precede release with pending checks explicitly recorded.
Before a tagged public release: verify artifact/source/license consistency, complete
supported Linux/Windows and native GUI checks, preserve the 95% coverage gate,
and exercise installed base/CAN/MF4 workflows outside checkout. Keep exact source
and runner evidence. Independent software checks are not a hosted CI pass.

Experimental publication does not require every physical research question to be
closed. Corresponding physical diagnostic, safety, calibration or HIL claims do
require their own evidence. The unresolved source timing and reference limitations
below remain material to interpretation.

## Historical policy and evidence

The dated record below is retained for traceability. Its old private/evaluation
licensing and two-package distribution policy is superseded by LICENSING.md for
this candidate. Its engineering observations retain their original source scope.

### Research readiness gates at the historical revision

Status date: 2026-10-12. Scope: private `CANWECAN/BatteryLog-Research`
working branch. This is a **gate checklist**, not a certificate or approval
for a commercial product, BMS safety function, physical fault diagnosis or
distribution of the mixed-license Research code.

Current implementation and CI status are summarized in [CURRENT_STATE](../CURRENT_STATE.md).
The dated records below preserve their original qualification scope.

## Historical evidence and blockers at 12 October 2026

| Area | Evidence at the status date | Gate for progression |
| --- | --- | --- |
| Core analysis | Published v0.10.0; report provenance, deterministic checks, large log work | Reproduce on supported Python and OS matrix from clean artifacts |
| Research regressions | Focused tests and synthetic oracles; 161 isolated tests passed on Python 3.13 at this baseline | All Research tests, Ruff/mypy, native Tk/MF4 checks and full CI must pass |
| CI | GitHub Actions workflow stored only under `ci-templates/ci.yml`; no private-mirror workflow run | Enable with authorized `workflow` scope and require green Linux/Windows checks |
| Distribution | Mixed public Apache Core and separately licensed new private code | Explicit legal/provenance approval, clean Core artifacts and Research distribution agreement |
| Fault accuracy | Event-level synthetic cases; NO independent labeled true-fault series | Test representative synchronized data with independent event labels and capture negative cases |
| Acquisition | Existing CORA dataset has asynchronous/ZOH sampling; not synchronized fault truth | Verify channel timing, topology, time basis, units and source provenance before step-model claims |
| Operator UX | GUI demo, CLI/HTML/JSON, batch mode | Independent engineer cold-start walkthrough and documented failure/recovery |
| Operational assurance | Input/config hashes and deterministic JSON | Release rollback, dependency risk review, support ownership, changelog, retention policy |

### 2026-10-12 discovery: source-distribution disclosure risk

The private repository's existing `MANIFEST.in` recursively includes `tests`
and `docs`, so a source distribution can include newly private tests and
Research notes despite the `pyproject.toml` wheel discovery rule limiting
packages to `batterylog`. An isolated setuptools build of the previous
recursive manifest reproduced the disclosure. The patched manifest preserves
published Core assets and excludes `batterylog_research/`,
`tests/test_research_*.py`, `tests/test_temperature_triage.py`,
`docs/RESEARCH_*.md` and Research root license/boundary notices.

This is **not** a full legal provenance audit or proof that every Research
snippet is excluded. A final artifact must be built from the full checkout,
inspected and reviewed **before** any real publication.

### Required artifact checks from a full authorized Research checkout

```sh
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy batterylog
python -m pip install build
python -m build --sdist --wheel
python scripts/validation/check_research_distribution.py dist/*.tar.gz dist/*.whl
```

Also install the built Core wheel into a fresh isolated environment and
exercise CLI, HTML/JSON schemas, input-inspection, configured event models,
CSV/MF4 optional dependencies and batch cancellation on Windows/Linux.
Run native Tk GUI tests under a real graphical session or `xvfb-run`.
No step should be reported as passed before its runner executes.
Do **not** distribute an integrated Research archive merely because the
technical boundary scan passes.

## Reproducible acquisition-timing risk

In a deterministic three-row test, every cell experiences the same
-200 mV physical step. Delayed row publication for 24 of 96 channels
produces **48 candidate observations** from the peer-relative observer
without any simulated cell fault. A single delayed channel generates
two candidates; the second can have zero reported current change.
An exact half-population split is marked ambiguous by the existing
majority rule, but smaller delayed groups can still pass that rule.

43 unique timing cases were characterized, expanded into 56 parameterized
regressions plus explicit edge tests. This is **acquisition artifact
sensitivity**, not an estimate of real-world false-positive incidence.
The observer stays Research-only until synchronized source timing is
proven; current-change metadata or median consensus alone is insufficient.

## Conditional milestones and proposed acceptance criteria

**Controlled pilot (3–6 weeks of dedicated engineering):**
- Green repeatable Linux/Windows regression matrix; zero known critical failures.
- Reproducible wheel/sdist checks, installed-package smoke, license boundary approval.
- Operator test on 10–30 representative logs and one unaffiliated engineering reviewer.
- Clearly label model limitations and all `NOT_EVALUATED` results.

**Near-enterprise engineering beta (2–4 months):**
- Two independent measurement families with independently checked acquisition
  metadata and reproducible source-to-output evidence.
- Measured error/unknown rates on both benign transients and labeled,
  deliberately constructed anomalous cases; thresholds from test plan.
- Supported clean install, documented resource ceilings, recoverable batch,
  versioned results, controlled change/review, vulnerability/dependency review.

**Operational institutional distribution (6–12 months):**
- Approved licensing and customer data handling, release governance,
  reproducible/signable binaries and source archives, SBOM/dependency review,
  maintained security channel, issue-response and support/rollback process.
- Application-specific V&V accepted by the adopting organization.
  No inference of regulatory certification or physical safety approval.

Timing assumes access to suitable data, engineering effort and a CI runner.
If the real synchronized fault/benign datasets cannot be obtained, the
diagnostic-like models remain Research-only and the timeline must move.

**Architecture decision:** preserve opt-in Core validation and avoid
adding UI wizards, heuristic fault labels or models without evidence.
Priority is reproducibility, artifact boundaries and field validation.

## Cloud-only release-boundary validation — 2026-10-12

**Public Core release identity:** the approved published
`CANWECAN/BatteryLog` tag `v0.10.0` points to commit
`ad051793a9d3b72af8a5647234ea968bd4387b18`.
The public GitHub release currently exposes exact SHA-256 digests:

| Public asset | Approved SHA-256 |
| --- | --- |
| `batterylog-0.10.0-py3-none-any.whl` | `5ccef6874811c955f3a2d2c082113d95a6afd1c1b2349b1a0ebcad619fcaff41` |
| `batterylog-0.10.0.tar.gz` | `d417d7ba44a324fbb890114230b60678d1db014f8a9bbef329f808c89cdbb0ab` |

`scripts/validation/check_approved_core_release.py` accepts **only**
these exact filenames with byte-for-byte matching hashes. Any new
Research-built archive, even one deliberately renamed as the public
release, is rejected unless it is identical to the approved artifact.
This is an exact known-release identity gate, **not a signature or
approval of v0.11**, and cannot substitute for code review.

Run on copies of the official published assets:

    python scripts/validation/check_approved_core_release.py \
      batterylog-0.10.0-py3-none-any.whl batterylog-0.10.0.tar.gz

Also run the archive-scanning gate on any **proposed** new build:

    python scripts/validation/check_research_distribution.py dist/*.whl dist/*.tar.gz

The second gate rejects known Research member paths at any nesting
depth, malformed traversal paths, Windows backslash path ambiguity
and symlinks in the distributed archives. It is not a general
positive-source allowlist, and cannot catch private content secretly
embedded in ordinary Core filenames or generated metadata.
Consequently **an archive scan passing is necessary but insufficient
for distributing an integrated Research checkout**.

The current private Research tree has 106 blob-identical files, 30
changed existing files and 68 new files compared with the public
v0.10.0 tag (the public tag contains 137 tracked files). This is
not a Core v0.10.0 equivalent build, regardless of the result of the
Research-name archive exclusions.

Cloud-local regression executed in Python 3.13: 118 focused tests
passed (87 voltage-observer tests retained from the previously
exported review plus 31 approval and archive-hardening tests).
The two newly committed test files constitute **31/31** of this
run. The full private Research CI, built-artifact e2e verification,
Windows/Tk checks and real fault-labeled data tests remain
**not executed**. The real official release assets were not present
for a SHA-256 comparison in this cloud workspace: the pinned hashes
were read from GitHub release metadata, while acceptance/rejection
behavior was unit-tested with synthetic artifacts.

**Approval rule:** until a future independently reviewed Core version
and separate Research distribution agreement are explicitly approved,
do not distribute newly built mixed-license Research code as Core.

## Private Research CI activation boundary (2026-10-12)

The dormant `ci-templates/ci.yml` has now been adapted for private
Research validation. It monitors `main`, `research/dev` and `audit/**`
plus pull requests, runs the existing Linux/Windows/MF4 matrix, and
checks created `.whl` and `.tar.gz` artifacts for known private paths
**before** artifact upload.

Automatic tagged-release triggers, the tag-version release check,
and the entire GitHub Release publishing job have been removed from
the private template. The template has only read-only repository
permissions. It is **not** an active workflow; GitHub Actions can run
it only after an authorized owner installs it under `.github/workflows/`
with appropriate workflow permissions.

The tests in `tests/test_research_ci_template.py` are static guards.
Passing them does not prove the workflow executed or the package is
safe to distribute. Actual CI must be enabled and run before any merge.
Distribution of an integrated mixed-license Research artifact remains
disallowed until independent approval of provenance and license terms.

## CI packaging consistency fix (2026-10-12)

The dormant Research CI's package job calls
`scripts/check_sdist_test_fixtures.py` after building an sdist.
The original checker insisted that **all** checkout test source files
be present in that distribution. This contradicted the deliberate
`MANIFEST.in` exclusions of private
`tests/test_research_*.py` and `tests/test_temperature_triage.py`.

The revised checker excludes only these known root-level Research
test paths from the *required Core corpus*. It continues to reject
missing or modified Core test modules, nested fixtures and golden
expected-result files. The private-path archive scanner runs
separately and continues to reject unintended Research disclosure.

An isolated real setuptools sdist fixture was rebuilt and the
**old and new verifier were run against the exact same archive**:
old verification failed on an intentionally excluded Research
test; the corrected verifier passed. This does not establish that
the entire private Research source tree packages cleanly or passes CI.

## Private internal notes and regression test naming — 2026-10-12

A further direct source-distribution reproduction found two more
unintended members under the original Research checkout packaging
rules: the internal `docs/BUG_HUNT_2026_10_08.md` file and a newly
authored, Research-only checker test that was named
`tests/test_sdist_research_boundary.py`. The latter did not match the
explicit Research test exclusion prefix.

The test is now `tests/test_research_sdist_boundary.py`, with its
contents unchanged. `MANIFEST.in` additionally excludes
`docs/BUG_HUNT_*.md`; the archive scanner independently blocks this
document pattern. Existing fixture tests now cover the omitted file
and verify normal Core tests and reference documentation are preserved.

A clean isolated setuptools sdist build verified the exclusion behavior
and the retained Core test corpus verifier. These controls remain
path-pattern preflights only; **no distribution of this mixed-license
Research build is authorized**.
