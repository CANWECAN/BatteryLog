# Source-bound interpretation review

The opt-in review analyzes one captured CSV/MDF/MF4 file and publishes a new
directory containing the unchanged engineering result, declared context,
effective analysis settings and separate interpretation JSON/HTML. It does not
estimate SOC differences, identify faulty parallel branches or distinguish
sensor faults from cell faults. All three physical claims remain
`NOT_EVALUATED`, independently of engineering `PASS`, `FAIL` or `NOT_EVALUATED`.

## CLI

```sh
batterylog measurement.csv --interpret \
  --measurement-context context.json --imbalance-limit-v 0.05 \
  --output-dir results/interpretation-001
```

The output directory must be new. Open `interpretation.html` for observations,
physical limits, missing context and evidence links. `--measurement-context` is
optional: omitting it explicitly reports that no context was supplied. A missing
file or invalid context is an error, rather than silently becoming absent context.
Use the strict [context format](MEASUREMENT_CONTEXT.md).

Stdout remains the original engineering JSON. Stderr separately states that
physical interpretation is `NOT_EVALUATED`. Existing YAML configuration and CLI
limit overrides retain their normal precedence. Exit codes describe engineering
acceptance or a workflow error; physical `NOT_EVALUATED` never hides an
engineering violation and never changes engineering PASS into a diagnosis.

| Exit | Meaning |
| --- | --- |
| 0 | Configured engineering checks passed; physical claims remain unevaluated. |
| 1 | Engineering FAIL, including applicable data-quality/model failures. |
| 3 | Engineering NOT_EVALUATED. |
| 2 | Invalid option combination or missing required option. |
| 4 | Input/context/configuration/analysis/output error; no successful JSON is emitted. |

`--interpret` is exclusive with batch, inspection, normalization and recording
audit. It requires `--output-dir` and rejects `--report`, `--json-out` and
`--recursive`, because the new directory is published as one bundle.
`--measurement-context` requires `--interpret`. Ordinary analysis is unchanged
when the new mode is unused. Desktop and batch integration are outside this API.

## Python API

```python
from batterylog import ValidationConfig, ValidationLimits
from batterylog.interpretation_review import review_measurement

bundle = review_measurement(
    "measurement.csv",
    "results/interpretation-001",
    context_path="context.json",  # or omit it
    config=ValidationConfig(limits=ValidationLimits(imbalance_max_v=0.05)),
)
assert bundle.engineering_status in {"PASS", "FAIL", "NOT_EVALUATED"}
assert bundle.to_dict()["physical_interpretation_status"] == "NOT_EVALUATED"
```

The frozen return value holds the published directory and exact result/review
JSON texts. `to_dict()` returns a fresh detached copy. The API accepts effective
`ValidationConfig` values, not a precomputed result or arbitrary analysis service.
It runs the existing engine on its own captured source, avoiding attachment of a
previous result to an unrelated file. It raises errors; process exit handling
belongs to the CLI.

## Files and version-1 JSON contract

| File | Content |
| --- | --- |
| `result.json` | Exact UTF-8 output of the existing result renderer, including its newline and frozen result-v8/v9 fields. |
| `effective-config.json` | Canonical JSON of the effective configuration actually supplied to analysis. |
| `context.json` | Exact original context bytes, including BOM/whitespace; absent if context was omitted. |
| `interpretation.json` | Versioned source/result/context/settings association, observations and three independent physical claim limits. |
| `interpretation.html` | Self-contained view of the same observation/status/reason payload, with relative links to the evidence files. |

`interpretation.json` has `interpretation_review_schema_version: 1` and scope
`source_bound_interpretation_limits`. Its engineering status is copied from the
engine. `physical_interpretation_status` is `NOT_EVALUATED`, `diagnostic_claim`
and `measurement_properties_verified` are false. `context_evidence_level` is
`DECLARED` or `NOT_SUPPLIED`.

`binding.source` identifies the original basename, exact-byte SHA-256 and byte
count. `binding.result`, `binding.effective_config` and optional `binding.context`
identify relative artifact paths, SHA-256 and byte counts. Context also retains
its original basename. `binding.kind` is
`same_snapshot_analysis_and_exact_artifact_hashes`; its
`source_channel_mapping_verified` is false. Hashes are integrity references, not
signatures or authentication of declarations.

`observations` copies the peak voltage spread, configured spread limit,
evaluated rules, original violation/data-quality events and optional v9 failure
model report. It applies no new thresholds or physical interpretation.
`claims` contains the [voltage context review](VOLTAGE_SPREAD_CONTEXT.md),
[parallel context review](PARALLEL_BRANCH_CONTEXT.md) and the unchanged
sensor/cell limit from the [initial contract](INTERPRETATION_CONTRACT.md).

The original measurement is not copied into the bundle. Raw YAML is not retained
or hash-bound: effective settings record what the engine used, including CLI
overrides. A metadata/source hash association does not prove that named channels
exist, belong to the declared cells, use the declared units or were acquired at
the declared times. This workflow does not certify those measurement properties.

## Publication and presentation

Source and optional context use captured file-backed snapshots. Context is
strictly parsed with its 1 MiB limit. The result comes from analysis of the
captured source, while context bytes are copied unchanged. Before publication,
the workflow checks artifact bytes and rehashes the original source/context to
reject changed inputs. Content hashes determine changes, not mtime alone.

Files are written under a temporary sibling directory; only a completed bundle
is renamed into the new target. Existing destinations are rejected. Errors or
cancellation before publication remove staging rather than exposing partially
written success files. Publication is the commit point: interruption afterwards
can leave a complete bundle. A newly created parent directory can remain empty.

HTML uses escaped text for every declaration and fixed local evidence filenames
for links. It shows every physical reason and the complete engineering event
count; at most 50 ordinary threshold events are previewed, with the full
unchanged evidence in Analysis JSON. Temporal/model status and data-quality
counts remain visible. No physical PASS badge, fault confidence, SOC conversion,
source-channel verification or safety conclusion is introduced.

Software, packaging and document-layout checks do not establish physical fault
accuracy or qualification of native GUI/platforms. Independent data suitability,
held-out evaluation and required release/CI qualification remain separate work.
