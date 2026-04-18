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
FILE_OPEN_TIMEOUT_S = 30.0
STREAM_STOP_TIMEOUT_S = 5.0

# Serial settings
BAUD_RATE = 115200
SERIAL_READ_TIMEOUT_S = 0.1


class ProtocolError(Exception):
    """Base class for protocol failures."""


class ProtocolTimeout(ProtocolError):
    """Board did not return $$$ within the expected window."""


class SDCardError(ProtocolError):
    """Firmware emitted a known SD-failure token inside an arm/start/stop response.

    The firmware surfaces SD-layer failures (card init, FAT init, pre-allocation,
    erase, writeStart, per-block writeData, BLOCK_COUNT exhaustion, BLE-guard
    refusal) with stable ASCII tokens. See SD_FAIL_TOKENS for the list.
    """

    def __init__(self, token: bytes, frame: bytes) -> None:
        super().__init__(f"{token.decode(errors='replace')}: {frame[:120]!r}")
        self.token = token
        self.frame = frame


# Stable firmware failure tokens. Order irrelevant; first match wins.
# Structured tokens (`$SDERR:*`) are emitted by the P0 patches; the plain
# strings below are pre-existing emissions left intact by the patches.
SD_FAIL_TOKENS: tuple[bytes, ...] = (
    b"$SDERR:",                    # family prefix: CANARY_FAIL, TAIL_FAIL, SD_FULL, FILE_INCOMPLETE
    b"initialization failed",      # SD_Card_Stuff.ino:143 (card.init fail)
    b"Could not find FAT16",       # :155 (volume.init fail)
    b"createfdContiguous fail",    # :201
    b"get contiguousRange fail",   # :210
    b"erase block fail",           # :223
    b"writeStart fail",            # :231
    b"block write fail",           # :372
    b"invalid BLOCK count",        # :188
    b"duration exceeds uint32",    # new (Change 4 overflow guard)
    b"Failure: cannot stream",     # new (Change 5 BLE-guard refusal)
)


def _scan_for_sd_error(frame: bytes) -> bytes | None:
    """Return the first known failure token found in `frame`, else None."""
    for tok in SD_FAIL_TOKENS:
        if tok in frame:
            return tok
    return None


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
        self._buf_lock = threading.Lock()

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
        with self._buf_lock:
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
            with self._buf_lock:
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


def auto_detect_port(candidate_ports: list[str], worker_factory=None) -> Optional[str]:
    """Try each candidate port; return the first that replies $$$ to 'v'.

    `worker_factory(port)` returns a SerialTransport-compatible object with
    open()/close() methods (defaults to SerialWorker). Injectable for tests.
    """
    if worker_factory is None:
        worker_factory = SerialWorker

    for port in candidate_ports:
        worker = worker_factory(port)
        try:
            worker.open()
        except Exception:
            continue
        try:
            proto = Protocol(transport=worker)
            try:
                proto.handshake()
                return port
            except (ProtocolTimeout, ProtocolError):
                continue
        finally:
            worker.close()
    return None


# ---------- UI layer (Tkinter) ----------

import tkinter as tk
from tkinter import ttk, messagebox
from enum import Enum, auto


class State(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    READY = auto()
    ARMING = auto()
    RECORDING = auto()
    CLOSING = auto()
    DONE = auto()
    SD_FAILED = auto()
    CONNECT_FAILED = auto()


# UI tick interval — how often the main loop drains the response queue and
# updates the elapsed-time readout while recording.
UI_TICK_MS = 50


class RecorderApp:
    """Tkinter UI driving the recorder state machine.

    Owns one SerialWorker and one Protocol instance at a time.
    All Tk widget mutation happens on the main thread, which polls the
    worker's frame queue every UI_TICK_MS.
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("OpenBCI Cyton Recorder")
        self.root.geometry("520x420")
        self.root.resizable(False, False)

        self.state: State = State.DISCONNECTED
        self.worker: Optional[SerialWorker] = None
        self.protocol: Optional[Protocol] = None
        self.selected_duration = tk.StringVar(value=DEFAULT_DURATION)
        self.selected_port = tk.StringVar(value="")
        self.recording_started_at: Optional[float] = None
        self.recording_target_s: int = 0

        self._build_widgets()
        self._refresh_ports()
        # Kick off auto-detect after the window appears.
        self.root.after(100, self._auto_connect)
        # Periodic UI tick for elapsed-time updates.
        self.root.after(UI_TICK_MS, self._on_tick)

    # ----- Layout -----

    def _build_widgets(self) -> None:
        pad = {"padx": 12, "pady": 6}

        # 1. Connection bar
        conn = ttk.Frame(self.root)
        conn.pack(fill="x", **pad)
        self.status_dot = tk.Canvas(conn, width=14, height=14, highlightthickness=0)
        self.status_dot.pack(side="left")
        self._draw_dot("red")
        self.status_label = ttk.Label(conn, text="Disconnected")
        self.status_label.pack(side="left", padx=(8, 12))
        ttk.Label(conn, text="Port:").pack(side="left")
        self.port_combo = ttk.Combobox(
            conn, textvariable=self.selected_port, width=10, state="readonly"
        )
        self.port_combo.pack(side="left", padx=4)
        ttk.Button(conn, text="Refresh", command=self._refresh_ports).pack(side="left")
        self.connect_btn = ttk.Button(conn, text="Connect", command=self._manual_connect)
        self.connect_btn.pack(side="left", padx=4)

        # 2. Duration selector
        dur = ttk.LabelFrame(self.root, text="Recording duration")
        dur.pack(fill="x", **pad)
        for label in DURATION_COMMANDS:
            ttk.Radiobutton(
                dur, text=label, value=label, variable=self.selected_duration
            ).pack(side="left", padx=8, pady=6)

        # 3. Action area
        action = ttk.Frame(self.root)
        action.pack(fill="x", **pad)
        self.start_btn = ttk.Button(
            action, text="Start Recording", command=self._on_start, state="disabled"
        )
        self.start_btn.pack(pady=8)
        self.stop_btn = ttk.Button(action, text="Stop", command=self._on_stop)
        # Stop is hidden until recording begins.
        self.timer_label = ttk.Label(action, text="", font=("Segoe UI", 14))
        self.progress = ttk.Progressbar(action, length=400, mode="determinate")

        # 4. Status + details
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill="both", expand=True, **pad)
        self.message_label = ttk.Label(status_frame, text="Searching for Cyton…")
        self.message_label.pack(anchor="w")
        self.details_btn = ttk.Button(
            status_frame, text="▸ Show details", command=self._toggle_details
        )
        self.details_btn.pack(anchor="w", pady=(6, 0))
        self.details_visible = False
        self.details_text = tk.Text(
            status_frame, height=8, font=("Consolas", 9), state="disabled", wrap="none"
        )
        # Pack on demand.

    def _draw_dot(self, color: str) -> None:
        self.status_dot.delete("all")
        self.status_dot.create_oval(2, 2, 12, 12, fill=color, outline="")

    def _toggle_details(self) -> None:
        if self.details_visible:
            self.details_text.pack_forget()
            self.details_btn.config(text="▸ Show details")
            self.details_visible = False
        else:
            self.details_text.pack(fill="both", expand=True, pady=(4, 0))
            self.details_btn.config(text="▾ Hide details")
            self.details_visible = True

    def _log_detail(self, text: str) -> None:
        self.details_text.config(state="normal")
        self.details_text.insert("end", text.rstrip() + "\n")
        self.details_text.see("end")
        self.details_text.config(state="disabled")

    # ----- Async helper -----

    def _run_async(self, work, on_success, on_error) -> None:
        """Run `work()` on a background thread; call `on_success(result)` or
        `on_error(exc)` back on the Tk main thread via root.after."""
        def runner():
            try:
                result = work()
            except Exception as exc:
                self.root.after(0, on_error, exc)
            else:
                self.root.after(0, on_success, result)
        threading.Thread(target=runner, daemon=True).start()

    # ----- State transitions -----

    def _set_state(self, new_state: State, message: str, dot_color: str) -> None:
        self.state = new_state
        self.status_label.config(text=new_state.name.title().replace("_", " "))
        self.message_label.config(text=message)
        self._draw_dot(dot_color)

    def _refresh_ports(self) -> None:
        ports = list_candidate_ports()
        self.port_combo["values"] = ports
        if ports and not self.selected_port.get():
            self.selected_port.set(ports[0])

    def _auto_connect(self) -> None:
        self._set_state(State.CONNECTING, "Searching for Cyton…", "yellow")
        ports = list_candidate_ports()
        if not ports:
            self._on_connect_failed("No COM ports found. Plug in the dongle and click Connect.")
            return

        def work():
            return auto_detect_port(ports)

        def on_success(port):
            if port is None:
                self._on_connect_failed(
                    "Could not find Cyton. Turn on Cyton (PC switch), plug in dongle, click Connect."
                )
            else:
                self.selected_port.set(port)
                self._open_port(port)

        def on_error(exc):
            self._on_connect_failed(f"Auto-detect error: {exc}")

        self._run_async(work, on_success, on_error)

    def _manual_connect(self) -> None:
        port = self.selected_port.get()
        if not port:
            messagebox.showwarning("No port", "Select a COM port from the dropdown first.")
            return
        self._open_port(port)

    def _open_port(self, port: str) -> None:
        # Phase 1 (sync): tear down prior worker, construct and open new one.
        if self.worker is not None:
            self.worker.close()
            self.worker = None
        try:
            self.worker = SerialWorker(port)
            self.worker.open()
            self.protocol = Protocol(transport=self.worker)
        except OSError as exc:
            self._on_connect_failed(f"Could not open {port}: {exc}")
            return

        # Phase 2 (async): run handshake on background thread so the UI stays live.
        self._set_state(State.CONNECTING, f"Handshaking on {port}…", "yellow")

        def work():
            return self.protocol.handshake()

        def on_success(banner):
            self._log_detail(f"[handshake] {banner!r}")
            self._set_state(State.READY, f"Connected on {port}. Ready to record.", "green")
            self.start_btn.config(state="normal")
            self.connect_btn.pack_forget()

        def on_error(exc):
            self._on_connect_failed(f"Could not talk to Cyton on {port}: {exc}")

        self._run_async(work, on_success, on_error)

    def _on_connect_failed(self, message: str) -> None:
        if self.worker is not None:
            self.worker.close()
            self.worker = None
        self.protocol = None
        self._set_state(State.CONNECT_FAILED, message, "red")
        self.start_btn.config(state="disabled")
        self.connect_btn.pack(side="left", padx=4)

    def _on_start(self) -> None:
        if self.protocol is None:
            return
        duration = self.selected_duration.get()
        # Synchronous part: update state immediately so the UI reflects ARMING.
        self._set_state(State.ARMING, f"Opening SD file for {duration}…", "yellow")
        self.start_btn.config(state="disabled")

        def work():
            response = self.protocol.arm(duration)
            self.protocol.start()
            return response

        def on_success(response):
            self._log_detail(f"[arm {duration}] {response!r}")
            self._log_detail("[start] sent 'b'")
            # Set recording_started_at only after the board actually starts.
            self.recording_started_at = time.monotonic()
            self.recording_target_s = DURATION_SECONDS[duration]
            self.progress.config(maximum=self.recording_target_s, value=0)
            self.timer_label.pack()
            self.progress.pack(pady=(0, 6))
            self.stop_btn.pack()
            self._set_state(State.RECORDING, "Recording in progress.", "green")

        def on_error(exc):
            if isinstance(exc, ProtocolTimeout):
                messagebox.showerror(
                    "SD card error",
                    "SD card not detected, is full, or is too slow. Try a different card.",
                )
            else:
                messagebox.showerror("Protocol error", str(exc))
            self._set_state(State.READY, "Ready to record.", "green")
            self.start_btn.config(state="normal")

        self._run_async(work, on_success, on_error)

    def _on_stop(self) -> None:
        if self.protocol is None:
            return
        # Synchronous part: update state to CLOSING immediately.  The state
        # guard in _on_tick checks for RECORDING, so once we are CLOSING,
        # subsequent ticks will not re-enter _on_stop.
        self._set_state(State.CLOSING, "Saving file — do not remove SD card…", "yellow")
        self.stop_btn.config(state="disabled")

        def work():
            return self.protocol.stop()

        def on_success(footer):
            self._log_detail(f"[stop] {footer!r}")
            self._enter_done()

        def on_error(exc):
            if isinstance(exc, (ProtocolTimeout, OSError)):
                messagebox.showwarning(
                    "Stop timeout",
                    "File may not have closed cleanly. Wait 10 seconds before removing the SD card.",
                )
            self._enter_done()

        self._run_async(work, on_success, on_error)

    def _enter_done(self) -> None:
        self.timer_label.pack_forget()
        self.progress.pack_forget()
        self.stop_btn.pack_forget()
        self.stop_btn.config(state="normal")
        self.recording_started_at = None
        messagebox.showinfo(
            "Recording complete",
            "Recording complete. Safe to power off the Cyton and remove the SD card.",
        )
        self._set_state(State.READY, "Ready to record.", "green")
        self.start_btn.config(state="normal")

    # ----- Periodic tick -----

    def _on_tick(self) -> None:
        if self.state is State.RECORDING and self.recording_started_at is not None:
            elapsed = int(time.monotonic() - self.recording_started_at)
            total = self.recording_target_s
            self.timer_label.config(text=f"{_fmt(elapsed)} / {_fmt(total)}")
            self.progress.config(value=min(elapsed, total))
            if elapsed >= total:
                self._on_stop()
        self.root.after(UI_TICK_MS, self._on_tick)

    # ----- Window close -----

    def on_close(self) -> None:
        if self.state is State.RECORDING:
            if not messagebox.askyesno(
                "Recording in progress",
                "Recording in progress. Quit anyway? "
                "(Recording will continue on-board until your duration elapses.)",
            ):
                return
        if self.worker is not None:
            self.worker.close()
        self.root.destroy()


def _fmt(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ---------- Entrypoint ----------

def main() -> None:
    root = tk.Tk()
    app = RecorderApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
