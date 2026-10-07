# Combined 0.11 development build — 2026-10-07

Review candidate: `build/0.11-desktop-failure-models`, [draft PR #117](https://github.com/CANWECAN/BatteryLog/pull/117).
Base: released v0.10.0/main `ad051793a9d3b72af8a5647234ea968bd4387b18`.
Application and Windows review-builder snapshot:
`24673ce256bebb5a5bfbcb5dd6b7fe8b0dc942f6`. The follow-up changes Windows pytest
capture and records this verification; it does not change the built application.

The candidate combines the desktop launcher from draft #115 with the opt-in models
from draft #116. The originals remain separate review drafts. This work publishes
no main merge, release or tag.

## Working behavior

The launcher accepts a model-only config-v7 YAML and preserves the CLI's PASS,
FAIL and NOT_EVALUATED outcomes. HTML and JSON retain result-v9 model evidence,
input/configuration hashes and the original pack/cell-sum rule. The launcher text
now describes configured validation rules, covering both legacy limits and models.

The five-model example produces six events: the existing pack/cell-sum mismatch
and one event for each new model outcome. The built-in **Try demo…** remains the
small five-sample example with two legacy violations. For the model example,
select `examples/failure_models_demo.csv` with `examples/failure_models.example.yaml`.

Cancellation, cleanup errors, responsive widget polling, report opening and
distinct output folders remain covered. Completed HTML/JSON are published together;
error/cancelled runs remove their owned partial output.

## Recorded verification

| Check | Result |
| --- | --- |
| Native Windows, Python 3.13.14, NumPy 2.5.3, pandas 3.0.6, PyYAML 6.0.3, asammdf 8.8.27 | 1,696 passed, 2 skipped; coverage 98.90% |
| Native Windows desktop test module, with required Tk and `--capture=sys` | 19 passed |
| Windows skips | Linux `/proc` benchmark and POSIX SIGTERM escalation; no display-dependent case skipped |
| Hosted Linux Python 3.11–3.14 at the application snapshot | Each 1,632 passed, 2 optional-MF4 module skips; coverage 98.26–98.37% |
| Hosted minimum runtime, NumPy 1.26.0 / pandas 2.2.0 / PyYAML 6.0 | 1,632 passed, 2 optional-MF4 module skips; coverage 98.37% |
| Hosted binary MF4 matrix, Linux Python 3.11–3.14 and Windows Python 3.13 | Passed, including `test_failure_models_mf4.py` |
| Ruff formatting/lint and package-wide mypy | Passed; 44 package source files |
| Review builder static checks | Ruff and mypy passed; builder also executed successfully on Windows |
| Wheel/sdist metadata and source fixture corpus | Built successfully; strict Twine and corpus checks passed |
| Fresh native Windows wheel and sdist installs outside checkout | Base and MF4 installed smoke checks passed for each distribution; pip check passed |
| Fresh installed desktop worker | Model-only PASS/FAIL/NOT_EVALUATED, result-v9 validation, service parity and report hashes passed |
| Fresh installed Tk window | Constructed, updated and closed successfully outside checkout |
| Native prepared model report | FAIL, schema 9, six events; HTML and JSON written successfully |
| Linux wheel / Python 3.11 minimum-runtime sdist outside checkout | Base smoke checks passed; optional MF4 checks passed after installing extras |
| Frozen result-v8 schema and golden corpus | Unmodified against main |

Hosted snapshot results are from [CI run #285](https://github.com/CANWECAN/BatteryLog/actions/runs/37660648567).
Its Windows job exposed the capture issue below. The follow-up requires the same
Windows desktop tests with Python-level capture. The PR's current commit checks
are the hosted gate for that follow-up.

The four overflow warnings come from existing numeric boundary tests. The minimum
runtime additionally emits pandas' existing optional-PyArrow warning. MF4 extras
may upgrade runtime dependencies; the minimum versions were verified before that
optional installation.

## Windows Tcl/Tk test capture

Creating fresh roots under pytest's default per-test file-descriptor capture caused
intermittent Tcl library-read errors in both the hosted Windows runner and the
native Windows machine. A native probe reproduced one failure among 150 test
windows; the same probe with `--capture=sys` passed all 150. Another 450 window
creations outside pytest passed. The full native suite with `--capture=sys` then
passed, including all desktop cases.

Windows CI now uses `--capture=sys` while keeping
`BATTERYLOG_REQUIRE_DESKTOP_TESTS=1`. A failure to initialize Tk still fails the job.
No automatic retry, xfail or desktop skip was added. Application launches and the
installed review-window check run outside pytest.

## Ready-to-open native build

The completed review folder on the authorized Windows machine is:

```text
C:\Users\berko\Berk-Automotive-Lab\products\BatteryLog-0.11.0.dev0-review-wxm6hc7t
```

Double-click `Start-BatteryLog.cmd` in that folder. The installed environment has
MF4 support, copied examples and a completed model report at
`results/failure-models/report.html`, with JSON beside it. `build.log` records the
fresh wheel and sdist checks. Keep the folder at its built location because the
virtual environments contain absolute paths.

Native distribution SHA-256 values for application snapshot `24673ce`:

```text
ee0e230ade45d2cee9279192c851d66c13c291026e14654b5f7b2a1883bd0529  batterylog-0.11.0.dev0-py3-none-any.whl
5ebf5b00c4c0cdb3162148e619d7b69e3b0c33a3e333c8149c3fc4982a5d579d  batterylog-0.11.0.dev0.tar.gz
```

The build can be recreated with `scripts/build_windows_review.py`; see
[desktop build instructions](DESKTOP_LAUNCHER.md). Later documentation-only builds
can produce different distribution hashes.

## Review scope

This is a Python-based local desktop review build. A standalone installer, batch
GUI, channel editor and embedded plot viewer remain outside this first launcher.
The CLI still provides normalization, inspection and batch workflows.

Model verification uses synthetic measurements, including real binary MF4 files.
Vehicle-data calibration remains unperformed. The formulas and observation limits
are in [FAILURE_MODELS.md](FAILURE_MODELS.md). The next manual review should cover
desktop usability, the model report's evidence, and parameters for an acquired log.
