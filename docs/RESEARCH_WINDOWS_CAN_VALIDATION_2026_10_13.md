# Native Windows/Tk and offline CAN validation — 2026-10-13

Baseline: `fcc8b382612cd3afe825b4aa6f3ff7e42875a7bb` plus the two portability edits
identified in the retained JSON evidence. Private branch:
`audit/cloud-balancing-spread-20261012`.

## Outcome and actual defect

Remote ping and file/terminal operations recovered after the earlier transport
failures. Existing Windows checkouts were old and clean. The current private
Research branch was cloned into a new isolated directory and its HEAD verified;
existing checkouts and their environments were not updated.

The first full Windows collection found an actual Research portability defect:
`field_stress.py` imported Unix-only `resource` at module load time. Both its own
tests and `field_episode_review.py` therefore failed to import on Windows.

Removed that unconditional import and centralized the three memory-metric calls
in `peak_rss_mib()`. It preserves the existing Linux process-lifetime peak RSS
conversion from KiB to MiB. On other platforms it returns JSON **null**, meaning
unavailable; it does not substitute zero, current memory or an invented peak.
Battery calculations, source handling, thresholds and statuses are unchanged.
Two contract tests cover missing Windows resource and preserved Linux conversion.
Actual Windows module import and full collection passed after the change.

## Verified runs

| Run | Result |
| --- | --- |
| Initial native desktop/batch subset | 159 passed / 1 POSIX-only skip, 52.73 s |
| Final Windows full suite | **2,514 passed / 4 skipped / 9 warnings, 176.61 s** |
| Core `batterylog` statement coverage | **96.67224780242779%**, above the 95% gate |
| Supplemental distribution-boundary file | **3 passed / 0 skipped, 1.87 s** |
| Final Linux full regression | **2,323 passed / 46 skipped / 9 warnings, 92.52 s** |
| Focused field/episode regressions on Linux | 10 passed |
| Whole-tree Ruff check/format | Passed on Linux and Windows |
| Windows mypy | Passed, 48 production source files |
| Isolated environment `pip check` | Passed |

Windows full suite used `BATTERYLOG_REQUIRE_DESKTOP_TESTS=1`, `--capture=sys`,
`--cov=batterylog --cov-report=term-missing --cov-fail-under=95`, JSON coverage
and JUnit evidence. System-level capture follows the dormant Windows CI template
and avoids the previously observed Tcl/file-descriptor-capture problem. Coverage
applies to the production `batterylog` package, not all Research code.

The full Windows run's four skips were a Linux `/proc` memory test, a POSIX signal
escalation test, and two source-distribution fixture tests whose optional
setuptools backend was initially absent. Installed setuptools 82.0.1 in the
isolated environment and reran that distribution test file: all three tests
passed, including both previously skipped cases. This is a supplemental run,
not a claim that the full suite was rerun with only two skips. The warnings are
the existing deliberately injected numerical-overflow probes.

The initial desktop subset used the existing full-build environment with NumPy
2.5.3/Pandas 3.0.6. The final full suite used a new environment with Python
3.13.14, NumPy 2.3.5, Pandas 2.2.3, pytest 9.1.1, pytest-cov 7.1.0, Hypothesis
6.169.0, cantools 44.2.1, canmatrix 1.2, python-can 4.6.1 and asammdf 8.8.27.
The native Tk smoke returned patchlevel 8.6.15. Full details are in the summary.
Installing the optional MF4 backend enables additional parametrized cases, so
Windows and cloud test counts are not directly interchangeable.

The first ad hoc strict mypy invocation lacked external type stubs. Final mypy
used the template's `--follow-imports=silent --ignore-missing-imports` flags and
installed `types-PyYAML==6.0.12.20260906`. The `[dev]` extra alone did not supply
that stub in this isolated installation. A future CI activation must reproduce
the intended type-check setup; no error-suppression config or dependency metadata
was changed as part of this portability fix. Research CI remains dormant.

## Real CAN recordings on Windows

Fetched the same immutable source snapshots with the existing pinned identities;
all source bytes/SHA-256 values were verified before use. Raw GPL captures and
community DBCs remain outside the repository in a separate data directory.

The second-vehicle campaign reviewed **317,435 EX30/BMW records**, compared
**76,005 dual-decoder values** and **17,995 separate byte-reference values**.
Its complete decoded JSON structure exactly equals the prior cloud summary.
This preserves the source blockers: EX30 lacks time/type/bus metadata and complete
multiplex definitions, while BMW has malformed IDs and unverified validity/time
semantics. Both remain ineligible for canonical analysis.

The first Model 3 campaign rechecked **118,053 raw frames**, independent decoders,
manual byte arithmetic, hostile mutations and the native BatteryLog bridge.
All independent/reference/hostile summaries and the compared native-result
fields match the cloud. Whole-frame and chunk sizes **1, 7, 65,536** agree.
The six anchor rows still yield **5 analyzed / 1 excluded**, **FAIL** due to
missing initial temperatures and **zero configured engineering-threshold events**.
That FAIL is a data-quality observation, not a measured physical battery fault.
Serialized files may have platform-specific line endings; comparison is of
the declared JSON structures/result fields, not all platform metadata bytes.

## Evidence and limits

`batterylog_research/windows_can_summary_20261013.json` retains the JUnit counts,
exact coverage totals, versions, skip reasons, full-log SHA-256 and tested patch
identities. Windows source and tests matched the Linux-tested bytes exactly:

| Path | Git blob identity |
| --- | --- |
| `batterylog_research/field_stress.py` | `94069906526aaca21f74f4fc5e439c951797971c` |
| `tests/test_research_field_stress.py` | `d2c9246469cf4b8360e58aafa3c158adb29d0c94` |

This closes a bounded native Windows/Tk and offline CAN verification gap. It
does not validate live adapter capture, reconnect/long recording, acquisition
synchronization, CAN FD/ISO-TP, application counters/CRC, HIL or physical fault
labels. No production algorithm/dependency/schema, license, public publication,
workflow activation, release or merge changed.
