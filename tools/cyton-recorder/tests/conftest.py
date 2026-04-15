"""Pytest fixtures for cyton_recorder tests."""

from __future__ import annotations

import queue
import threading
import time
from typing import List

import pytest

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cyton_recorder import EOT_MARKER, ProtocolTimeout


class FakeSerial:
    """In-memory SerialTransport for protocol tests.

    - `writes` records every byte string sent by the Protocol layer.
    - `queue_response(bytes)` enqueues a frame the next read_frame() call returns.
    - `read_frame()` blocks up to `timeout_s` waiting for an enqueued frame.
    """

    def __init__(self) -> None:
        self.writes: List[bytes] = []
        self._frames: "queue.Queue[bytes]" = queue.Queue()
        self.drained = 0

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def read_frame(self, timeout_s: float) -> bytes:
        try:
            return self._frames.get(timeout=timeout_s)
        except queue.Empty:
            raise ProtocolTimeout(f"no frame within {timeout_s}s")

    def drain(self) -> None:
        self.drained += 1

    # Test helpers
    def queue_response(self, payload: bytes) -> None:
        self._frames.put(payload)

    def queue_response_after(self, delay_s: float, payload: bytes) -> None:
        threading.Timer(delay_s, lambda: self._frames.put(payload)).start()


@pytest.fixture
def fake_serial() -> FakeSerial:
    return FakeSerial()
