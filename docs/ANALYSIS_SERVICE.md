# Shared analysis service (early 0.10 development)

`AnalysisService` accepts one effective `ValidationConfig`. CLI callers resolve
YAML and overrides before constructing it; application callers can use the
same config directly, including data-quality and signal-mapping settings.
The service owns no per-run accumulator state. Each call produces one
`AnalysisOutput` with the canonical `result` and optional `report_series` from
the same streaming pass.

```python
from batterylog import AnalysisService, load_validation_config
from batterylog.reporting import render_json_result

service = AnalysisService(load_validation_config("validation.yaml"))
output = service.analyze_path("capture.csv")  # also selects MDF/MF4 by suffix
print(render_json_result(output.result))

# Collect display geometry in the same pass as validation.
with open("capture.mf4", "rb") as handle:
    output = service.analyze_file(
        handle, source_name="capture.mf4", report_max_points=2400
    )
```

`analyze_path`, `analyze_file`, and `analyze_loader` have the same
`report_max_points` option. `None` omits plotting; an integer requests the
existing report reducer. The minimum accepted budget is 14; 14-19 can fail if
the retained extrema do not fit. Use 20 or more for its worst-case candidate
bound, or the usual 2400-point budget. Invalid budgets fail before reading rows.
See [REPORT_SERIES.md](REPORT_SERIES.md) for reduction and rendering details.

`analyze_loader` supports built-in or structurally compatible adapters following
[MEASUREMENT_CONTRACT.md](MEASUREMENT_CONTRACT.md). File handles are seekable,
binary and caller-owned. A missing `source_name` selects CSV for a handle; use
an `.mf4`/`.mdf` name explicitly for those formats. The name selects format;
it does not attach provenance or cause the service to reopen that path.

The service propagates input/config/analysis exceptions. It does not parse CLI
arguments, write output, select a process exit code, create a source snapshot,
or compute provenance. The CLI retains its existing source/config snapshot,
output-path guards, result serialization and evidence-report workflow.
Desktop callers must also prepare an evidence snapshot when reporting hashes;
calling `analyze_path` alone provides no content-hash guarantee. Progress,
cancellation and background execution are future launcher concerns.

The service and output wrapper are frozen dataclasses, but `output.result` is
the existing mutable `AnalysisResult` dictionary. Treat it as the authoritative
result and avoid modifying it before rendering. Plot geometry does not make
independent validation decisions. Report collection or rendering can fail
independently of rule evaluation; no partial output is returned on analysis error.

The existing `analyze_battery_log`, CSV-byte and streaming Python APIs retain
their signatures and behavior, including deprecated threshold overrides.
No migration is required. New callers can avoid manually unpacking a config
into separate analysis options by using this service. Frozen config-v6 and
result-v8, comparison, polarity, grouping and status semantics are unchanged.

This is the service foundation, not completion of 0.10 or a desktop launcher.
Result-consumer semantic validation, representative large-log limits and a
fresh integration review remain open before release.
