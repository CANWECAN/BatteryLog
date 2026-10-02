# Input inspection (0.10 development)

Inspect one measurement before configuring or running its analysis:

```sh
batterylog capture.csv --inspect
batterylog capture.mf4 --inspect --config validation.yaml
```

The command writes a separate inspection JSON envelope to stdout and does not
create reports, modify inputs or evaluate engineering rules. It reads the CSV
header or MDF/MF4 channel metadata, without decoding measurement samples.
MF4 inspection requires `batterylog[mf4]` just like analysis.

## Reading the output

- `channels` lists available source names. CSV order is preserved; MDF names are
  sorted, with a separate entry for each group/channel occurrence.
- `unit` is `null` for CSV: column names do not verify physical units. For MDF it
  contains the declared metadata, including units of unused channels.
- `bindings` shows source-to-canonical names when selection succeeds. Sensor
  selection, duplicate detection, mapping and required pack-channel checks use
  the same policy as analysis. MDF also checks selected sensors' declared units.
- `time_basis` is `csv_column` or `mdf_master`. In MDF, the timestamp binding is
  the loader's name for master time; that name need not exist in `channels`.
  A configured timestamp name does not select a separate MDF sensor channel.
- `metadata_status` is `OK` or `ISSUES`. A readable inventory survives a selection
  error. `issues` reports the first blocking issue; `bindings` is empty in that
  case. Correct it and inspect again to uncover any subsequent issue.
- `inspection_schema_version: 1`, `scope: "channel_metadata_only"` and
  `analysis_performed: false` identify this output. It is separate from the
  frozen result-v8 analysis JSON and cannot be passed to its result validator.

`OK` only describes the checked metadata. It can occur for a header-only CSV or
a file whose values later fail analysis. It does not certify numeric samples,
CSV data-row structure, timestamp ordering/alignment, calibration, complete cell
topology or battery safety. MDF unit checks trust declared metadata and do not
convert units. Run the normal analysis to check samples and evaluate configured
engineering limits.

## Configuration and exit codes

Use the same YAML mapping and CLI overrides as analysis. An active pack-current
or pack-voltage rule makes its corresponding channel required, even though the
rule itself is not evaluated by inspection.

Exit code `0` means metadata checks returned `OK`; `4` means `ISSUES` or an
unreadable input/configuration/backend. Selection issues appear in stdout JSON;
read failures appear on stderr without JSON. Exit code `2` means invalid CLI
usage. Inspection never emits the engineering FAIL or NOT_EVALUATED exit codes.

`--inspect` cannot be combined with `--batch`, `--recursive`, `--output-dir`,
`--report` or `--json-out`. Redirect stdout yourself if a saved inventory is needed.
Discovery and JSON output are proportional to channel count; this is not a
streaming inventory interface for arbitrarily many channels.

## Python API

```python
from batterylog import inspect_measurement, load_validation_config

inventory = inspect_measurement("capture.mf4", config=load_validation_config("validation.yaml"))
print(inventory["channels"])
print(inventory["issues"])
```

The optional config defaults to `ValidationConfig()`. The API returns an
`InspectionResult` typed dictionary; unreadable inputs or unavailable backends
raise the same ordinary read/configuration exceptions used by the CLI.
