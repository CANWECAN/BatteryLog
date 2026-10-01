# Result-v8 consumer checks

The published `result-v8.json` is frozen. Its JSON Schema checks structure,
allowed fields and many status constraints, but cannot establish every
cross-field relationship. `validate_result_semantics(result)` adds a small,
opt-in set of consistency checks for consumers of result-v8 JSON.

It checks:

- Applied limits satisfy the existing `ValidationLimits` constraints.
- `rules_evaluated` contains exactly the rules with non-null applied limits.
  List order is not an additional wire requirement.
- Every violation code belongs to that evaluated set.
- The comparison policy is the fixed v8 policy: relative tolerance
  `1.7763568394002505e-15` (8 binary64 epsilons), absolute tolerance `0.0`, and
  mode `strict_with_binary64_guard`.
- `rows_input == rows_analyzed + rows_excluded`.
- Data-quality event bounds satisfy `1 <= start_row <= end_row <= rows_input`,
  and `affected_values == (end_row - start_row + 1) * len(signals)`.

These address the known consumer gaps recorded in PRs #60, #63 and #66, plus
the documented row-accounting relationships. The function returns `None` on
success, raises `ValueError` for a checked inconsistency, and does not modify
the result. It supports v8 only. Different defect classes may overlap one
excluded row; their affected-value counts must not be summed as row counts.

## Usage

Parse strict JSON and validate the frozen structural schema **before** calling
the semantic check. The example uses `jsonschema`, available in BatteryLog's
development extra; a consumer may use another conforming structural validator.
No new runtime dependency is required by the semantic function itself.

```python
import json
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator

from batterylog import validate_result_semantics


def reject_non_json_number(token):
    raise ValueError(f"Non-JSON number: {token}")


result = json.loads(
    Path("result.json").read_text(encoding="utf-8"),
    parse_constant=reject_non_json_number,
)
schema = json.loads(files("batterylog").joinpath("schema/result-v8.json").read_text())
Draft202012Validator(schema).validate(result)
validate_result_semantics(result)
```

This is not a replacement for JSON Schema validation. Missing fields, wrong
types, duplicate rule entries and status constraints belong to that structural
step. Skipping it is unsupported. The semantic check also does not reconstruct
source rows, recompute measured extrema or event peaks, validate all event
arithmetic, establish complete data-quality event coverage, authenticate
provenance, or prove physical sensor validity. Passing both checks establishes
the listed contract constraints, not the truth of an independent producer's
measurements.

Analysis and report generation continue to use their existing behavior. The
check is not automatically added to those paths and does not alter result bytes,
engineering decisions, config-v6 or result-v8. A future schema version may encode
more of these constraints; this helper does not justify changing the published
v8 artifact in place.
