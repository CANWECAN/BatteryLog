"""Authored software lifecycle checks; no bus adapter or physical validation."""

import hashlib
import io
import json
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from batterylog_research.can_prepare import Frame
from batterylog_research.can_replay import Recorder, Replay, replay_paths

RAW = (
    b"(1800000000.000000001) can0 123#00ff\r\n"
    b"(1800000000.000000002) can1 00000123#1020304050607080\n"
    b"(1800000000.000000002) can0 7FF#\n"
)


def frame(index=1, timestamp=None):
    return Frame(
        index,
        Decimal(str(index) if timestamp is None else timestamp),
        "can0",
        0x123,
        False,
        b"\x12\x34",
    )


def manifest(directory):
    return json.loads((directory / "session.json").read_text())


def records(directory, report):
    return [json.loads(line) for line in (directory / report["data_file"]).read_text().splitlines()]


def test_replay_pause_resume_stop_does_not_read_ahead():
    consumed = []

    def lines():
        for index, line in enumerate(RAW.decode().splitlines(True)):
            consumed.append(index)
            yield line

    replay = Replay(lines())
    assert next(replay).line == 1
    replay.pause()
    with pytest.raises(RuntimeError, match="paused"):
        next(replay)
    assert consumed == [0]
    replay.resume()
    assert next(replay).data == bytes.fromhex("1020304050607080")
    replay.stop()
    assert list(replay) == []
    assert consumed == [0, 1]
    assert replay.state == "stopped"
    with pytest.raises(RuntimeError):
        replay.resume()


def test_replay_eof_and_failed_source_are_distinct():
    empty = Replay([])
    assert list(empty) == []
    assert empty.state == "eof"
    empty.stop()
    assert empty.state == "eof"

    def broken():
        yield "(1) can0 123#12"
        raise ConnectionError("authored source disconnected")

    replay = Replay(broken())
    next(replay)
    with pytest.raises(ConnectionError):
        next(replay)
    assert replay.state == "failed"
    with pytest.raises(RuntimeError):
        next(replay)


@pytest.mark.parametrize("operation", ["pause", "resume"])
def test_invalid_replay_controls_do_not_consume(operation):
    replay = Replay([])
    if operation == "pause":
        replay.pause()
    with pytest.raises(RuntimeError):
        getattr(replay, operation)()


@pytest.mark.parametrize("capacity", [1, 2, 1024])
def test_file_replay_preserves_exact_fields_and_bytes_identity(tmp_path, capacity):
    source = tmp_path / "capture.log"
    source.write_bytes(RAW)
    output = tmp_path / "session"
    report = replay_paths(source, output, capacity=capacity)
    assert report == manifest(output)
    assert report["complete"] and report["status"] == "complete"
    assert report["source_eof"] and report["source"]["fully_consumed"]
    assert report["source"]["consumed_sha256"] == hashlib.sha256(RAW).hexdigest()
    assert report["source"]["consumed_bytes"] == len(RAW)
    assert report["written_frames"] == report["accepted_frames"] == report["received_frames"] == 3
    assert report["dropped_frames"] == report["pending_frames"] == report["invalid_frames"] == 0
    assert report["peak_pending"] <= capacity
    result = records(output, report)
    assert [r["timestamp_as_recorded"] for r in result] == [
        "1800000000.000000001",
        "1800000000.000000002",
        "1800000000.000000002",
    ]
    assert [r["source_line"] for r in result] == [1, 2, 3]
    assert [r["sequence"] for r in result] == [1, 2, 3]
    assert [r["bus"] for r in result] == ["can0", "can1", "can0"]
    assert [r["extended"] for r in result] == [False, True, False]
    assert [r["data_hex"] for r in result] == ["00ff", "1020304050607080", ""]
    assert (
        report["data_sha256"] == hashlib.sha256((output / "frames.jsonl").read_bytes()).hexdigest()
    )
    assert not list(output.glob("*.part"))
    assert source.read_bytes() == RAW


@pytest.mark.parametrize("count", [1, 3])
def test_stop_keeps_partial_and_hashes_only_consumed_source(tmp_path, count):
    source = tmp_path / "capture.log"
    source.write_bytes(RAW)
    output = tmp_path / "session"
    report = replay_paths(source, output, stop_after=count)
    prefix = b"".join(RAW.splitlines(True)[:count])
    assert report["status"] == "stopped"
    assert not report["complete"] and not report["source_eof"]
    assert not report["source"]["fully_consumed"]
    assert report["source"]["consumed_sha256"] == hashlib.sha256(prefix).hexdigest()
    assert report["source"]["consumed_bytes"] == len(prefix)
    assert report["data_file"] == "frames.jsonl.part"
    assert len(records(output, report)) == count
    assert not (output / "frames.jsonl").exists()


def test_queue_overflow_is_counted_and_does_not_drop_accepted_frames(tmp_path):
    recorder = Recorder(tmp_path / "session", capacity=2)
    assert recorder.offer(frame(1))
    assert recorder.offer(frame(2))
    assert not recorder.offer(frame(3))
    assert not recorder.offer(frame(4))
    recorder.drain()
    assert recorder.offer(frame(5))
    report = recorder.finish()
    assert report["status"] == "finished_with_gaps" and not report["complete"]
    assert report["received_frames"] == 5 and report["dropped_frames"] == 2
    assert report["written_frames"] == report["accepted_frames"] == 3
    assert report["peak_pending"] == 2
    assert report["first_dropped_frame"] == {"sequence": 3, "source_line": 3}
    assert report["last_dropped_frame"] == {"sequence": 4, "source_line": 4}
    assert [r["sequence"] for r in records(recorder.directory, report)] == [1, 2, 5]
    assert recorder.finish() is report
    with pytest.raises(RuntimeError):
        recorder.offer(frame(6))


def test_disconnect_reconnect_retains_segment_boundary_and_clock_reset(tmp_path):
    recorder = Recorder(tmp_path / "session")
    recorder.offer(frame(1, "100"))
    recorder.disconnect()
    with pytest.raises(RuntimeError):
        recorder.offer(frame(2, "101"))
    recorder.drain()
    recorder.reconnect()
    recorder.offer(frame(1, "0"))
    report = recorder.finish()
    assert not report["complete"]
    assert report["source_disconnects"] == 1 and report["source_segments"] == 2
    result = records(recorder.directory, report)
    assert [r["source_segment"] for r in result] == [1, 2]
    assert [r["timestamp_as_recorded"] for r in result] == ["100", "0"]
    assert [r["source_line"] for r in result] == [1, 1]


def test_clock_reversal_in_one_segment_fails_even_after_a_dropped_frame(tmp_path):
    recorder = Recorder(tmp_path / "session", capacity=1)
    recorder.offer(frame(1, "10"))
    assert not recorder.offer(frame(2, "20"))
    with pytest.raises(ValueError, match="decreases"):
        recorder.offer(frame(3, "15"))
    report = recorder.finish()
    assert report["status"] == "failed"
    assert report["received_frames"] == 3
    assert report["accepted_frames"] == report["dropped_frames"] == report["invalid_frames"] == 1
    assert report["pending_frames"] == 1 and report["written_frames"] == 0


@pytest.mark.parametrize("capacity", [True, 0, -1, 1.0, 100001])
def test_invalid_capacity_creates_nothing(tmp_path, capacity):
    output = tmp_path / "session"
    with pytest.raises(ValueError):
        Recorder(output, capacity=capacity)
    assert not output.exists()


@pytest.mark.parametrize("count", [True, 0, -1, 1.0])
def test_invalid_stop_limit_creates_nothing(tmp_path, count):
    output = tmp_path / "session"
    with pytest.raises(ValueError):
        replay_paths(tmp_path / "missing.log", output, stop_after=count)
    assert not output.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"line": False},
        {"line": 0},
        {"timestamp": Decimal("NaN")},
        {"timestamp": Decimal("Infinity")},
        {"timestamp": Decimal("-0")},
        {"timestamp": Decimal("1e18")},
        {"timestamp": Decimal("1e-10")},
        {"frame_id": True},
        {"frame_id": 0x800},
        {"extended": 1},
        {"bus": "bad bus"},
        {"data": bytearray(b"x")},
        {"data": bytes(9)},
        {"bus": "x" * 4100},
    ],
)
def test_invalid_frame_cannot_be_finalized_as_complete(tmp_path, changes):
    recorder = Recorder(tmp_path / "session")
    with pytest.raises(ValueError):
        recorder.offer(replace(frame(), **changes))
    report = recorder.finish()
    assert not report["complete"] and report["status"] == "failed"
    assert report["invalid_frames"] == 1 and report["accepted_frames"] == 0


class BrokenWriter:
    def __init__(self, raw, mode):
        self.raw, self.mode = raw, mode

    def write(self, data):
        if self.mode == "write":
            raise OSError("authored disk full")
        if self.mode == "short":
            return self.raw.write(data[:3])
        return self.raw.write(data)

    def flush(self):
        if self.mode == "flush":
            raise OSError("authored flush failure")
        self.raw.flush()

    def close(self):
        self.raw.close()
        if self.mode == "close":
            raise OSError("authored close failure")


@pytest.mark.parametrize("mode", ["write", "short", "flush", "close"])
def test_disk_failures_preserve_partial_and_never_retry_writes(tmp_path, mode):
    recorder = Recorder(tmp_path / "session")
    recorder._writer = BrokenWriter(recorder._writer, mode)
    recorder.offer(frame(1))
    recorder.offer(frame(2))
    if mode != "close":
        with pytest.raises(OSError):
            recorder.drain()
    report = recorder.finish()
    assert report["status"] == "failed" and not report["complete"]
    assert report["data_file"].endswith(".part")
    assert report["error"]["type"] == "OSError"
    assert report["accepted_frames"] == report["written_frames"] + report["pending_frames"]
    before = (recorder.directory / report["data_file"]).read_bytes()
    assert recorder.finish() is report
    assert (recorder.directory / report["data_file"]).read_bytes() == before


def test_existing_data_target_is_not_overwritten(tmp_path):
    recorder = Recorder(tmp_path / "session")
    recorder.offer(frame())
    target = recorder.directory / "frames.jsonl"
    target.write_bytes(b"existing data")
    report = recorder.finish()
    assert not report["complete"] and report["error"]["type"] == "FileExistsError"
    assert target.read_bytes() == b"existing data"
    assert report["data_file"] == "frames.jsonl.part"


def test_manifest_publication_failure_latches_failed_and_refuses_retry(tmp_path):
    recorder = Recorder(tmp_path / "session")
    recorder.offer(frame())
    target = recorder.directory / "session.json"
    target.write_bytes(b"existing manifest")
    with pytest.raises(FileExistsError):
        recorder.finish()
    assert recorder.state == "failed"
    assert target.read_bytes() == b"existing manifest"
    with pytest.raises(RuntimeError, match="cannot be retried"):
        recorder.finish()
    with pytest.raises(RuntimeError):
        recorder.offer(frame())


@pytest.mark.parametrize("bad", [b"bad CAN record\n", b"\xff\n", b"(0) can0 123#00\n"])
def test_failed_source_retains_valid_prefix_and_consumed_hash(tmp_path, bad):
    first, _, last = RAW.splitlines(True)
    source = tmp_path / "capture.log"
    source.write_bytes(first + bad + last)
    output = tmp_path / "session"
    with pytest.raises(ValueError):
        replay_paths(source, output)
    report = manifest(output)
    assert not report["complete"] and report["status"] == "failed"
    assert not report["source_eof"] and not report["source"]["fully_consumed"]
    assert report["source"]["consumed_sha256"] == hashlib.sha256(first + bad).hexdigest()
    assert report["written_frames"] == 1
    assert len(records(output, report)) == 1


def test_overlong_source_line_is_read_with_a_bound(tmp_path):
    source = tmp_path / "capture.log"
    source.write_bytes(b"x" * 100_000)
    output = tmp_path / "session"
    with pytest.raises(ValueError, match="4096"):
        replay_paths(source, output)
    report = manifest(output)
    assert report["source"]["consumed_bytes"] == 4097
    assert not report["source"]["fully_consumed"]


def test_empty_source_finishes_transport_without_measurement_claim(tmp_path):
    source = tmp_path / "empty.log"
    source.write_bytes(b"")
    report = replay_paths(source, tmp_path / "session")
    assert report["complete"] and report["written_frames"] == 0
    assert report["scope"] == "software_recording_lifecycle_only"
    assert report["hardware_validated"] is False


@pytest.mark.parametrize("stop", [False, True])
def test_real_cli_and_existing_output_refusal(tmp_path, stop):
    source = tmp_path / "capture.log"
    source.write_bytes(RAW)
    output = tmp_path / "session"
    args = [sys.executable, "-m", "batterylog_research.can_replay", str(source), str(output)]
    if stop:
        args += ["--stop-after", "1"]
    result = subprocess.run(
        args, cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False
    )
    assert result.returncode == int(stop), result.stderr
    report = manifest(output)
    assert json.loads(result.stdout)["status"] == report["status"]
    original = {p.name: p.read_bytes() for p in output.iterdir()}
    repeated = subprocess.run(
        args, cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False
    )
    assert repeated.returncode == 2
    assert {p.name: p.read_bytes() for p in output.iterdir()} == original
    assert source.read_bytes() == RAW


def test_disconnected_source_finishes_with_gap_even_without_reconnect(tmp_path):
    recorder = Recorder(tmp_path / "session")
    recorder.offer(frame())
    recorder.disconnect()
    with pytest.raises(RuntimeError):
        recorder.disconnect()
    report = recorder.finish()
    assert report["status"] == "finished_with_gaps"
    assert report["source_disconnects"] == 1
    assert report["written_frames"] == 1


def test_invalid_reconnect_and_finish_reason_leave_session_usable(tmp_path):
    recorder = Recorder(tmp_path / "session")
    with pytest.raises(RuntimeError):
        recorder.reconnect()
    with pytest.raises(ValueError):
        recorder.finish(reason="pretend_complete")
    assert recorder.state == "running"
    recorder.offer(frame())
    assert recorder.finish()["complete"]


def test_source_failure_without_detail_cannot_claim_completion(tmp_path):
    recorder = Recorder(tmp_path / "session")
    recorder.offer(frame())
    report = recorder.finish(reason="source_error")
    assert report["status"] == "failed"
    assert report["error"]["type"] == "RuntimeError"
    assert report["written_frames"] == 1


def test_failed_writer_drain_is_not_retried(tmp_path):
    recorder = Recorder(tmp_path / "session")
    recorder._writer = BrokenWriter(recorder._writer, "short")
    recorder.offer(frame())
    with pytest.raises(OSError):
        recorder.drain()
    recorder._writer.raw.flush()
    before = recorder._partial.read_bytes()
    with pytest.raises(RuntimeError):
        recorder.drain()
    recorder.finish()
    assert recorder._partial.read_bytes() == before


def test_keyboard_interrupt_publishes_stopped_prefix_then_reraises(tmp_path, monkeypatch):
    source = tmp_path / "capture.log"
    source.write_bytes(RAW)
    first = RAW.splitlines(True)[0]

    class InterruptedFile(io.BytesIO):
        def readline(self, size=-1):
            if self.tell():
                raise KeyboardInterrupt
            return super().readline(size)

    original_open = Path.open

    def controlled_open(path, *args, **kwargs):
        if path == source:
            return InterruptedFile(RAW)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", controlled_open)
    output = tmp_path / "session"
    with pytest.raises(KeyboardInterrupt):
        replay_paths(source, output)
    report = manifest(output)
    assert report["status"] == "stopped" and not report["complete"]
    assert report["written_frames"] == 1
    assert report["source"]["consumed_sha256"] == hashlib.sha256(first).hexdigest()
    assert not report["source"]["fully_consumed"]
