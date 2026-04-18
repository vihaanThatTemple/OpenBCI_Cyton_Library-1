# Cyton P0 Firmware — Manual Bench Smoke Test

**Prerequisites:** Cyton board + RFduino dongle + one known-good microSD card (SanDisk Ultra/Extreme, ≤32 GB, FAT32) + one known-bad card (e.g., SDXC 64 GB formatted exFAT) + a USB serial terminal at 115200 baud.

## T1 — Clean arm + 5-min record (happy path)
1. Flash `examples/DefaultBoard/` firmware. Insert known-good SD. Power on PC mode.
2. In serial terminal: send `A` (5-min). Expect one frame:
   `%SD_DIAG fw=v3.1.5-p0 ads_id=0x3E daisy_id=NA rtc=<ms> sps=250 free_blocks=<n> file=OBCI_XX.TXT$$$`
3. Send `b`. Expect NO response frame.
4. Wait 5 min. Expect silent completion (no token).
5. Send `j`. Expect footer frame + `$$$`.
6. Pull SD, open `OBCI_XX.TXT` in hex editor. First 16 bytes = `OBCI_CANARY_V01` + `0x01`. Last 512 B block = `OBCI_TAIL_V01...`. Middle = valid hex-ASCII samples.

## T2 — Missing SD card
1. Remove SD card.
2. Send `A`. Expect `initialization failed. Things to check:* is a card is inserted?%SD_DIAG ... ads_id=0x3E daisy_id=NA rtc=<ms> sps=250 free_blocks=NA file=NA$$$`.
3. `cyton_recorder` should surface `SD_FAILED` with `initialization failed` token.

## T3 — SD_FULL mid-session (simulated)
1. Edit firmware locally to hard-code `BLOCK_COUNT = 4` (temporarily) and flash.
2. Send `A` then `b`. Wait ~1 s.
3. Expect `$SDERR:SD_FULL$$$` in the stream.
4. Revert the edit.

## T4 — BLE SPS>250 guard
1. Set board to BLE mode (PC→BLE switch) OR leave in PC mode but ensure `!wifi.present`.
2. Send SPS-up command (`~D` or similar) to raise SPS to 500.
3. Send `b`. Expect `Failure: cannot stream over BLE at SPS > 250$$$`. No samples flow.

## T5 — Daisy detection in diag
1. Attach Daisy module. Send `A`. Verify `daisy_id=0x3E` in the diag frame.

## T6 — Host app upgrade path
1. Run `cyton-recorder` built from this branch against OLD firmware (pre-P0). Verify `arm()` still returns a valid frame (it will be the legacy "Corresponding SD file" text; our parser ignores frames without the `%SD_DIAG` prefix, returns the raw frame, and `last_diag` stays None).
2. Run `cyton-recorder` from this branch against NEW firmware. Verify `last_diag` is populated and UI status label shows the file name.

## T7 — Repeated back-to-back arms (forum 2552 regression guard)
1. With known-good SD, arm + record + close five sessions in a row.
2. Each file's offset 0 should contain `OBCI_CANARY_V01`; each file's last block should contain `OBCI_TAIL_V01`.
3. No `$SDERR:*` tokens should appear in any session.
