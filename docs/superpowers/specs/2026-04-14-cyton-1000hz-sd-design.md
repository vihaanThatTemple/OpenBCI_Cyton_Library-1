# Cyton 1000Hz SD-Only Recording

## Goal

Modify the OpenBCI Cyton firmware to sample all 8 channels at 1000Hz and write data exclusively to the SD card. No Bluetooth/serial streaming.

## Background & Prior Art

Community members have done this before:
- **PR #96** (unmerged) — minimal fix: removes the forced 250Hz reset, suppresses serial streaming at >250Hz. Tested successfully at 1000Hz for 35+ minutes.
- **yj-xxxiii/OpenBCI_2kHz** — standalone SD-only firmware achieving 2kHz/8ch. Uses optional binary format and a FIFO buffer to decouple acquisition from SD writes.
- Multiple forum reports confirm 1000Hz SD works reliably with a good Class 10/UHS-I card.

## Approach: New Example Sketch

Create `examples/BoardSDOnly1000Hz/` with two files:
- `BoardSDOnly1000Hz.ino` — main sketch
- `SD_Card_Stuff.ino` — adapted from DefaultBoard's version

This avoids modifying the core library, keeping the stock firmware intact for other use cases.

## Changes Required

### 1. Remove the forced 250Hz reset (in the sketch, not the library)

The core library at `OpenBCI_32bit_Library.cpp:355-358` forces the sample rate to 250Hz when streaming starts over Bluetooth. Since our sketch is SD-only, we avoid this by:
- Setting the sample rate **after** calling `board.begin()` but **before** any streaming starts
- Not relying on the `'b'` (stream start) serial command to initiate recording — instead, the sketch will manage streaming directly

### 2. Set sample rate to 1000Hz at startup

In `setup()`:
```cpp
board.setSampleRate(SAMPLE_RATE_1000);
```

This writes `0x04` to CONFIG1 bits[2:0], configuring the ADS1299 for 1000 SPS.

### 3. Scale SD block counts by 4x

The existing block counts assume 250Hz. At 1000Hz, data rate is 4x higher. Each sample at 8 channels produces ~50 bytes of hex ASCII text. At 1000Hz:
- ~50KB/s data rate
- ~98 block writes/s (512 bytes each)
- Sustainable on a Class 10 SD card (typical sequential write: 10+ MB/s)

Block count scaling:
```
BLOCK_5MIN_1K   = BLOCK_5MIN * 4    // 67,560 blocks
BLOCK_15MIN_1K  = BLOCK_15MIN * 4
... etc
```

### 4. Skip serial streaming entirely

In the main loop, do NOT call `board.sendChannelData()`. This saves ~200-400us per sample — critical when the total budget is 1ms.

The loop becomes:
```
if channelDataAvailable:
    updateChannelData()
    if SDfileOpen:
        writeDataToSDcard(sampleCounter)
```

### 5. Skip accelerometer in the sample loop

The LIS3DH accelerometer maxes out at ~400Hz ODR. At 1000Hz it can't keep up and polling it wastes time. Accelerometer data is omitted from SD writes.

### 6. Keep hex ASCII format

Binary would be more efficient (~32 bytes/sample vs ~50), but hex ASCII:
- Is compatible with the existing OpenBCI GUI SD file converter
- Is human-readable for debugging
- At 1000Hz/8ch the data rate (~50KB/s) is well within SD card capability
- Can always switch to binary later if needed

### 7. SD commands via serial

The sketch still accepts serial commands to open/close SD files (A/S/F/G/H/J/K/L and 'j'). The user:
1. Connects via serial terminal
2. Sends a file-size command (e.g., 'A' for 5 min)
3. Sends 'b' to start streaming → data goes to SD only
4. Sends 's' to stop, or file auto-closes when full

## Data Format

Identical to existing SD format (hex ASCII CSV):
```
SampleNum,CH1,CH2,CH3,CH4,CH5,CH6,CH7,CH8\n
```

Footer includes: sampling frequency (1000), elapsed time, min/max write times, overrun count.

## Timing Budget (per sample at 1000Hz = 1ms)

| Operation | Estimated Time |
|-----------|---------------|
| DRDY interrupt + flag set | ~5 us |
| SPI read 8ch (27 bytes @ 4MHz) | ~60 us |
| Hex convert + cache write | ~100 us |
| SD block flush (every ~6 samples) | ~300 us amortized |
| **Total** | **~465 us** |
| **Headroom** | **~535 us** |

This leaves comfortable margin. The SD block flush (~300-500us at 20MHz SPI) only happens every ~6 samples, so most iterations only do the read + convert (~165us).

## Risk Mitigation

1. **SD card quality**: Must use Class 10 or UHS-I. Cheap cards cause corruption.
2. **Overrun monitoring**: Keep the existing overrun tracking (OVER_DIM=20). The footer will report any timing violations.
3. **MICROS_PER_BLOCK threshold**: Keep at 2000us. At 1000Hz this spans 2 sample periods — a block write taking >2ms means we definitely lost a sample, so it's still a meaningful threshold.

## Out of Scope

- Daisy support (16 channels) — user specified Cyton-only
- Bluetooth/WiFi streaming — SD-only
- Binary format — hex ASCII is sufficient and compatible
- Library modifications — all changes in the example sketch
