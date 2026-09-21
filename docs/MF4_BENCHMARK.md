# MDF/MF4 end-to-end benchmark

Issue #36 tracks a performance-validation question rather than a correctness bug: the MDF loader asks `asammdf` for 64 MiB output DataFrame chunks, but that request does not prove that the complete MDF filtering/decoding path has a 64 MiB process-memory bound.

This benchmark measures the whole BatteryLog workload in a fresh child process and records sampled resident set size (RSS) plus the OS-native peak-RSS high-water mark, not only Python `tracemalloc` heap.

## Method

The repeatable benchmark is:

```powershell
.\.venv\Scripts\python.exe benchmarks\benchmark_mf4_analysis.py
```

Defaults:

- 96 cell-voltage channels
- 12 temperature channels
- 100,000 and 200,000 samples
- 10 Hz timestamps
- MDF 4.10
- no MDF compression
- both standard analysis and full HTML evidence-report modes
- three fresh child-process repeats per size/mode
- process RSS sampled every 10 ms with `psutil`
- OS-native process peak RSS captured as a high-water mark (`peak_wset` on Windows; `resource.ru_maxrss` on POSIX)

Synthetic MF4 generation runs in the parent process. Each measured analysis/report workload runs in a fresh child process, so the generator's allocations do not contaminate the measured RSS baseline or peak.

The standard-analysis worker calls the public path-based analysis API. The report worker executes the CLI report path, including the file-backed evidence snapshot, hashing, MF4 ingestion, report-series collection, and HTML generation.

Benchmark output is informational. No cross-platform timing or RSS threshold is enforced in CI.

## Initial measurement

Measured on 2026-09-21 with:

- BatteryLog: `0.8.0.dev0`
- Python: `3.13.14`
- asammdf: `8.8.27`
- psutil: `7.2.2`
- OS: Windows 11 (`Windows-11-10.0.26200-SP0`)
- CPU: AMD Ryzen 5 7500F 6-Core Processor
- physical RAM: 15.7 GiB
- channels: 96 cell voltages + 12 temperatures
- repeats: 3 per size/mode

| Rows | MF4 size | Mode | Median elapsed | Median throughput | Median sampled peak RSS | Median native peak RSS | Max native peak RSS |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 100,000 | 83.2 MiB | analysis | 1.193 s | 83,791 rows/s | 559.5 MiB | 580.0 MiB | 618.5 MiB |
| 100,000 | 83.2 MiB | report | 1.513 s | 66,106 rows/s | 499.3 MiB | 538.1 MiB | 538.3 MiB |
| 200,000 | 166.3 MiB | analysis | 2.332 s | 85,756 rows/s | 817.7 MiB | 869.1 MiB | 869.1 MiB |
| 200,000 | 166.3 MiB | report | 2.848 s | 70,223 rows/s | 670.2 MiB | 704.4 MiB | 704.4 MiB |

The generated HTML reports were 173.4 KiB for the 100,000-row input and 174.9 KiB for the 200,000-row input.

## Interpretation

Doubling the generated MF4 from 83.2 MiB / 100,000 rows to 166.3 MiB / 200,000 rows increased median OS-native peak RSS by:

- 289.1 MiB (+49.8%) in standard analysis
- 166.3 MiB (+30.9%) in evidence-report mode

Therefore the loader's 64 MiB `chunk_ram_size` request must **not** be described as an end-to-end process RSS bound. The measured path contains a source-size-proportional memory component inside or around the third-party MDF filtering/decoding workflow.

The report path happened to use less peak RSS than the standard path on this host. This benchmark does not establish that relationship as a general property; the two paths reach MDF ingestion through different source/snapshot mechanics and should be compared again on other platforms and vendor files.

## Limits of this measurement

- RSS is sampled every 10 ms, so the sampled series can miss a shorter transient peak. The separately recorded OS-native high-water mark provides a second view on supported platforms and was higher than the sampled peak in several Windows runs. The two metrics use platform-specific accounting definitions and are not assumed to be numerically ordered on every operating system.
- The input is deterministic synthetic MDF rather than proprietary vendor data.
- All generated channels share one time base and are selected for analysis.
- The file is uncompressed; compressed/vendor MDFs can have different CPU and memory behavior.
- The synthetic values remain inside the configured engineering limits, so the result contains no large violation-event list.
- Results are from one Windows host and are not suitable as universal performance thresholds.

For real-world validation, repeat the benchmark with representative channel counts, file sizes, MDF compression/layout, and host operating systems, and keep the raw JSON output with `--json-out`.
