"""Tests for auto_detect_port port-scan logic."""

from __future__ import annotations

from typing import Dict

import pytest

from cyton_recorder import (
    EOT_MARKER,
    Protocol,
    ProtocolTimeout,
    auto_detect_port,
)


class FakeWorker:
    """Mimics SerialWorker for auto-detect tests.

    `responses` maps port-name -> bytes to return on read_frame, or None to time out.
    """

    def __init__(self, responses: Dict[str, "bytes | None"]) -> None:
        self._responses = responses
        self._port: str | None = None
        self.opened = False
        self.closed = False

    def __call__(self, port: str) -> "FakeWorker":
        # Each call constructs a new instance bound to that port; for test simplicity
        # we mutate self.
        self._port = port
        return self

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True

    def write(self, data: bytes) -> None:
        pass

    def read_frame(self, timeout_s: float) -> bytes:
        payload = self._responses.get(self._port or "")
        if payload is None:
            raise ProtocolTimeout("no response")
        return payload

    def drain(self) -> None:
        pass


def test_auto_detect_returns_first_responding_port():
    factory = FakeWorker({
        "COM3": None,                         # no reply
        "COM4": b"OpenBCI V3\n" + EOT_MARKER, # reply
        "COM5": b"OpenBCI V3\n" + EOT_MARKER, # reply (but COM4 wins)
    })
    assert auto_detect_port(["COM3", "COM4", "COM5"], worker_factory=factory) == "COM4"


def test_auto_detect_returns_none_when_no_port_replies():
    factory = FakeWorker({"COM3": None, "COM4": None})
    assert auto_detect_port(["COM3", "COM4"], worker_factory=factory) is None


def test_auto_detect_handles_empty_port_list():
    assert auto_detect_port([], worker_factory=lambda p: None) is None


def test_auto_detect_skips_port_that_fails_to_open():
    class FailToOpenWorker(FakeWorker):
        def open(self):
            if self._port == "COM3":
                raise OSError("port in use")
            super().open()

    factory = FailToOpenWorker({"COM4": b"banner" + EOT_MARKER})
    assert auto_detect_port(["COM3", "COM4"], worker_factory=factory) == "COM4"
