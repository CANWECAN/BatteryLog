# Precharge numerical control corrections - 15 October 2026

Source baseline: e4de1f6b. The boundary campaign ran on Windows; parent CI
38629784843 passed all 12 jobs. Source identities are retained with the results.

## Reproduced failures

### Activation pre-check used a different numerical boundary

For an actual interval of 0.25 s and max_gap_s=0.24999999999999956 s, scalar
math.isclose with the existing REL=8*binary64 epsilon accepts the interval.
The curve loop uses that symmetric boundary. The vector activation pre-check
used NumPy's second-argument-scaled isclose and rejected the same edge.

With phases [0,1,1,0,0,1,1] at [-.25,0,.25,.5,.75,1,1.25], the pre-check missed
both accepted activation edges. The loop then completed the first 0.25 s
reference horizon and returned before the second activation. A standalone curve
call that should reject multiple observed activations could therefore return
covered=true. With nominal max_gap_s=0.25 the same input correctly rejected.

The vector pre-check now ORs both isclose argument orders, matching the existing
scalar policy. It still rejects multiple observed activations. Capture review
still intentionally reviews separate spans; its two valid boundary spans remain
covered. REL, source data, references and production Core decisions are unchanged.
This is numerical equivalence, not a sensor or physical measurement tolerance.

### Real gap controls were validated without normalizing their representation

A JSON max_gap_s integer of 10**400 reached math.isfinite and raised an uncaught
OverflowError. The file CLI exited 1 with a Python traceback; it created no report.
Fraction(1,4), accepted by the Python API's Real type check, later caused NumPy
TypeError. A positive Fraction too small for binary64 failed in the same path.

The shared validator now converts the real gap to binary64, catches conversion
errors and requires a finite positive result. Both public reviewers use that
validated value. Representable Real controls work; overflow, underflow-to-zero,
unsupported types and invalid values produce the established ValueError family.
The file CLI therefore reports its normal argument error (exit 2), preserves
inputs and creates neither output nor staging directory for these invalid gaps.

## Validation

- 24 new regressions: old source 17 failed / seven passed; corrected source
  24 passed. Includes powers-of-two time scales 2**-800 through 2**800,
  single/capture-span qualification, Fraction and NumPy scalar controls, enormous
  integers and actual subprocess CLI rejection without traceback/output.
- Independent scalar-edge comparison: 1,200 captures over exponents -800..800
  and neighbouring binary64 gap values. Expected 1,036 multiple-activation
  rejections. Old vector pre-check disagreed in 262 trials; corrected code in zero.
- 400 generated capture reviews plus 400 single-curve reviews retain all prior
  reports exactly. 20,607 generated source rows / 5,071 capture spans. Includes
  duplicates, missing current, zero pack voltage, unknown phase and interrupted
  coverage. Strict JSON and unchanged read-only input arrays verified.
- Existing pinned BMW raw trace rebuilt byte-identically: 13,412,692 bytes,
  SHA-256 4f9e4b0a8bcd02952e586d1dc58d704dc18f3290a5faf8186b4e1a626f6fea9c.
  Its clock, sensor ages and physical curve eligibility remain unknown/false.
- Windows cases passed in two processes: 45 GUI plus 2,857 remaining cases,
  two skips / nine existing warnings; combined Core coverage 96.67% with the 95%
  gate enforced. Required real Tk and actual MF4 were used. Ruff check/format,
  CI-mode Core mypy (48 files), pip and whitespace checks passed.
  Two single-process full attempts each had 2,901 passes / two skips / one Tk
  setup error before a test body (button.tcl, then init.tcl could not be read).
  The file read ten times with equal hashes; five real roots, 45 isolated GUI
  cases and a separate 100-root probe passed. No Python/Tcl installation or
  application/test source was changed for isolation. Original failed logs are
  retained. Single-process native GUI stability remains an open issue; its
  cause has not been established. Coverage data from both partitions is combined.

Compact results, exact source fingerprints and raw-log digests are retained in
`batterylog_research/precharge_boundary_validation_20261015.json`.
Native generator/check scripts, old normal reports and raw logs remain in the
separate batterylog-file-boundary-20261015-evidence directory. Campaign seeds
are 20261015 (normal) and 15002026 (boundary). These are software trials, not
physical fault labels or population performance estimates.

The source changes are limited to precharge_curve_review.py,
precharge_capture_review.py and new regressions. No Core/schema/dependency/license
change, CAN transmission, merge or release. Physical steps 6-8 retain the prior
clock/signal/acquisition/reference requirements. The exact-source hosted result is recorded in PR #14.
