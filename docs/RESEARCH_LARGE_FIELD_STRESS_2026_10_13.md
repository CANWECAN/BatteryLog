# Large real-field stress and interpretation — 2026-10-13

Baseline: `8d28af92b29f488b3bfeaf4957f2eedd3ab3a89c`.
Branch: `audit/cloud-balancing-spread-20261012`.

## Source and identity

Schaeffer, Joachim; Lenz, Eric; Gulla, Duncan; Bazant, Martin; Braatz, Richard D.;
Findeisen, Rolf. *Lithium-Ion Battery Field Data: 28 LFP battery systems with 8
cells in series, up to 5 years of operation*. DOI:
[10.5281/zenodo.13715694](https://doi.org/10.5281/zenodo.13715694).
License: CC BY-NC 4.0. This is an internal research characterization; raw data
files are not committed or distributed by BatteryLog.

The selected system has eight series-cell voltage channels, four shared
temperature channels, pack voltage/current and converter-current channels.
The publisher describes a returned-system population, with return reasons
not established as independently labeled faults. One selected system therefore
does not measure the general population's fault rates.

Selected archive member: `field_data/data_sys_4.csv`, **690,633,709 bytes**.
A standard HTTP byte-range retrieval fetched this member from the official
Zenodo file URL. Its ZIP member length and CRC32 `459f0234` were checked, and
the complete extracted file is pinned by SHA-256:

`f4a7861b72b273f7a78f5fc2e1f965c9c631bc579ea03099d14b10f82df003b9`

The archive's published MD5 is `827f508740c4154b7ff7b15de3b2c75d`, but the
entire 1,668,409,464-byte archive was NOT downloaded and that full-archive
digest was NOT verified. The selected complete member's integrity was checked.
Download/extraction took 265.351 s; that is not an analysis benchmark.

The publisher-linked [BattGP channel map](https://github.com/JoachimSchaeffer/BattGP/blob/main/src/batt_data/data_columns.py)
was consulted for signal meaning; its filtering, gap removal, duplicate removal,
float32 conversion and smoothing were not applied.

## Every source row retained, one clock boundary exposed

All **4,695,793 rows** were mapped to 8 cell voltages, 4 temperatures, pack
current/voltage and elapsed recorded time. Absolute source timestamp differences
were retained without timezone assumptions or interpolation. The resulting
canonical CSV is **847,710,112 bytes**; decimal representation changed, but no
source row was removed, reordered, clipped or physically recalibrated.

Recorded time runs from 2015-02-09 21:22:22 for 45,665,933 elapsed seconds.
Source quality observations:
- 11,214 duplicate-timestamp adjacent pairs.
- 389,938 gaps greater than the illustrative 60 s continuity limit.
- Zero non-finite rows in the channels used by the analyzer.
- One backward timestamp: source data row **3,304,582** goes from
  **2016-01-01 00:00:54 to 00:00:00**, a **54 s reversal**.
  In this source, CSV physical line is data row + 1.

The intact canonical file was passed through the actual native CSV loader and
streaming engine at 65,536 rows/chunk. It correctly rejected the input with
`ValueError: timestamp_s must be non-decreasing`; no complete result was emitted.

The two chronological regions were then analyzed separately. The split copied
the existing canonical record bytes and added only the same CSV header to the
second file. Reassembling both data portions reproduced the exact complete
canonical SHA-256. Original elapsed times and all duplicate records remained.
No temporal event was allowed to bridge the clock reversal.

## Native CSV stress results

Illustrative profile: cell voltage 2.5–3.65 V; maximum spread 0.1 V; temperature
ceiling 55 C; pack/cell-sum error 0.15 V. Models: sustained spread above 0.05 V
for 30 s; recorded temperature rise above 10 C/min, minimum interval 1 s;
maximum observation gap 60 s. These parameters are software probes, not
manufacturer requirements or validated safety limits.

| Region | Rows | CSV bytes | Core events | Model events | 65,536 chunk analysis s / peak MiB | 131,072 chunk analysis s / peak MiB |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Before reversal | 3,304,581 | 597,851,655 | 393 | 13,153 | 100.554 / 179.266 | 100.566 / 252.270 |
| After reversal | 1,391,212 | 249,858,607 | 1,662 | 7,029 | 47.579 / 178.328 | 46.468 / 259.082 |

Both regions returned FAIL under the illustrative parameters. That is a
threshold outcome; all executed reference/parity checks passed.

The full serialized result-v9 JSON bytes matched exactly between the two
chunk sizes for EACH region, including all statuses, events, counters, peaks
and evidence. Combined successful stream row-analyses: **9,391,586**.
Both runs of each region passed result-v9 Schema and semantic validation.

Independent raw-array expressions matched all configured Core violation
sample counts. Independent vector/interval references matched **20,182 model
event chains**: 1,052 sustained-imbalance and 19,130 temperature-rise events.
Checked fields include eligible sample accounting, model status, start/end/peak
timestamps, sample counts, peak values and numeric before/after evidence.

The independent full-frame reference peaked at 1,573.027 MiB for the larger
region and 699.227 MiB for the smaller one. The streaming peaks above include
the whole fresh Python process, CSV header preflight, result retention,
validation and serialization; they are not observer-only allocation counts.
Some workers ran concurrently, and filesystem caches were warm. Timings are
one-host characterizations, not throughput guarantees. The observed result
volume was only about 7.7 MB JSON combined, so arbitrary event-heavy memory
behavior is still not proven bounded.

## Adversarial checks

The first 2,049 real source rows were also compared as a full frame versus
partitions of 1, 7, 1,024 and 65,536 rows: four exact matches.

Separate injected timestamp regression and infinite cell-voltage inputs were
rejected at all four partition sizes with identical diagnostics. The non-finite
diagnostic identifies data row 1,025 and `cell_1_v`. These injected cases are
software adversarial probes, not claims about measured physical faults.

The source's integer temperature dtype exposed a bug in the NEW independent
reference harness: a derivative buffer allocated with integer dtype could not
hold floating rates. The harness now converts temperature arrays to float64
explicitly. An all-integer-channel regression test anchors this case. BatteryLog's
production rate calculation already converts temperature arrays to float.

Final focused validation: **45 tests passed**, including four new reference
anchors, existing independent model oracles, CSV evidence provenance and
distribution-boundary checks. Whole-tree Ruff check/format passed. The complete
2,219-test repository suite from the earlier checkpoint was not repeated here;
no production analysis code was changed.

## What the results mean

### Temperature resolution dominates the sampled-rise flags

**18,942 / 19,130 event peaks (99.02%)** depend on a recorded **+1 C** step.
A +1 C step across 1 s calculates to 60 C/min; across 4 s it calculates to
15 C/min. Most recorded nonzero temperature changes are whole-degree steps.
The highest logged temperature across the tested regions is **47 C**, with
zero samples above the illustrative 55 C absolute ceiling.

This is evidence of sampled threshold crossings, not 19,130 thermal faults.
Coarse temperature resolution and update timing can create large finite
differences from a gradual underlying change. Actual thermal behavior requires
sensor resolution, source update timing and physical corroboration. A future
review should display that context; silently smoothing away peaks or raising
limits just to obtain PASS would destroy evidence.

### Cell 1 deserves targeted source review

The standalone peer-relative step observer processed both regions with a 0.05 V
review threshold and 60 s gap limit. It emitted **4,037 observational candidates**;
**3,958 (98.04%)** concerned cell 1. There were no ambiguous-reference pairs.
This is a useful localization result, not a cause or defect count. Repeated
changes and reversals may belong to the same physical/acquisition episode.

Traceable extremes in the original row order:
- Row **4,521,427**, 2016-07-12 08:09:39: cell 1 = **1.752 V** while other cells
  are around 3.36 V. Pack voltage 25.184 V versus sum 25.290 V.
- Row **4,535,913**, 2016-07-13 04:16:56: cell 1 = **4.934 V** while most peers
  are around 3.31 V. Pack voltage 28.203 V versus sum 28.131 V.

Those pack sums are reasonably close under the example 0.15 V criterion, adding
a second logged measurement chain to the cell-spread observation. It still
does not establish cell failure rather than sensor, converter, connection,
mapping or acquisition behavior. Channel-specific source timestamps and
independent known-fault labels remain absent.

The logged pack-current magnitude reaches **15,879.939 A** in the later region.
This is a recorded value, not a verified physical current. Numerically finite
signals can still require calibration/acquisition plausibility review.

### Complementary rules caught a real observer blind spot

At source row **3,802,126**, 2016-02-11 14:53:53:
pack = **27.038 V**, all eight cells approximately **2.8 V**, cell sum =
**22.370 V**, signed discrepancy = **4.668 V**.

An 11-row window around that source record produced **zero peer-step candidates**
but two rows beyond the pack/cell-sum error criterion. A common change of all
cells is deliberately removed by the relative observer. The existing
independent pack/cell-sum rule exposed the inconsistency. This argues for
reviewing absolute, relative and continuity evidence together, rather than
treating the peer observer as a complete detector.

### Promotion decision

Keep the peer-step tool observational and keep source-quality limits explicit.
The arithmetic and chunk state passed this larger real-data campaign.
Physical diagnosis, universal thresholds, SOH/RUL accuracy and population fault
rates are not established. Converter current was summarized as logged context;
it was not silently converted into an authoritative balancing-active state.

Interpretation of the July episodes requires original cell-1, converter and
current records with source timing, scale and sensor documentation. This campaign
does not establish native Windows/Tk, actual MF4 or installed-distribution behavior.

## Reproduce

Obtain the publisher's archive, verify its published archive MD5 when the full
archive is downloaded, and extract `field_data/data_sys_4.csv`. The preparer
also enforces the selected member's SHA-256 above.

```bash
python -m batterylog_research.field_stress prepare --source data_sys_4.csv --output field-stress
```

For this hash-pinned source, preserve all canonical bytes while splitting at
the independently located source row:

```python
from pathlib import Path

root = Path("field-stress")
with (root / "canonical.csv").open("rb") as src:
    header = src.readline()
    out = (root / "segment_1.csv").open("wb")
    out.write(header)
    try:
        for row, record in enumerate(src, start=1):
            if row == 3304582:
                out.close()
                out = (root / "segment_2.csv").open("wb")
                out.write(header)
            out.write(record)
    finally:
        out.close()
```

Run each region at both sizes, then its independent reference and peer audit:

```bash
python -m batterylog_research.field_stress core --source field-stress/segment_1.csv --output field-stress/segment1-65536.json --chunk-rows 65536
python -m batterylog_research.field_stress core --source field-stress/segment_1.csv --output field-stress/segment1-131072.json --chunk-rows 131072
python -m batterylog_research.field_stress reference --source field-stress/segment_1.csv --result field-stress/segment1-65536.json --output field-stress/reference1.json
python -m batterylog_research.field_stress peer --source field-stress/segment_1.csv --output field-stress/peer1.json
python -m batterylog_research.field_stress hostile --source field-stress/canonical.csv --output field-stress/hostile.json
python -m pytest -q tests/test_research_field_stress.py
```

Repeat the core/reference/peer commands for `segment_2.csv`. Aggregate observed
evidence is retained in `batterylog_research/field_stress_summary_20261013.json`.
