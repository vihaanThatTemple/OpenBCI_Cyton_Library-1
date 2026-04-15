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


# ---------- Serial transport (real, background thread) ----------

import serial  # pyserial
import serial.tools.list_ports


class SerialWorker:
    """Owns a pyserial.Serial. Runs a background reader thread.

    Implements SerialTransport. Frames are split on EOT_MARKER (b"$$$").
    Bytes between frames are concatenated and emitted as one frame each
    time the marker is seen.
    """

    def __init__(self, port: str) -> None:
        self._port_name = port
        self._ser: Optional[serial.Serial] = None
        self._frames: "queue.Queue[bytes]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._buffer = bytearray()

    def open(self) -> None:
        self._ser = serial.Serial(
            port=self._port_name,
            baudrate=BAUD_RATE,
            timeout=SERIAL_READ_TIMEOUT_S,
        )
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    # SerialTransport interface
    def write(self, data: bytes) -> None:
        if self._ser is None:
            raise RuntimeError("SerialWorker not open")
        self._ser.write(data)
        self._ser.flush()

    def read_frame(self, timeout_s: float) -> bytes:
        try:
            return self._frames.get(timeout=timeout_s)
        except queue.Empty:
            raise ProtocolTimeout(f"no frame within {timeout_s}s on {self._port_name}")

    def drain(self) -> None:
        # Drop any queued frames AND any buffered partial frame.
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                break
        self._buffer.clear()

    # Internal
    def _reader_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(256) if self._ser else b""
            except (serial.SerialException, OSError):
                break
            if not chunk:
                continue
            self._buffer.extend(chunk)
            while True:
                idx = self._buffer.find(EOT_MARKER)
                if idx < 0:
                    break
                end = idx + len(EOT_MARKER)
                frame = bytes(self._buffer[:end])
                del self._buffer[:end]
                self._frames.put(frame)


def list_candidate_ports() -> list[str]:
    """Return all serial ports the OS reports. UI lets the user pick."""
    return [p.device for p in serial.tools.list_ports.comports()]
