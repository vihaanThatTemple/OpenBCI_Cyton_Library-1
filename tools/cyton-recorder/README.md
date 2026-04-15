# Cyton Recorder

A double-clickable Windows app for recording 8-channel EEG from an OpenBCI
Cyton + RFduino dongle to the on-board SD card at **1000 Hz**.

No serial terminal, no command letters, no GUI install. Pick a duration,
click **Start**, wait for the popup, take the SD card out.

> Requires the Cyton to be flashed with the
> [`BoardSDOnly1000Hz`](../../examples/BoardSDOnly1000Hz/) firmware sketch.

---

## End-user quickstart

1. Plug the OpenBCI USB dongle into your PC.
2. Insert a Class-10 (or faster) SD card into the Cyton.
3. Switch the Cyton to **PC** mode and turn it on.
4. Double-click `CytonRecorder.exe`.
5. The status dot turns **green** when it finds the board.
6. Pick a duration (default: 15 min), click **Start Recording**.
7. When the popup says "Recording complete", power off the Cyton and pull
   the SD card. Your file is `OBCI_XX.TXT` on the card.

If the dot stays **red**: turn the Cyton on, check the dongle is plugged
in, click **Connect**.

If "SD card not detected" appears: insert a card and try again. If it
keeps failing, try a faster card (Class 10 / UHS-I).

---

## Building from source

Requires Python 3.11+ on Windows.

```cmd
cd tools\cyton-recorder
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
build.bat
```

Output: `dist\CytonRecorder.exe` (single ~12 MB file, no Python required on
target machines).

---

## Running tests

```bash
cd tools/cyton-recorder
pip install -r requirements-dev.txt
python -m pytest -v
```

All tests run without hardware.

---

## Manual hardware smoke test (per release)

1. Flash `examples/BoardSDOnly1000Hz/` to the Cyton.
2. Insert a freshly formatted FAT32 SD card.
3. Launch `CytonRecorder.exe`. Confirm green status.
4. Select **5 min**, click **Start Recording**.
5. Wait ~5 minutes for the "Recording complete" popup.
6. Power off the Cyton, take the card to a PC.
7. Open `OBCI_XX.TXT`. Confirm:
   - Footer line `%SamplingFreq:` shows `1000`.
   - First column (sample counter) increments and wraps at `FF`.
   - Eight comma-separated hex columns of channel data per line.
   - `%Over:` count is 0 or very low (<5).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Red dot, "Could not find Cyton" | Check Cyton is on, switch is on **PC**, dongle is plugged in. Click **Connect**. |
| App freezes during file-open | 4 hr pre-allocation can take 2–3 s on slow cards. If it stays frozen >5 s, the card is bad. |
| "Recording complete" never fires | Open **Show details**. If you see a `$$$` line, the file closed; click OK. If not, wait 10 s then remove the card. |
| Dongle unplugged mid-recording | The Cyton keeps recording on its own. Wait for your selected duration to elapse, then power it off and grab the card. |

---

## Architecture (for maintainers)

Three internal layers in `cyton_recorder.py`:

- **SerialWorker** — owns `pyserial.Serial`, runs a daemon reader thread,
  splits incoming bytes on `$$$` and pushes complete frames into a
  `queue.Queue`. Never touches Tkinter.
- **Protocol** — synchronous wrapper. `handshake()`, `arm(duration)`,
  `start()`, `stop()`. Knows the firmware command alphabet.
- **RecorderApp** — Tkinter UI. Owns the state machine. Polls the worker
  queue every 50 ms via `root.after()`.

See `docs/superpowers/specs/2026-04-15-cyton-recorder-app-design.md` for
the full design.
