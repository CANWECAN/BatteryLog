# Research operator file workflow - 17 October 2026

> Historical record: licensing and package descriptions below refer to the recorded
> revision. The current unified Apache-2.0 package is defined in [LICENSING.md](LICENSING.md).
> Engineering evidence and qualification limits retain their original scope.

H7 adds a thin common source-tree command on top of existing Research preparation,
precharge review and the Core AnalysisService. It does not change Core algorithms,
thresholds, result schemas or the frozen alpha #19 package.

## Two supported paths

Run from this Research checkout, using the environment with Core dependencies;
the CAN path additionally needs cantools. Choose an existing output parent and
a new output directory. Open index.html first.

```powershell
python -m batterylog_research.operator can --log capture.log --dbc source.dbc --profile profile.json --config limits.yaml --output-dir reviews\can-001
python -m batterylog_research.operator precharge --csv aligned.csv --context context.json --output-dir reviews\precharge-001
```

The CAN path preserves the strict classic-CAN/profile contract. It writes
prepared/canonical.csv, prepared/alignment.jsonl, prepared/preparation.json,
Core result.json and report.html, plus index.html and manifest.json.
No signal aliases, units, thresholds, missing samples or precharge phase are inferred.
The YAML config is mandatory; a config with no applicable limits retains Core
NOT_EVALUATED rather than inventing an acceptance decision.

The precharge path uses the existing exact ordered aligned CSV and hash-bound
context declaration. It writes review.json, index.html and manifest.json.
OBSERVATIONS_RECORDED means the review completed; it is not a PASS decision.
Precharge curve/band HTML remains H8, and the physical/reference limitations
of the existing observer remain in force.

## H5 interpretation boundary

Prepared CAN context is bounded previous-sample association, not simultaneous
acquisition. Per-row source lines, sample ages, expired values and preparation
limits remain inspectable. H5 showed held rows can create misleading derivatives
or miss short pulses. This operator path therefore rejects temporal failure
models, custom signal remapping of its canonical output, and pack/cell-sum
comparison on unqualified brick groups. It does not silently strip those options
or change the Core engine. Source-clock analysis and complete-stack qualification
are separate work.

## Completion and provenance

The manifest retains input byte hashes, byte lengths, names, stat metadata,
implementation hashes, effective CAN config and hashes of all output files
except the manifest itself. Hashes provide consistency evidence, not a signature
or authenticated hardware provenance. Core HTML identifies the canonical CSV
and config; the manifest links those outputs back to log/DBC/profile hashes.

Each path stages its products in the destination filesystem, verifies source
hashes against both consumed-input reports and current paths, and publishes the
directory only after successful completion. Input/report exceptions and normal
Python interruption clean up staging. Existing output paths are rejected before
work and again before publication. This is a single-owner file workflow; it is
not a multi-process publisher or a crash-recovery recording journal.

| CLI exit | Meaning |
| --- | --- |
| 0 | CAN Core PASS, or precharge observations successfully recorded |
| 1 | CAN Core FAIL; complete review remains available |
| 2 | Argument/usage error |
| 3 | CAN Core NOT_EVALUATED; complete review remains available |
| 4 | Input, dependency, analysis or output error; no new published review |

An OS/process kill can leave a hidden staging directory; its presence is not
a completed review. Raw CAN logs and DBCs are not copied into the output or git.
The source-tree operator is intentionally excluded from the frozen 0.1.0a1
allowlist. H9 must qualify a new package candidate before distributing it.

## Validation

Tests compare the complete result with a direct Core service call, verify raw-byte
values and age expiry, exercise CLI exit codes, preserve existing outputs, reject
input mutation and inject preparation, analysis, HTML, manifest and interruption
failures.

Native source: `10b1a8527bdf2fdf68ebdcdfe1b0405896ac6292`.

| Environment | Result | Coverage |
| --- | --- | --- |
| Windows Python 3.13.14, required real Tk and actual MF4 | 3,151 passed, two skipped, nine existing warnings; 189.67 s | Core 96.67% |
| Hosted Linux Python 3.13, Fast profile | 3,002 passed, two skipped, nine existing warnings; 144.84 s | Core 96.23% |

Ruff, formatting, Core mypy, dependency and whitespace checks passed. The 23
operator regressions pass. In-process operator statement/branch coverage is 77%;
independent CLI subprocesses are excluded from that counter.

[Fast verification](https://github.com/CANWECAN/BatteryLog-Research/actions/runs/39067145103)
passed planning, Linux tests and the final gate; four unselected heavy families
were skipped. Later acceptance documentation retains the tested source bytes.
GitHub's synthetic merge checkout is a test artifact rather than branch integration.

Reproduce the focused regressions with:

```sh
python -m pytest -q tests/test_research_operator.py
```

The results establish software behavior. Physical precharge acceptance and adapter
qualification require separate evidence.
