# Research-only: temperature event source triage

A BatteryLog temperature-rise event records **a sampled rate of change**, not a
diagnosis of a physical battery fault. The external battery cycling dataset contains
finite but implausible readings (e.g. 655.28 degC). These events must not silently
disappear from result-v9 reports merely because they exceed a review bound.

The new `batterylog_research.temperature_triage` module inspects existing
`TEMPERATURE_RISE_HIGH` event evidence. It **never** changes input JSON, model
outcomes, original event counts or sensor values. It is not packaged in the
Apache-licensed Core wheel; see `RESEARCH_BOUNDARY.md`.

## Run from a Research checkout

    python -m batterylog_research.temperature_triage path/to/result.json \
      --max-temperature-c 150 --max-reported-rate-c-per-min 1000 \
      --max-examples 5

All review limits are **explicit and user-supplied**. The example numbers above
are not calibrated hardware, chemistry, fire or safety thresholds. At least one
bound is mandatory. Optional `--min-temperature-c` checks the lower bound.

The JSON stdout gives the number of reported temperature-rise events examined,
flagged events, reasons, representative sensors and at most N examples. When
multiple sensors tie on peak rate, the first listed sensor is the one associated
with the numerical evidence chain. A single event may have several review flags.

## Scope limitations

- This is **event-level triage**, not a scan of every raw temperature sample.
- An event with no review flag is *not* a confirmed physical temperature fault;
  zero flags are *not* evidence that the source file is healthy.
- The original input should first pass BatteryLog's result-v9 JSON Schema and
  semantic validations. This lightweight triage does not replace either validator.
- An implausible value should trigger a source-channel investigation (units,
  decoding, thermistor dropout, acquisition artefacts, ZOH alignment) and an
  independent physical cross-check where possible.
- This tool makes **no changes** to `TEMPERATURE_RISE_HIGH` engineering logic,
  source normalization, thresholds, PASS/FAIL/NOT_EVALUATED, or evidence schemas.
- Loading a very large result JSON still takes memory proportional to file size.
  An event-streaming implementation would require independent resource testing.

Focused local check (Python 3.13, without running the full BatteryLog test suite):

    python -m pytest -q tests/test_temperature_triage.py

14 new unit tests passed in an isolated local environment on 2026-10-12.
This is **not** a substitute for the full Linux/Windows CI suite, Ruff, mypy or
validation against actual source JSON files.

## CLI result-v9 validation gate (2026-10-12)

Before reviewing events, the command-line entry point loads BatteryLog's
packaged result-v9 JSON Schema and applies both the structural schema
and validate_result_semantics consistency checks. It rejects duplicate
JSON object keys, NaN/Infinity tokens, and floating-point exponents
that overflow to non-finite binary64 values.

This is **contract consistency checking, not cryptographic integrity
or evidence that the measured physical signals are authentic**.
The direct Python function triage_temperature_events still expects its
caller to validate the source; only the CLI enforces that gate.

The CLI continues to load the *entire* JSON result in memory, so very
large reports require enough RAM. An isolated, synthetic 50,000-event
JSON parse + triage probe used an 8.54 MiB input string, took around
1.16 seconds, and reached about 32 MiB traced peak Python allocations.
This probe did **not** run the full schema/semantic validation gate.
It is not representative of complete real BatteryLog reports.

The focused isolated test suite passed 20 tests; two full-repository
integration tests were skipped because the isolated environment lacks
the private BatteryLog runtime. Those tests must run in an authorized
Research checkout, along with Ruff, mypy, full pytest and Windows checks.
