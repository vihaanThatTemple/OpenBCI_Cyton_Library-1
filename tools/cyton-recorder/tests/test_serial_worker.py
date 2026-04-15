"""Tests for SerialWorker frame-splitting on $$$."""

from __future__ import annotations

import threading
import time
from typing import List
from unittest.mock import patch

import pytest

from cyton_recorder import SerialWorker, ProtocolTimeout


class StubSerial:
    """Mimics pyserial.Serial.read/write/flush/close.

    `script` is a list of byte chunks the reader thread will see, one per read() call.
    After the script is exhausted, read() returns b"" forever (mimicking a timeout).
    """

    def __init__(self, script: List[bytes]) -> None:
        self.script = list(script)
        self.writes: List[bytes] = []
        self.closed = False

    def read(self, n: int) -> bytes:
        if self.script:
            return self.script.pop(0)
        time.sleep(0.01)  # mimic read timeout
        return b""

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def make_worker(stub: StubSerial) -> SerialWorker:
    w = SerialWorker(port="STUB")
    with patch("cyton_recorder.serial.Serial", return_value=stub):
        w.open()
    return w


def test_single_frame_is_emitted():
    stub = StubSerial([b"hello world$$$"])
    w = make_worker(stub)
    try:
        frame = w.read_frame(timeout_s=1.0)
        assert frame == b"hello world$$$"
    finally:
        w.close()


def test_frame_split_across_chunks():
    stub = StubSerial([b"hel", b"lo wo", b"rld$", b"$$"])
    w = make_worker(stub)
    try:
        frame = w.read_frame(timeout_s=1.0)
        assert frame == b"hello world$$$"
    finally:
        w.close()


def test_two_frames_in_one_chunk():
    stub = StubSerial([b"first$$$second$$$"])
    w = make_worker(stub)
    try:
        assert w.read_frame(timeout_s=1.0) == b"first$$$"
        assert w.read_frame(timeout_s=1.0) == b"second$$$"
    finally:
        w.close()


def test_read_frame_timeout_raises():
    stub = StubSerial([])
    w = make_worker(stub)
    try:
        with pytest.raises(ProtocolTimeout):
            w.read_frame(timeout_s=0.2)
    finally:
        w.close()


def test_drain_clears_buffered_partial_and_queued_frames():
    stub = StubSerial([b"complete$$$partial-no-marker"])
    w = make_worker(stub)
    try:
        # Wait for the reader thread to process both chunks.
        time.sleep(0.1)
        w.drain()
        with pytest.raises(ProtocolTimeout):
            w.read_frame(timeout_s=0.2)
    finally:
        w.close()


def test_write_forwards_to_serial():
    stub = StubSerial([])
    w = make_worker(stub)
    try:
        w.write(b"v")
        assert stub.writes == [b"v"]
    finally:
        w.close()


def test_buffer_lock_prevents_concurrent_drain_corruption():
    """Verify that calling drain() concurrently with the reader thread does
    not raise an exception and leaves the buffer in a clean (empty) state.

    We feed a long repeating script so the reader thread is busy extending
    the buffer while the main thread calls drain() repeatedly.
    """
    # Build a script of many small chunks so the reader keeps running.
    chunk = b"ABCDEFGHIJ"  # no $$$ marker — keeps filling the buffer
    script = [chunk] * 500
    stub = StubSerial(script)
    w = make_worker(stub)
    try:
        # Let the reader thread fill the buffer a bit.
        time.sleep(0.05)

        errors = []

        def drain_repeatedly():
            for _ in range(20):
                try:
                    w.drain()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                time.sleep(0.001)

        drainer = threading.Thread(target=drain_repeatedly)
        drainer.start()
        drainer.join(timeout=2.0)

        assert not errors, f"drain() raised exceptions concurrently: {errors}"

        # After drain finishes, the buffer should be clean (empty or nearly so).
        # Give the reader one more tick, then drain again and confirm no frames.
        time.sleep(0.05)
        w.drain()
        with pytest.raises(ProtocolTimeout):
            w.read_frame(timeout_s=0.1)
    finally:
        w.close()
