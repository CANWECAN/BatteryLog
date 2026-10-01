import argparse
import json
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "benchmarks/benchmark_mf4_analysis.py"
BENCHMARK = runpy.run_path(str(SCRIPT))


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1"])
def test_sampling_interval_must_be_positive_and_finite(value) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="finite"):
        BENCHMARK["_positive_float"](value)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux /proc exec-lifetime measurement")
def test_native_peak_excludes_fixture_parent_memory() -> None:
    # Keep the allocation alive during fork/exec. ru_maxrss inherits this peak
    # on Linux, whereas /proc VmHWM belongs to the worker's new address space.
    allocation = bytearray(128 * 1024 * 1024)
    code = (
        "import json,resource,runpy,psutil;from pathlib import Path; "
        f"b=runpy.run_path({str(SCRIPT)!r}); "
        "p=psutil.Process(int(Path('/proc/self').resolve().name)); "
        "print(json.dumps({'measured':b['_native_peak_rss_bytes'](p), "
        "'inherited':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}))"
    )
    measured = json.loads(subprocess.check_output([sys.executable, "-c", code], text=True))
    assert len(allocation) == 128 * 1024 * 1024
    assert measured["inherited"] >= len(allocation)
    assert 0 < measured["measured"] < len(allocation) // 2


def test_linux_without_proc_reports_no_native_peak(monkeypatch) -> None:
    function = BENCHMARK["_native_peak_rss_bytes"]
    monkeypatch.setitem(function.__globals__, "sys", SimpleNamespace(platform="linux"))

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("no proc mount")

    monkeypatch.setattr(Path, "read_text", unavailable)
    process = SimpleNamespace(pid=1, memory_info=lambda: SimpleNamespace(rss=1))
    assert function(process) is None


@pytest.mark.parametrize("status", ["Name:\tpython\n", "VmHWM:\t1234 kB\n"])
def test_linux_native_peak_uses_kib_units_and_handles_missing_field(monkeypatch, status) -> None:
    function = BENCHMARK["_native_peak_rss_bytes"]
    monkeypatch.setitem(function.__globals__, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: status)
    expected = 1234 * 1024 if "VmHWM:" in status else None
    process = SimpleNamespace(pid=1, memory_info=lambda: SimpleNamespace(rss=1))
    assert function(process) == expected
