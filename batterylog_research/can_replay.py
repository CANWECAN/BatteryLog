# Copyright (c) 2026 Berk Ozfiliz
# SPDX-License-Identifier: Apache-2.0
"""Pull-based classic CAN replay and bounded recording; software lifecycle only."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import deque
from decimal import Decimal
from pathlib import Path

from batterylog_research.can_prepare import Frame, publish_new_file, read_frames, sha256


class Replay:
    """Read in source order without waiting, retiming, decoding, or a CAN interface."""

    def __init__(self, source):
        self._frames = read_frames(source)
        self.state = "running"

    def __iter__(self):
        return self

    def __next__(self):
        if self.state in {"stopped", "eof"}:
            raise StopIteration
        if self.state != "running":
            raise RuntimeError(f"Cannot read replay in state {self.state}")
        try:
            return next(self._frames)
        except StopIteration:
            self.state = "eof"
            raise
        except Exception:
            self.state = "failed"
            raise

    def pause(self):
        if self.state != "running":
            raise RuntimeError("Only a running replay can pause")
        self.state = "paused"

    def resume(self):
        if self.state != "paused":
            raise RuntimeError("Only a paused replay can resume")
        self.state = "running"

    def stop(self):
        if self.state in {"running", "paused"}:
            self.state = "stopped"


def _frame_record(frame, sequence, segment):
    if (
        not isinstance(frame, Frame)
        or type(frame.line) is not int
        or frame.line < 1
        or not isinstance(frame.timestamp, Decimal)
        or not frame.timestamp.is_finite()
        or frame.timestamp.is_signed()
        or frame.timestamp.adjusted() > 17
        or frame.timestamp.as_tuple().exponent < -9
        or type(frame.frame_id) is not int
        or not isinstance(frame.extended, bool)
        or not isinstance(frame.bus, str)
        or not isinstance(frame.data, bytes)
        or len(frame.data) > 8
    ):
        raise ValueError("Require a valid immutable classic CAN Frame")
    identifier = f"{frame.frame_id:08X}" if frame.extended else f"{frame.frame_id:03X}"
    encoded = f"({frame.timestamp:f}) {frame.bus} {identifier}#{frame.data.hex()}"
    # Reuse the transport contract, including identifier width/range and bus syntax.
    next(read_frames([encoded]))
    return {
        "sequence": sequence,
        "source_segment": segment,
        "source_line": frame.line,
        "timestamp_as_recorded": str(frame.timestamp),
        "bus": frame.bus,
        "frame_id": frame.frame_id,
        "extended": frame.extended,
        "data_hex": frame.data.hex(),
    }


class Recorder:
    """Single-owner queue and file writer; no background worker or hardware backend."""

    def __init__(self, output_dir, *, capacity=1024):
        if type(capacity) is not int or not 1 <= capacity <= 100_000:
            raise ValueError("capacity must be an integer from 1 to 100000")
        self.directory = Path(output_dir)
        self.directory.mkdir()
        self._partial = self.directory / "frames.jsonl.part"
        self._writer = self._partial.open("xb")
        self._queue = deque()
        self.capacity = capacity
        self.state = "running"
        self.received = self.accepted = self.written = self.dropped = self.invalid = 0
        self.peak_pending = self.disconnects = 0
        self.segment = 1
        self._previous_time = None
        self._first_drop = self._last_drop = None
        self._error = self._report = None
        self._finalized = False

    @property
    def pending(self):
        return len(self._queue)

    def _fail(self, error):
        self.state = "failed"
        if self._error is None:
            self._error = {"type": type(error).__name__, "message": str(error)}

    def offer(self, frame):
        if self.state != "running":
            raise RuntimeError(f"Cannot offer a frame in state {self.state}")
        self.received += 1
        try:
            record = _frame_record(frame, self.received, self.segment)
            if self._previous_time is not None and frame.timestamp < self._previous_time:
                raise ValueError("Timestamp decreases within a source segment")
            row = (json.dumps(record, allow_nan=False) + "\n").encode("utf-8")
            if len(row) > 4096:
                raise ValueError("CAN journal record exceeds the 4096-byte bound")
        except (TypeError, ValueError, OverflowError) as error:
            self.invalid += 1
            self._fail(error)
            raise
        self._previous_time = frame.timestamp
        if self.pending == self.capacity:
            self.dropped += 1
            self._last_drop = {"sequence": self.received, "source_line": frame.line}
            if self._first_drop is None:
                self._first_drop = self._last_drop
            return False
        self._queue.append(row)
        self.accepted += 1
        self.peak_pending = max(self.peak_pending, self.pending)
        return True

    def drain(self):
        if self.state not in {"running", "disconnected"}:
            raise RuntimeError(f"Cannot drain a recorder in state {self.state}")
        try:
            while self._queue:
                row = self._queue[0]
                if self._writer.write(row) != len(row):
                    raise OSError("Short CAN journal write; partial record retained")
                self._queue.popleft()
                self.written += 1
            self._writer.flush()
        except (OSError, ValueError) as error:
            self._fail(error)
            raise

    def disconnect(self):
        if self.state != "running":
            raise RuntimeError("Only a running recorder can disconnect")
        self.state = "disconnected"
        self.disconnects += 1

    def reconnect(self):
        if self.state != "disconnected":
            raise RuntimeError("Only a disconnected recorder can reconnect")
        self.segment += 1
        self._previous_time = None
        self.state = "running"

    def finish(self, *, reason="eof", error=None, source=None):
        """Publish a manifest last; incomplete sessions retain a .part data file."""
        if self._report is not None:
            return self._report
        if self._finalized:
            raise RuntimeError("Failed finalization cannot be retried")
        if reason not in {"eof", "stopped", "source_error"}:
            raise ValueError("Unsupported recording finish reason")
        self._finalized = True
        try:
            if self.state != "failed":
                self.drain()
        except (OSError, ValueError):
            pass  # drain retained the original error and pending count
        try:
            self._writer.close()
        except OSError as close_error:
            self._fail(close_error)
        if error is not None:
            self._fail(error)
        if reason == "source_error" and self.state != "failed":
            self._fail(RuntimeError("Source failed without further error detail"))
        if self.state == "failed":
            status = "failed"
        elif reason == "stopped":
            status = "stopped"
        elif self.disconnects or self.dropped:
            status = "finished_with_gaps"
        else:
            status = "complete"
        self.state = "failed"  # Publication must succeed before a final state is visible.
        data = self._partial
        if status == "complete":
            target = self.directory / "frames.jsonl"
            try:
                publish_new_file(data, target)
                data = target
                self._partial.unlink()
            except OSError as publish_error:
                self._fail(publish_error)
                status = "failed"
        report = {
            "format": "batterylog-offline-can-session-v1",
            "scope": "software_recording_lifecycle_only",
            "hardware_validated": False,
            "status": status,
            "complete": status == "complete",
            "source_eof": reason == "eof",
            "source": source,
            "queue_capacity": self.capacity,
            "peak_pending": self.peak_pending,
            "received_frames": self.received,
            "accepted_frames": self.accepted,
            "written_frames": self.written,
            "dropped_frames": self.dropped,
            "invalid_frames": self.invalid,
            "pending_frames": self.pending,
            "source_segments": self.segment,
            "source_disconnects": self.disconnects,
            "first_dropped_frame": self._first_drop,
            "last_dropped_frame": self._last_drop,
            "data_file": data.name,
            "data_sha256": sha256(data),
            "error": self._error,
        }
        staged = self.directory / "session.json.part"
        with staged.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
        publish_new_file(staged, self.directory / "session.json")
        staged.unlink()
        self.state, self._report = status, report
        return report


def replay_paths(source_path, output_dir, *, capacity=1024, stop_after=None):
    """Hash exactly the source bytes consumed, including a rejected source line."""
    if stop_after is not None and (type(stop_after) is not int or stop_after < 1):
        raise ValueError("stop_after must be a positive integer")
    source_path = Path(source_path)
    digest = hashlib.sha256()
    consumed = 0
    with source_path.open("rb") as source:
        recorder = Recorder(output_dir, capacity=capacity)

        def lines():
            nonlocal consumed
            while raw := source.readline(4097):
                digest.update(raw)
                consumed += len(raw)
                if len(raw) > 4096:
                    raise ValueError("CAN source line exceeds the 4096-byte bound")
                yield raw.decode("utf-8")

        replay = Replay(lines())

        def identity():
            return {
                "name": source_path.name,
                "consumed_bytes": consumed,
                "consumed_sha256": digest.hexdigest(),
                "fully_consumed": replay.state == "eof",
            }

        reason = "eof"
        try:
            for frame in replay:
                recorder.offer(frame)
                if recorder.pending == capacity:
                    recorder.drain()
                if stop_after is not None and recorder.received == stop_after:
                    replay.stop()
                    reason = "stopped"
                    break
        except KeyboardInterrupt:
            recorder.finish(reason="stopped", source=identity())
            raise
        except Exception as error:
            recorder.finish(reason="source_error", error=error, source=identity())
            raise
        return recorder.finish(reason=reason, source=identity())


def main(argv=None, *, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--capacity", type=int, default=1024)
    parser.add_argument("--stop-after", type=int)
    args = parser.parse_args(argv)
    try:
        report = replay_paths(
            args.source, args.output_dir, capacity=args.capacity, stop_after=args.stop_after
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"status": report["status"], "written_frames": report["written_frames"]}))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
