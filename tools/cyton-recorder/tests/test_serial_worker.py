"""Tests for SerialWorker frame-splitting on $$$."""

from __future__ import annotations

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
