# Batch analysis (0.10 development)

Analyze a directory of CSV/MDF/MF4 logs with one effective configuration:

```sh
batterylog measurements --batch --config validation.yaml --output-dir results/run-001
```

Add `--recursive` to include subdirectories. Without it, only files directly
inside the input directory are selected. Supported suffixes are case-insensitive;
other file types are ignored. Measurements are processed in sorted relative-path
order, one at a time, using the same analysis service as single-file runs.

The output directory must be new and outside the input directory. This protects
previous results and prevents generated CSV summaries becoming future inputs.
Batch mode always creates per-file JSON and HTML reports; `--report` and
`--json-out` are single-file options.

## Outputs

For `measurements/session/a.csv`, a recursive batch writes:

- `results/run-001/session/a.csv/result.json`: the unchanged result-v8 payload.
- `results/run-001/session/a.csv/report.html`: the existing standalone evidence report.
- `results/run-001/summary.csv`: one row for every selected file.

Keeping the original filename, including its suffix, as a directory avoids
collisions between `a.csv` and `a.mf4`. Relative paths also distinguish duplicate
basenames in different input subdirectories.

The CSV includes status, row/exclusion counts, violation/data-quality event
counts, maximum cell voltage, cell delta and temperature, source SHA-256, output
paths, and any file error. Full engineering evidence remains in each result JSON.
Spreadsheet-sensitive text is prefixed with an apostrophe in CSV; the JSON
summary retains the exact source names and relative output paths.

Standard output is a batch summary with `batch_schema_version: 1`,
`config_sha256`, `summary_csv`, and `files`. It is distinct from a result-v8
analysis payload. Python callers can use the same workflow:

```python
from batterylog import AnalysisService, analyze_directory, load_validation_config

summary = analyze_directory(
    "measurements",
    "results/run-001",
    service=AnalysisService(load_validation_config("validation.yaml")),
    recursive=True,
)
```

An application supplying `config_evidence` must capture the YAML corresponding to
its service configuration. The CLI captures and parses the YAML once before
starting the batch; later changes to the source YAML do not change the settings
used for subsequent files. CLI overrides are represented in each result's
effective limits, as in single-file analysis.

Each measurement is analyzed from the existing file-backed snapshot. Source
hash verification happens after rendering and before publishing the per-file
report directory. JSON and HTML become available together; a failed report pair
is discarded instead of leaving a successful-looking partial artifact.

## Status and exit codes

| File status | Meaning |
| --- | --- |
| PASS | The existing analysis returned PASS. |
| FAIL | The existing analysis returned FAIL, including recorded required-data defects. |
| NOT_EVALUATED | No active engineering rule established a pass/fail result. |
| ERROR | Reading, analysis or report generation failed; no completed report pair is published. |
| NOT_PROCESSED | Processing stopped before a completed outcome was available. |

An expected error affects its file and does not stop later measurements. Missing
optional MF4 dependencies therefore appear as file errors while CSV files can
still finish. Invalid configuration, an empty input selection or an invalid
output directory aborts before processing.

Batch process exit codes preserve single-file meanings:

- `4` if any file is ERROR or NOT_PROCESSED.
- Otherwise `1` if any file is FAIL.
- Otherwise `3` if any file is NOT_EVALUATED.
- Otherwise `0` when every selected file is PASS.
- Invalid option combinations return `2`.

Interrupting processing preserves completed reports and writes a summary showing
untouched files as NOT_PROCESSED, then propagates the interruption. If summary
writing itself fails, the error propagates and no partial CSV is published.

This first version is sequential and does not resume or overwrite an old run.
Normal single-file commands, engineering rules, config-v6 and result-v8 are
unchanged. Batch analysis is a development feature; no release is published.
