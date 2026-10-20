# Private Research integration and hosted CI — 2026-10-13

Integration candidate: [draft PR #2](https://github.com/CANWECAN/BatteryLog-Research/pull/2),
`audit/cloud-balancing-spread-20261012` to private `research/dev`.
Verified source commit: `7b032af9193f1286b8cd95851b346ca2cb043cbb`.
[Successful hosted run](https://github.com/CANWECAN/BatteryLog-Research/actions/runs/38430587468):
**12/12 jobs passed**.

## What changed

The private mirror had a dormant template and no executing workflow. The active
`.github/workflows/research-ci.yml` now matches the reviewed template and runs on
working-branch pushes and PRs. It includes standalone Research CAN dependencies,
types-PyYAML and setuptools so the intended contracts/type checks/fixture builds
actually execute. mypy/Ruff versions match the prior verified tools; production
dependency metadata is unchanged. Official Actions v7 commit identities are pinned.

Jobs have contents-read permission, a 20-minute limit and same-branch concurrency.
The initial push run was cancelled when the PR run superseded it; cancellation is
not counted as a successful validation. There are no tag/release triggers or
public publishing jobs. Verification distributions are stored as a private Actions
artifact after the known-path scan and outside-checkout installation tests.

The new draft tracks the actual tested cloud/CAN branch, including the earlier
normalization, evidence and installation fixes. PR #1 stays open on its old head;
it is not the current integration candidate. This preparation does not merge
either PR or move public Core. Reviewed the changed production paths for ordered
strict diagnostics, canonical/state-name conflicts, deadline/event sequencing,
conditional balancing-spread reuse and GUI payload/onboarding behavior; no new
blocking issue was found in that scoped self-review. This is not an independent
external engineering or physical calibration review.

## Actual hosted results

| Job | Pytest result | Core statement coverage |
| --- | --- | ---: |
| Linux 3.11 | 2,373 passed / 2 skipped / 9 warnings | 96.23% |
| Linux 3.12 | 2,373 passed / 2 skipped / 9 warnings | 96.23% |
| Linux 3.13 | 2,373 passed / 2 skipped / 9 warnings | 96.23% |
| Linux 3.14 | 2,373 passed / 2 skipped / 9 warnings | 96.02% |
| Minimum runtime, Python 3.11 | 2,373 passed / 2 skipped / 10 warnings | 96.23% |
| Hosted Windows 3.13 | 2,371 passed / 4 skipped / 9 warnings | 96.21% |
| MF4 Linux 3.11–3.14, four jobs | 175 passed in each job | Dedicated backend subset |
| MF4 Windows 3.13 | 175 passed | Dedicated backend subset |
| Package | Build, path scan, source-test corpus, strict Twine and installed base/MF4 smoke checks passed | Not a coverage job |

Both the Linux and Windows local CI/CAN contract subsets passed **99 tests** before
activation. Hosted full-suite jobs install the pinned CAN decoder dependencies and
require real desktop tests; Linux uses Xvfb and Windows uses system-level capture.
Linux full-suite skips are the optional actual MF4 cases; separate jobs test that
backend with it installed. Windows adds the Linux `/proc` and POSIX escalation
skips. The nine warnings are deliberate numerical-overflow probes; the minimum
runtime adds Pandas 2.2.0's PyArrow deprecation warning. No failure was suppressed.
Coverage applies to `batterylog`, not all Research modules or physical scenarios.

The verified artifact is `private-research-verification-distributions`, ID
`11830244599`, 642,531 bytes, GitHub-reported archive digest
`sha256:b81a7ebd83dc47a6cccf9787ee7d1a6fad31dbddc25b857cb3eeac88422c4f69`.
It is a private verification build, not an approved Core v0.10.0 release or a
licensed integrated Research distribution. Path exclusions do not replace a
per-file provenance/licensing review.

## Decision boundary

The current private checkpoint has actual hosted verification and can proceed
to human review for integration. PR #2 remains draft and unmerged. General BMS
support, physical cell/time/validity semantics, live adapter/HIL, long capture,
counter/CRC and CAN FD/ISO-TP validation remain separate gates.

The subsequent documentation/evidence commit triggers a fresh CI run. Its live
status is linked from PR #2; this report preserves the verified source run above
rather than rewriting a historical run to refer to a later SHA.
