# CAN profile validity, boundary fixes and file stress — 2026-10-13

Private integration candidate: [draft PR #2](https://github.com/CANWECAN/BatteryLog-Research/pull/2).
Baseline before this iteration: `ec1e52e3d011ddd8fe3fad350235882ca57bca70`.
Changes are confined to Research tools, tests and evidence. Core source, runtime
dependencies, result schemas, public repository, licensing and release remain unchanged.

## Reproduced findings

| Finding | Before | Resolution |
| --- | --- | --- |
| Multiplexer scaling changes raw group identity | With selector conversion `(1,1)`, raw group 0 could be decoded/selected as group 1 and enter canonical CSV. Timing observations were also relabelled. | Preparation and audit require unsigned integer multiplexers with identity conversion across all selected messages. Scaled/signed/float selectors are rejected before output. This does not modify cantools. |
| Ambiguous JSON profile | Conflicting `max_age_s`, bus or required-group keys silently used the last occurrence. | Reject duplicate keys at every nesting level and nonstandard JSON constants; read profiles as UTF-8. |
| Distinct times collapse in binary64 CSV | Widely separated origin/anchor times allowed distinct nanosecond timestamps to become one CSV time. | Reject lost ordering precision with source-line evidence; genuine duplicate source times remain valid and ordered. |
| Caller Decimal precision changes age decisions | With caller precision 8, age `1.000000001` became 1 and a span `2.000000001` became 2, crossing configured boundaries. | Isolate stream arithmetic in a local 28-digit context, sufficient for the transport parser's 27-digit bound, and preserve the caller context. |
| Concurrent report overwrite | A report created after the initial existence check could be overwritten by POSIX rename. | Publish fully written single-file audit/review reports through an atomic hard link that rejects an existing name. No overwrite fallback. |

Also normalized Research evidence/fixture output to UTF-8 and LF. Windows JSONL
previously differed by one CR byte per row; the final large-file outputs match
Linux byte-for-byte. This is reproducibility hardening, not a physical CAN defect.
The hard-link publication path requires a supporting destination filesystem;
unsupported filesystems fail rather than replacing an existing report. Directory
preparation retains its existing staged-publication behavior; this iteration does
not claim a general concurrent-directory reservation protocol.

## Small build: explicit raw validity codes

An individual signal entry may now declare `invalid_raw_values`, for example:

```json
{
  "column": "temp_1_c",
  "frame_id": 512,
  "extended": false,
  "signal": "T",
  "max_age_s": 1,
  "invalid_raw_values": [255]
}
```

These are caller-declared exclusions. No all-ones or other value is guessed to
be invalid. The list must be nonempty, unique integers inside the DBC signal's
raw width and signedness; float signals and booleans/coercions are rejected.
For a signed 16-bit signal, a code such as `-32768` uses the signed decoded raw
value; unsigned bit-pattern `65535` is not silently converted to `-1`.

A declared invalid newest record replaces the previous cached valid value.
The affected CSV field remains blank, including at a still-fresh anchor. It is
not filled from an older record. Source line/time, age, raw value, rejection flag
and usable state remain in `alignment.jsonl`. A subsequent valid source record
can restore the field. Unrelated buses/identifier types cannot invalidate it.

`declared_invalid_raw_values_observed_by_column` counts selected source-signal
observations, not anchor rows or physical faults. The existing missing/expired
counter includes the resulting blank CSV values. There is no new engine status:
native strict analysis rejects the missing measurement; explicit exclusion mode
retains quality evidence and returns FAIL, including when every row is excluded.
Full-frame/native streaming results agree at chunk sizes 1, 2 and 65,536.

Profiles without this key preserve their measurements/evidence and do not run
the extra unscaled decode. Existing Model 3 profiles were not assigned guessed
invalid codes. OEM validity/status mappings still need verified source evidence.

## Verification

The final focused CAN corpus has **214 passed** on Linux and native Windows,
up from 90 at this iteration's baseline. Preparation has 48 seeded 160-record
campaigns, including declared raw rejection; multiplex timing has 24 seeded
321-record campaigns. Independent references use direct bytes, earlier-record
searches and offline partitions rather than the preparation/timing cache.

Full-suite results and the exact eight source/test Git blob identities are stored
in `batterylog_research/can_bug_hunt_summary_20261013.json`. Cloud execution lacks
desktop display and optional actual MF4; native Windows includes those backends.
Core coverage comes from the native/hosted gates, not an unrun cloud coverage job.
Ruff checks/format and pinned native mypy passed. Test warnings are the existing
nine deliberately overflowing arithmetic probes.

Replayed real-source evidence remains unchanged: Model 3's 118,053 frames,
canonical CSV, alignment JSONL, native result hash and full-frame/chunks 1/7/65,536;
the multiplex baseline plus six raw-reference mutation campaigns; and EX30/BMW's
317,435 records, 76,005 dual-decoder values and 17,995 direct-byte values. Model 3
still has 6 selected anchors, 5 analyzed/1 excluded, a data-quality FAIL and zero
configured engineering violations. EX30/BMW remain ineligible for canonical
analysis. These are offline observations, not fault-detection accuracy rates.

## Large file campaign

Ran an authored 2,000,000-frame file and checked every one of its 1,000,000 CSV
rows and alignment records independently on Linux and native Windows. In each
host run, 500,000 anchors arrive exactly at the 0.05-second age limit and 500,000
arrive one nanosecond past it. No timestamp rounding makes expired data usable.

A second campaign declares raw temperature code 255 and injects it every 100
cycles: 5,000 source contexts are explicitly rejected, with no previous-value
backfill. All 1,000,000 rows are still checked. Current remains independent of
the temperature policy. The source, canonical CSV and JSONL file hashes match
across hosts in both campaigns.

| Raw-validity campaign file | Bytes | SHA-256 |
| --- | ---: | --- |
| Source | 94,000,000 | `dea2280d4863d5ca404800f3f5e48ab4dda7490ec82b1950e9a58e136d269577` |
| Canonical CSV | 26,267,834 | `946afbd2c77b130a2133240f6c3003afe28cee6bd271f7b6d63a1b94d5450740` |
| Alignment JSONL | 635,116,122 | `9ffd12ebae81747f3c09f06514a5aca2dbd131b834d60df480dbe1a2ff58f253` |

Preparation took about 46.02 seconds in the cloud and 24.68 seconds on native
Windows for the raw-validity campaign. Timings characterize these executions,
exclude source generation and do not establish sustained adapter performance.
Large raw/generated files remain outside the repository; only aggregate evidence
and the reproducible authored campaign are committed.

```bash
python -m batterylog_research.can_boundary_stress fresh-stress --cycles 500000
python -m batterylog_research.can_boundary_stress fresh-raw-stress \
  --cycles 500000 --invalid-every 100
```

## Integration boundary

The combined source/evidence commit triggers the existing private verification
workflow. [PR #2](https://github.com/CANWECAN/BatteryLog-Research/pull/2) carries
the exact-HEAD hosted outcome; predecessor CI must not be cited as proof of this
iteration. PR stays draft and unmerged. Source/profile validity declarations do
not authenticate OEM codes, acquisition synchronization, physical topology,
hardware calibration or fault labels. Live adapter/HIL, counters/CRC, CAN FD and
ISO-TP remain separate gates. No vehicle transmission was performed.

## Hosted outcome collected after interruption — 2026-10-14

Verified source HEAD `61c1607d9a19ef662357b619c3bfbf70df699ada` completed
[run 38465139249](https://github.com/CANWECAN/BatteryLog-Research/actions/runs/38465139249)
successfully at 2026-10-13T20:52:38Z: **12/12 jobs passed**. The conversational
interruption left final evidence collection incomplete; it did not lose source
work or interrupt GitHub's run. Source/test blob identities were rechecked.

| Hosted job | Result | Core coverage |
| --- | --- | ---: |
| Linux 3.11, 3.12, 3.13 | 2,497 passed / 2 skipped in each | 96.23% |
| Linux 3.14 | 2,497 passed / 2 skipped | 96.02% |
| Minimum runtime | 2,497 passed / 2 skipped | 96.23% |
| Windows 3.13 | 2,495 passed / 4 skipped | 96.21% |
| Five MF4 jobs | 175 passed in each | Backend subset |
| Package | All build/scan/corpus/Twine/outside-checkout install checks passed | Not a coverage job |

Private artifact ID 11847817743, 642,525 bytes, archive digest
`sha256:c2bd2bce53d9412813fd0c7065d35aee7598953f80f1dccfeef9c92fa68baf94`.
The documentation closure preserves this completed source-run identity and
triggers its own follow-up verification; latest status remains on PR #2.
