"""Exercise real batch cancellation with combined state models on both platforms."""

import hashlib
import json
import signal
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from batterylog.desktop_batch_results import read_batch_rows
from batterylog.desktop_job import DesktopBatchJob

CONFIG = """schema_version: 7
limits:
  cell_voltage:
    max_v: 4.2
failure_models:
  max_gap_s: 1
  balancing:
    active_source: Bal
    evaluation_s: 2
    min_improvement_v: 0.1
    min_start_delta_v: 0.2
    timeout_s: 3
  unloaded_current:
    unloaded_source: Unload
    max_abs_current_a: 0.5
    duration_s: 2
  contactor_response:
    command_source: Cmd
    feedback_source: Feedback
    response_timeout_s: 2
  precharge_current:
    active_source: Phase
    evaluation_s: 2
    min_start_abs_current_a: 4
    min_drop_a: 3
"""


def frame(count):
    t = np.arange(count)
    phase = t % 6
    active = ((phase >= 1) & (phase <= 3)).astype(int)
    return pd.DataFrame(
        {
            "timestamp_s": t,
            "cell_1_v": np.full(count, 3.5),
            "cell_2_v": 3.5 - np.where(phase == 3, 0.125, 0.25),
            "temp_c": np.full(count, 25.0),
            "pack_current_a": np.where(phase == 1, 6.0, np.where(phase == 2, 3.0, 0.0)),
            "Bal": active,
            "Unload": np.ones(count, dtype=int),
            "Cmd": active,
            "Feedback": active,
            "Phase": active,
        }
    )


records = []
for index, (ignored, recursive, first) in enumerate(
    [
        (False, False, "=ready.csv"),
        (True, False, "'=ready.csv"),
        (False, True, "0,ölçüm/=ready.csv"),
    ]
):
    with TemporaryDirectory(prefix="batterylog-cancel-audit-") as d:
        root = Path(d)
        inputs = root / "inputs"
        outputs = root / "outputs"
        inputs.mkdir()
        outputs.mkdir()
        config = root / "models.yaml"
        config.write_text(CONFIG, encoding="utf-8")
        small = inputs / first
        small.parent.mkdir(parents=True, exist_ok=True)
        frame(6).to_csv(small, index=False)
        long = inputs / "b_long.csv"
        frame(300000).to_csv(long, index=False)
        pending = inputs / "z_pending.csv"
        frame(6).to_csv(pending, index=False)
        original = hashlib.sha256(small.read_bytes()).hexdigest()
        inherited = signal.getsignal(signal.SIGINT)
        try:
            if ignored:
                signal.signal(signal.SIGINT, signal.SIG_IGN)
            job = DesktopBatchJob(inputs, outputs, config, recursive=recursive)
        finally:
            signal.signal(signal.SIGINT, inherited)
        report = job.directory / "files" / first / "report.html"
        deadline = time.monotonic() + 30
        while not report.is_file():
            early = job.poll()
            assert early is None, ("worker ended before cancellation", early)
            assert time.monotonic() < deadline, "first report timeout"
            time.sleep(0.01)
        time.sleep(0.075)  # Allow the first returned summary record to be committed.
        started = time.monotonic()
        job.cancel()
        outcome = None
        while outcome is None:
            outcome = job.poll()
            assert time.monotonic() - started < 10, "cancellation timeout"
            time.sleep(0.01)
        assert outcome.status == "CANCELLED", outcome
        assert outcome.summary_csv is not None
        rows = read_batch_rows(outcome)
        assert [row.source for row in rows] == [first, "b_long.csv", "z_pending.csv"], rows
        assert [row.status for row in rows] == ["PASS", "NOT_PROCESSED", "NOT_PROCESSED"], rows
        assert [row.violation_events for row in rows] == [0, None, None], rows
        assert rows[0].report == report and report.is_file()
        assert rows[1].report is None and rows[2].report is None
        assert original == hashlib.sha256(small.read_bytes()).hexdigest()
        assert job.poll() is outcome
        assert not job._directory.exists()
        records.append(
            {
                "case": index,
                "inherited_sigint_ignore": ignored,
                "recursive": recursive,
                "retained_statuses": [row.status for row in rows],
                "cancel_seconds": round(time.monotonic() - started, 3),
            }
        )
print(json.dumps(records, ensure_ascii=False))
