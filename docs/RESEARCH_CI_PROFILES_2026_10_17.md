# Research CI profiles — 17 October 2026

Ordinary Research PRs run Plan CI, Linux Python 3.13 full pytest with real
desktop widgets, and Research CI gate. No failure-model/CAN test subset is
removed; Core coverage remains >=95%. The minimum runtime and complete Python
matrices are reserved for Full qualification.

| Change | Required verification |
| --- | --- |
| docs/*.md or *.rst and CURRENT_STATE only | Plan and gate; no heavy tests |
| Research code or ordinary tests | Linux full pytest + Ruff/mypy/pip check |
| Core runtime or schema | Linux + Windows + MF4 on Linux/Windows + packaging |
| Desktop tests | Linux + Windows |
| MF4 tests | Linux + MF4 on Linux/Windows |
| Distribution/installed-package tests, package docs/scripts/examples | Linux + packaging |
| CI policy/workflows/templates, dependencies/manifest/lockfiles, unknown paths or test fixtures | Full qualification |

Mixed changes take the union of requirements. Deleted paths count. Rename
detection is disabled in the diff so moving code into docs cannot hide removal.
Paths come from a local NUL-delimited three-dot Git diff using validated event
SHAs and complete checkout history; there is no GitHub changed-file API cap or
shell expansion of filenames. Diff/event errors fail the planner and gate.

Full retains the existing 12 verification jobs: four Linux Python versions,
minimum runtime, Windows and five MF4 combinations, plus packaging.
Plan and gate add two small jobs, for 14 total. Normal Research code has three
jobs, prose-only PRs two. Risk changes can require more than three jobs.

Full is selected for main/research/dev pushes, workflow_dispatch, or a PR with
the ci:full label. CI/dependency/unknown-path changes also select Full.
PR label changes re-evaluate the whole diff; unrelated labels can rerun CI,
but cannot replace a failed selected test with a no-op green gate.

Future operator commands after this workflow exists on the default branch:

```text
gh workflow run research-ci.yml --repo CANWECAN/BatteryLog-Research --ref <branch>
gh pr edit <number> --repo CANWECAN/BatteryLog-Research --add-label ci:full
```

The first command qualifies the selected branch. It is not assumed to satisfy
a required PR check. The label runs the Full profile in the actual PR context.
workflow_dispatch availability on an unmerged non-default-branch candidate is
not assumed. CI changes themselves force Full, so this candidate is qualified
through a draft PR.

Research CI gate requires successful planning and every selected job to return
success; a skipped/cancelled/failed selected job is an error. Jobs legitimately
not selected must be skipped. The gate runs with !cancelled() after failed or
skipped dependencies. A cancelled workflow remains non-successful.
No workflow-level paths-ignore is used, avoiding required checks stuck pending.

At inspection research/dev reports protected=false and no required checks.
Ruleset lookup returned a plan-related 403. Repository settings are not changed.
If branch protection is enabled later, require the stable Research CI gate
context and verify its PR behavior before replacing existing requirements.

No Core application behavior, thresholds, dependencies, public Core repository,
release permissions or licensing are changed. No automatic release/tag trigger.
The existing private artifact and distribution exclusion checks remain.
Measured billing savings and sub-five-minute feedback are goals, not results.

Official sources:
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
https://docs.github.com/en/actions/reference/workflows-and-actions/expressions
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow
