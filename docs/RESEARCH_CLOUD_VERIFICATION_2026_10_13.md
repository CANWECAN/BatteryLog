# Research cloud verification — 2026-10-13

Working branch: `audit/cloud-balancing-spread-20261012`.
Baseline: `5872adc77ad507f9b79b1caa7dcd9c52b3694434`.

## Executed verification

The cloud source snapshot contained all 209 repository text files, each verified
against its Git blob SHA before modification. The report-preview PNG was not
needed or fetched. This was a source-test run, not a genuine full-tree package
build or installed-artifact check.

| Check | Observed result |
| --- | --- |
| Initial focused model/streaming/CSV regression | 290 passed in 72.39 s |
| New chunk-boundary suite | 25 passed in 13.22 s |
| Final entire collected pytest suite | 2,219 passed, 46 skipped, 0 failures/errors in 147.89 s |
| Focused triage/desktop-worker/distribution follow-up | 106 passed in 21.58 s |
| Ruff check over the whole repository | Passed |
| Ruff format check over the whole repository | Passed |
| mypy 1.19.1, CI flags, `batterylog` | No issues in 48 source files |
| GitHub Actions history | Still zero workflow runs |

The JUnit accounting was 2,265 collected entries with 0 errors, 0 failures and
46 skips. Skips: 44 GUI tests required a display; the two collection skips
were the optional MF4 integration/model modules. Nine NumPy overflow warnings
came from intentional arithmetic-overflow rejection tests; those tests passed.

Runtime: Python 3.12.14, NumPy 2.3.5, pandas 2.2.3, PyYAML 6.0.3,
jsonschema 4.26.0, pytest 9.1.1, Hypothesis 6.169.0, Ruff 0.17.0.
The newly installed mypy 2.4.0 crashed before checking project code because
psutil could not resolve this host's process PID. Retrying with zero worker
processes did not avoid its parser thread-probe crash. The supported older
mypy 1.19.1 was used without modifying third-party tools or disabling project
checks. A normal CI host should still exercise its selected mypy version.

## Chunk-boundary evidence

`tests/test_research_chunk_invariance.py` enables all seven configured failure
models together (balancing emits two evaluation codes, so eight evaluations).
It compares complete result-v9 dictionaries, including statuses, sample
accounting, source evidence, event times, peaks and measured values.

- 24 cases: boundaries 6, 7, 8, 13, 14, 15 under clean samples, a duplicate
  timestamp, a time gap above the configured limit, and an excluded invalid
  temperature sample.
- Each small case compares the full-frame result with chunks of 1, 7, 1,024
  and 65,536 rows. A large chunk on a small case intentionally covers the
  single-chunk path; it does not demonstrate crossing that large boundary.
- One 65,542-row case has active model events spanning the actual 65,536-row
  boundary; it compares 1,024- and 65,536-row streaming partitions with the
  full-frame result. It independently asserts that the sustained imbalance
  peak stays at 65,536 s.
- Every compared payload receives semantic validation; the full-frame reference
  also receives result-v9 JSON Schema validation.
- No result differences were found in these cases. This is bounded synthetic
  coverage, not proof for arbitrary data or a physical fault-detection metric.

## Resolved verification blockers

The pre-existing temperature-triage integration test required the literal text
`validation_status` in an error. Tampering a genuine FAIL result to PASS is
already rejected by JSON Schema because violations remain. The verbose
schema diagnostic instead names the nonempty violations array. Rejection
behavior was correct; the test's message assumption was wrong.

The corrected test explicitly covers both structural rejection of the tampered
status and semantic rejection of a schema-valid row-count inconsistency. It
asserts that invalid input never reaches triage, stdout remains empty and the
input file remains byte-identical.

Additional check-only cleanup:
- Type the desktop batch display's existing status-name tuple as `BatchStatus`.
  The previously inferred `str` iterator failed mypy's Literal argument check.
- Remove one unused test import and format existing cloud-added tests/helpers.
- Preserve the Research helpers' ValueError contract with narrow TRY004 comments.
- Combine the distribution scanner's equivalent string-prefix checks into one
  tuple-based `startswith` call.

Thirteen formatting/comment-only edits were independently checked for identical
Python ASTs. No analysis threshold, numerical comparison, status decision,
event algorithm, schema, release policy or license changed.

## Remaining gates

- Native Windows and Linux GUI/Tk checks, optional actual MF4 suite.
- The complete Python version/minimum-dependency matrix and CI coverage threshold.
- Enable the dormant Research CI workflow only with the required workflow-scoped
  authorization; this run did not activate it.
- Genuine full-tree wheel/sdist builds, artifact scans and clean installed-package
  checks. Source-test success does not approve a Core repackage.
- Synchronized, independently labeled real BMS data and source timing/topology
  evidence before making physical diagnostic claims.

Reproduce in a Research checkout with its development dependencies:

```bash
python -m pytest -q tests/test_research_chunk_invariance.py
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy --follow-imports=silent --ignore-missing-imports batterylog
```
