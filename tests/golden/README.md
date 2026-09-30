# Serialized semantic anchors

These JSON files are fixed expectations, not snapshots regenerated from the
current analyzer. Both whole-frame and streaming analysis must match their exact
serialized bytes, because Python dictionary equality alone hides signed zero.

The initial three anchors preserve ordinary v0.9.2 behavior. The additional
fixtures use hand-calculated, binary-exact inputs:

- `semantic_all_rules_pass.json`: all nine rules enabled; current, temperature,
  temperature-spread and pack/cell-sum values on exact limits remain PASS.
- `semantic_pack_lower_fail_charge.json` and
  `semantic_pack_lower_fail_discharge.json`: physically equivalent current
  traces with reversed polarity; signed limits and measured evidence, cell
  undervoltage, low temperature, temperature spread, event-gap splitting,
  duplicate timestamps, and first-equal positive/negative pack-mismatch peaks.
- `semantic_all_excluded_fail.json`: active rules with no analyzed rows produce
  FAIL, grouped data-quality evidence, null metrics and no engineering events.
- `semantic_explicit_mapping_pass.json`: vendor source names and patterns remain
  present in mapping provenance while the numeric result matches canonical input.

The additional fixtures run with chunk sizes 1, 2, 3 and 64, covering boundaries
inside events as well as an input smaller than one chunk. They were checked
against the released v0.9.2 tree as well as the post-refactor implementation.

Do not update these files merely to make a refactor pass. Any intentional change
to an expected value needs a documented contract decision and an independent
calculation of the replacement expectation.
