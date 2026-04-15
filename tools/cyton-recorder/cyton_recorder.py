"""Cyton Recorder — Windows app for 1000 Hz SD-only EEG capture.

Single-file design: SerialWorker (background thread, owns COM port),
Protocol (sync wrapper), RecorderApp (Tkinter UI + state machine).
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional, Protocol as TypingProtocol

# ---------- Firmware protocol constants ----------

EOT_MARKER = b"$$$"
HANDSHAKE_CMD = b"v"
START_CMD = b"b"
STOP_CMD = b"j"

# Duration command letters — must match examples/BoardSDOnly1000Hz/SD_Card_Stuff.ino
DURATION_COMMANDS = {
    "5 min":  b"A",
    "15 min": b"S",
    "30 min": b"F",
    "1 hr":   b"G",
    "2 hr":   b"H",
    "4 hr":   b"J",
}

DURATION_SECONDS = {
    "5 min":  5 * 60,
    "15 min": 15 * 60,
    "30 min": 30 * 60,
    "1 hr":   60 * 60,
    "2 hr":   2 * 60 * 60,
    "4 hr":   4 * 60 * 60,
}

DEFAULT_DURATION = "15 min"

# Timeouts (seconds)
HANDSHAKE_TIMEOUT_S = 5.0
FILE_OPEN_TIMEOUT_S = 3.0
STREAM_STOP_TIMEOUT_S = 5.0

# Serial settings
BAUD_RATE = 115200
SERIAL_READ_TIMEOUT_S = 0.1


class ProtocolError(Exception):
    """Base class for protocol failures."""


class ProtocolTimeout(ProtocolError):
    """Board did not return $$$ within the expected window."""


# ---------- Serial transport interface ----------

class SerialTransport(TypingProtocol):
    """Minimal interface the Protocol layer requires.

    The real implementation is SerialWorker (Task 4). Tests use FakeSerial.
    """

    def write(self, data: bytes) -> None: ...
    def read_frame(self, timeout_s: float) -> bytes:
        """Block until a $$$-terminated frame arrives, or raise ProtocolTimeout."""
        ...
    def drain(self) -> None:
        """Discard any buffered incoming bytes."""
        ...


# ---------- Protocol layer ----------

@dataclass
class Protocol:
    transport: SerialTransport

    def handshake(self) -> bytes:
        self.transport.drain()
        self.transport.write(HANDSHAKE_CMD)
        return self.transport.read_frame(HANDSHAKE_TIMEOUT_S)

    def arm(self, duration_label: str) -> bytes:
        if duration_label not in DURATION_COMMANDS:
            raise ValueError(f"Unknown duration: {duration_label!r}")
        self.transport.drain()
        self.transport.write(DURATION_COMMANDS[duration_label])
        return self.transport.read_frame(FILE_OPEN_TIMEOUT_S)

    def start(self) -> None:
        # 'b' produces no $$$ response — streaming begins silently.
        self.transport.write(START_CMD)

    def stop(self) -> bytes:
        self.transport.write(STOP_CMD)
        return self.transport.read_frame(STREAM_STOP_TIMEOUT_S)
