from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any

import psutil

_DEFAULT_ROWS = (100_000, 200_000)
_DEFAULT_CELLS = 96
_DEFAULT_TEMPERATURES = 12
_DEFAULT_SAMPLE_INTERVAL_MS = 10.0
_DEFAULT_REPEATS = 3


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _mib(value: float) -> float:
    return float(value) / 1024.0 / 1024.0


def _write_synthetic_mf4(
    path: Path,
    *,
    rows: int,
    cells: int,
    temperatures: int,
) -> None:
    try:
        import numpy as np
        from asammdf import MDF, Signal
    except ImportError as exc:  # pragma: no cover - benchmark environment guard
        raise RuntimeError(
            "MF4 benchmark generation requires the optional mf4 dependencies; "
            "install with: pip install -e '.[dev,mf4]'"
        ) from exc

    timestamps = np.arange(rows, dtype=np.float64) * 0.1
    phase = np.arange(rows, dtype=np.float64)

    signals: list[Signal] = []
    for index in range(cells):
        samples = 3.70 + (index % 8) * 0.001 + 0.012 * np.sin(phase * 0.0031 + index * 0.17)
        signals.append(
            Signal(
                samples=samples,
                timestamps=timestamps,
                name=f"cell_{index + 1}_v",
                unit="V",
            )
        )

    for index in range(temperatures):
        samples = 27.0 + (index % 4) * 0.4 + 5.0 * np.sin(phase * 0.0017 + index * 0.31)
        signals.append(
            Signal(
                samples=samples,
                timestamps=timestamps,
                name=f"temp_{index + 1}_c",
                unit="degC",
            )
        )

    mdf = MDF(version="4.10")
    try:
        mdf.append(signals, common_timebase=True)
        mdf.save(
            path,
            overwrite=True,
            compression=0,
        )
    finally:
        mdf.close()


def _native_peak_rss_bytes(process: psutil.Process) -> int | None:
    info = process.memory_info()
    peak_wset = getattr(info, "peak_wset", None)
    if peak_wset is not None:
        return int(peak_wset)

    if os.name == "posix":
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return int(peak)
        return int(peak * 1024)

    return None


def _run_batterylog_workload(path: Path, *, mode: str, report_path: Path) -> dict[str, Any]:
    from batterylog import ValidationLimits, analyze_battery_log
    from batterylog.__main__ import run

    limits = ValidationLimits(
        cell_min_v=2.8,
        cell_max_v=4.2,
        imbalance_max_v=0.08,
        temperature_min_c=-20.0,
        temperature_max_c=55.0,
    )

    if mode == "analysis":
        return dict(analyze_battery_log(path, limits=limits))

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = run(
            [
                str(path),
                "--cell-min-v",
                "2.8",
                "--cell-max-v",
                "4.2",
                "--imbalance-limit-v",
                "0.08",
                "--temp-min-c",
                "-20",
                "--temp-max-c",
                "55",
                "--report",
                str(report_path),
            ]
        )
    if exit_code != 0:
        raise RuntimeError(f"report benchmark returned exit code {exit_code}")
    return json.loads(stdout.getvalue())


def _measure_worker(
    path: Path,
    *,
    mode: str,
    report_path: Path,
    sample_interval_ms: float,
) -> dict[str, Any]:
    process = psutil.Process(os.getpid())
    baseline_rss = process.memory_info().rss
    peak_rss = baseline_rss
    stop = threading.Event()
    sample_interval_s = sample_interval_ms / 1000.0

    def sample_rss() -> None:
        nonlocal peak_rss
        while not stop.wait(sample_interval_s):
            peak_rss = max(peak_rss, process.memory_info().rss)

    sampler = threading.Thread(
        target=sample_rss,
        name="batterylog-rss-sampler",
        daemon=True,
    )
    sampler.start()

    started = perf_counter()
    try:
        result = _run_batterylog_workload(path, mode=mode, report_path=report_path)
    finally:
        peak_rss = max(peak_rss, process.memory_info().rss)
        stop.set()
        sampler.join()
    elapsed = perf_counter() - started
    native_peak_rss = _native_peak_rss_bytes(process)

    if result["validation_status"] != "PASS":
        raise RuntimeError(
            "synthetic MF4 benchmark should pass the configured engineering limits; "
            f"got {result['validation_status']}"
        )

    rows = int(result["rows_analyzed"])
    return {
        "mode": mode,
        "rows": rows,
        "cells": int(result["cells_detected"]),
        "temperature_sensors": int(result["temperature_sensors_detected"]),
        "elapsed_s": elapsed,
        "rows_per_s": rows / elapsed,
        "rss_baseline_bytes": baseline_rss,
        "rss_peak_sampled_bytes": peak_rss,
        "rss_peak_native_bytes": native_peak_rss,
        "rss_delta_sampled_bytes": max(0, peak_rss - baseline_rss),
        "rss_delta_native_bytes": (
            max(0, native_peak_rss - baseline_rss) if native_peak_rss is not None else None
        ),
        "sample_interval_ms": sample_interval_ms,
        "status": result["validation_status"],
        "report_bytes": report_path.stat().st_size if report_path.exists() else None,
    }


def _worker_main(args: argparse.Namespace) -> None:
    payload = _measure_worker(
        Path(args.path),
        mode=args.mode,
        report_path=Path(args.report_path),
        sample_interval_ms=args.sample_interval_ms,
    )
    print(json.dumps(payload, sort_keys=True))


def _invoke_worker(
    path: Path,
    *,
    mode: str,
    report_path: Path,
    sample_interval_ms: float,
) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--path",
            str(path),
            "--mode",
            mode,
            "--report-path",
            str(report_path),
            "--sample-interval-ms",
            str(sample_interval_ms),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _environment_metadata(*, cells: int, temperatures: int) -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "asammdf_version": version("asammdf"),
        "psutil_version": version("psutil"),
        "batterylog_version": version("batterylog"),
        "cells": cells,
        "temperature_sensors": temperatures,
    }


def _print_human_summary(payload: dict[str, Any]) -> None:
    environment = payload["environment"]
    print(
        "environment="
        f"Python {environment['python_version']} / "
        f"asammdf {environment['asammdf_version']} / "
        f"psutil {environment['psutil_version']} / "
        f"{environment['os']}"
    )
    print(
        f"channels={environment['cells']} cells + {environment['temperature_sensors']} temperatures"
    )
    for case in payload["cases"]:
        print(
            f"rows={case['rows']} "
            f"mf4_mib={_mib(case['mf4_bytes']):.1f} "
            f"mode={case['mode']} "
            f"repeat={case['repeat']} "
            f"elapsed_s={case['elapsed_s']:.3f} "
            f"rows_per_s={case['rows_per_s']:.0f} "
            f"rss_baseline_mib={_mib(case['rss_baseline_bytes']):.1f} "
            f"rss_peak_sampled_mib={_mib(case['rss_peak_sampled_bytes']):.1f} "
            + (
                f"rss_peak_native_mib={_mib(case['rss_peak_native_bytes']):.1f} "
                if case["rss_peak_native_bytes"] is not None
                else ""
            )
            + f"rss_delta_sampled_mib={_mib(case['rss_delta_sampled_bytes']):.1f} "
            + (
                f"rss_delta_native_mib={_mib(case['rss_delta_native_bytes']):.1f}"
                if case["rss_delta_native_bytes"] is not None
                else ""
            )
            + (
                f" report_kib={case['report_bytes'] / 1024.0:.1f}"
                if case["report_bytes"] is not None
                else ""
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark end-to-end MDF/MF4 analysis/report throughput, sampled process RSS, "
            "and OS-native peak RSS. "
            "Synthetic MF4 generation runs in the parent; each measured workload runs in a fresh "
            "child process so generator memory does not contaminate the RSS measurement."
        )
    )
    parser.add_argument(
        "--rows",
        nargs="+",
        type=_positive_int,
        default=list(_DEFAULT_ROWS),
        help="One or more sample counts; use at least two sizes to inspect RSS scaling.",
    )
    parser.add_argument("--cells", type=_positive_int, default=_DEFAULT_CELLS)
    parser.add_argument(
        "--temperatures",
        type=_positive_int,
        default=_DEFAULT_TEMPERATURES,
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("analysis", "report"),
        default=["analysis", "report"],
    )
    parser.add_argument(
        "--sample-interval-ms",
        type=_positive_float,
        default=_DEFAULT_SAMPLE_INTERVAL_MS,
        help="RSS sampling interval inside the measured child process.",
    )
    parser.add_argument(
        "--repeats",
        type=_positive_int,
        default=_DEFAULT_REPEATS,
        help="Fresh child-process runs per input-size/mode case.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional path for the complete machine-readable benchmark payload.",
    )

    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--path", help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=("analysis", "report"), help=argparse.SUPPRESS)
    parser.add_argument("--report-path", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        if not args.path or not args.mode or not args.report_path:
            parser.error("--worker requires --path, --mode, and --report-path")
        _worker_main(args)
        return

    rows_values = list(dict.fromkeys(args.rows))
    if len(rows_values) < 2:
        parser.error("benchmark requires at least two distinct --rows values")

    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="batterylog-mf4-benchmark-") as directory:
        root = Path(directory)
        for rows in rows_values:
            mf4_path = root / f"synthetic-{rows}.mf4"
            _write_synthetic_mf4(
                mf4_path,
                rows=rows,
                cells=args.cells,
                temperatures=args.temperatures,
            )
            mf4_bytes = mf4_path.stat().st_size

            for mode in args.modes:
                for repeat in range(1, args.repeats + 1):
                    report_path = root / f"report-{rows}-{mode}-{repeat}.html"
                    case = _invoke_worker(
                        mf4_path,
                        mode=mode,
                        report_path=report_path,
                        sample_interval_ms=args.sample_interval_ms,
                    )
                    case["repeat"] = repeat
                    case["mf4_bytes"] = mf4_bytes
                    cases.append(case)

    payload = {
        "environment": _environment_metadata(
            cells=args.cells,
            temperatures=args.temperatures,
        ),
        "repeats": args.repeats,
        "cases": cases,
    }
    _print_human_summary(payload)

    if args.json_out is not None:
        args.json_out.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
