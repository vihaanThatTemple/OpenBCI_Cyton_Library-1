# Cyton Recorder App — Design

**Date:** 2026-04-15
**Status:** Approved for implementation planning
**Target firmware:** `examples/BoardSDOnly1000Hz/` (1000 Hz, SD-only)

## Purpose

Give a naive end-user a double-clickable Windows application that drives the OpenBCI Cyton + RFduino dongle to record EEG to the on-board SD card at 1000 Hz, without exposing them to serial terminals, switch positions, or command letters.

## Non-Goals

- No live data visualisation.
- No integration with the OpenBCI GUI (1000 Hz cannot be streamed over the RFduino radio; post-hoc GUI playback is out of scope for v1).
- No on-the-fly SD file conversion to GUI/CSV formats.
- No cross-platform builds (v1 ships Windows `.exe` only; the Python source can be run manually on macOS/Linux).
- No auto-updater, telemetry, multi-board support.

## Scope

A single Python 3.11+ Tkinter application, packaged with PyInstaller into `CytonRecorder.exe`, that:

1. Auto-detects the Cyton dongle COM port on launch via a `v` handshake.
2. Presents six preset durations (5 min, 15 min, 30 min, 1 hr, 2 hr, 4 hr).
3. Sends the firmware's SD-preallocation command + `b` to start recording.
4. Shows elapsed time and provides a Stop button (sends `j`).
5. Waits for the firmware's end-of-file acknowledgement before telling the user it is safe to remove the SD card.
6. Provides a collapsible "Show details" log of raw board messages for support/debugging.

## Architecture

Three-layer design in a single `cyton_recorder.py` file (~400 LOC):

**Serial layer** (`pyserial`). Owns the COM port. Runs on a background `threading.Thread`. Accumulates incoming bytes into a buffer; on seeing `$$$` terminator, pushes the completed response onto a `queue.Queue` for the UI thread to drain. Never touches Tkinter widgets.

**Protocol layer.** Thin wrapper over the serial layer. Exposes `handshake()`, `arm(duration_letter)`, `start()`, `stop()`, each returning the board's response or raising `ProtocolTimeout`. Knows the firmware command alphabet (`v`, `A`/`S`/`F`/`G`/`H`/`J`, `b`, `j`) and the `$$$` response marker.

**UI layer** (Tkinter). Single fixed-size window, ~500×400. Drives the state machine. Polls the response queue on a 50 ms `after()` tick. Only the UI thread touches widgets.

### Rationale for splitting layers

The serial layer is testable without Tkinter (pipe it against a mock serial). The protocol layer is testable without hardware (mock the serial layer). Only the UI layer requires a human, and its state transitions are small enough to follow by eye.

## UI Layout

Fixed-size window, four stacked regions top-to-bottom:

1. **Connection bar** — status label with a coloured dot (red/yellow/green), COM-port dropdown, refresh button, manual Connect button (hidden while auto-connect succeeds).
2. **Duration selector** — six radio buttons in a single row. Default: 15 min.
3. **Action area** — large green "Start Recording" button. During recording, replaced by elapsed/total timer, progress bar, and red "Stop" button.
4. **Status + details** — one-line plain-English status message, plus a collapsible "▸ Show details" pane with a monospace scrolling log of raw board messages (~8 lines visible, autoscroll).

## State Machine

```
DISCONNECTED ──auto-detect──▶ CONNECTING ──$$$──▶ READY
     ▲                              │                │
     │                          timeout              │
     │                              ▼                │
     └──────────────────── CONNECT_FAILED ◀──retry───┤
                                                     │
                                            click Start
                                                     ▼
       RECORDING ◀──── $$$ (file opened) ──── ARMING (sends A/S/F/G/H/J)
           │                                         │
      click Stop (sends 'j')                    SD error / timeout
       OR duration elapsed                           │
           ▼                                         ▼
        CLOSING (waits for final $$$, ≤5 s)     SD_FAILED (popup) ──▶ READY
           │
           ▼
        DONE (popup "safe to remove SD") ──OK──▶ READY
```

### Happy path

1. Launch → scan COM ports → send `v` on each candidate → first port returning `$$$` within 5 s wins.
2. Status → green "Ready." User selects 15 min → clicks **Start**.
3. App sends `S`; board pre-allocates the SD file, replies `…$$$`.
4. App sends `b`; ADS streaming + SD writes begin on-device. Timer starts in the UI.
5. Timer reaches duration (or user clicks **Stop**, sending `j`).
6. Status → "Saving file — do not remove SD card…" App waits for final `$$$` (footer-write marker).
7. Popup: "Recording complete. Safe to power off and remove the SD card."

### Error paths

| Situation | App behaviour |
|---|---|
| No COM port replies to `v` | "Turn on Cyton (switch to PC), plug in dongle, click Retry." |
| Handshake timeout (5 s) | Same as above. |
| SD error during ARMING | Popup: "SD card not detected — insert card and try again." State → READY. |
| File-open timeout (3 s, 4 hr preallocation can be slow on slow cards) | Popup: "SD card is slow or full. Try a different card." |
| Dongle unplugged mid-recording | "Dongle disconnected. Cyton may still be recording to SD. Wait for your duration to elapse, then power off and retrieve the card." |
| Stop timeout (5 s with no final `$$$`) | "File may not have closed cleanly. Wait 10 seconds before removing the SD card." |
| Window close during recording | Confirm dialog: "Recording in progress. Quit anyway? (Recording will continue on-board.)" |

## Protocol Details

**Port settings:** 115200 8N1, no flow control, 100 ms read timeout (non-blocking loop).

**Commands:**

| User action | Bytes sent | Expected response |
|---|---|---|
| App launch | `v` | Banner text + `$$$` |
| 5 min | `A` | File-open text + `$$$` |
| 15 min | `S` | " |
| 30 min | `F` | " |
| 1 hr | `G` | " |
| 2 hr | `H` | " |
| 4 hr | `J` | " |
| Start | `b` | (binary samples to SD; no serial text) |
| Stop | `j` | Footer text + `$$$` |

**Timing guards:**

- Handshake timeout: 5 s.
- File-open timeout: 3 s (covers up to 4 hr / 1.6 GB block pre-erase on Class-10 SD).
- Stream-stop timeout: 5 s.

**Note on firmware sample-rate toggle.** The sketch re-applies 1000 Hz ~50 ms after `b` because the library's `processChar('b')` path forces 250 Hz before streaming. The app does nothing about this; the details log will briefly show "Sample rate set to 250 Hz" then "Sample rate set to 1000 Hz". The log pane will carry a tooltip noting this is expected.

## Testing

- **Unit tests** (`tests/test_protocol.py`): mock the serial port, assert correct bytes per duration, verify `$$$` detection across fragmented reads, verify timeouts raise `ProtocolTimeout`. Runs in CI; no hardware required.
- **Manual hardware smoke test**, documented in `README.md`: plug in Cyton + dongle + SD, launch app, record 5 min, confirm `OBCI_XX.TXT` appears on the card with ~5 min of 1000 Hz samples. Performed once per release before tagging.
- **No hardware CI.**

## Packaging & Distribution

**Project layout:**

```
tools/cyton-recorder/
├── cyton_recorder.py
├── requirements.txt          # pyserial==3.5
├── build.bat                 # PyInstaller one-liner
├── icon.ico
├── README.md                 # user-facing 1-page quickstart
└── tests/
    └── test_protocol.py
```

**Build:**

```
pyinstaller --onefile --windowed --icon=icon.ico --name=CytonRecorder cyton_recorder.py
```

Produces `dist/CytonRecorder.exe` (~12 MB standalone; no Python install required on the target machine).

**Distribution:** source committed to `tools/cyton-recorder/` in this repo; release binaries uploaded to the GitHub Releases page as `CytonRecorder-vX.Y.Z.exe`. `README.md` links to the latest release.

## Open Questions

None at spec-approval time.

## Out of Scope (explicit)

- Auto-updater, telemetry.
- Multi-board, multi-dongle.
- SD-file conversion to GUI or CSV formats.
- Live data preview.
- macOS/Linux binary builds.
