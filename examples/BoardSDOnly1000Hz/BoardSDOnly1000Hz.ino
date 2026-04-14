/*
 * BoardSDOnly1000Hz
 *
 * Samples 8 channels at 1000Hz and writes exclusively to SD card.
 * No Bluetooth/serial streaming — all bandwidth goes to SD writes.
 * Accelerometer is disabled (LIS3DH can't keep up at 1000Hz).
 *
 * Usage:
 *   1. Open serial monitor at 115200 baud
 *   2. Send a file-size command: A(5min) S(15min) F(30min) G(1hr) H(2hr) J(4hr) K(12hr) L(24hr)
 *   3. Send 'b' to start recording
 *   4. Recording stops automatically when the file is full, or send 'j' to stop early
 *
 * IMPORTANT: Use a Class 10 or UHS-I SD card. Slow cards will cause overruns.
 */

#include <DSPI.h>
#include <OBCI32_SD.h>
#include <EEPROM.h>
#include <OpenBCI_32bit_Library.h>
#include <OpenBCI_32bit_Library_Definitions.h>

boolean SDfileOpen = false;

void setup() {
  board.begin();
  board.useAccel(false);
  board.setSampleRate(SAMPLE_RATE_1000);

  Serial0.println("OpenBCI 1000Hz SD-Only Mode");
  Serial0.println("Send file-size command (A/S/F/G/H/J/K/L) then 'b' to start");
  board.sendEOT();
}

void loop() {
  if (board.streaming) {
    if (board.channelDataAvailable) {
      board.updateChannelData();
      if (SDfileOpen) {
        writeDataToSDcard(board.sampleCounter);
      }
      // NOTE: board.sendChannelData() intentionally omitted — SD only
    }
  }

  if (board.hasDataSerial0()) {
    char newChar = board.getCharSerial0();
    sdProcessChar(newChar);
    board.processChar(newChar);
    // Re-apply 1000Hz after library's forced 250Hz reset on 'b' command
    if (board.streaming && board.curSampleRate != SAMPLE_RATE_1000) {
      board.streamSafeSetSampleRate(SAMPLE_RATE_1000);
    }
  }

  if (board.hasDataSerial1()) {
    char newChar = board.getCharSerial1();
    sdProcessChar(newChar);
    board.processChar(newChar);
    if (board.streaming && board.curSampleRate != SAMPLE_RATE_1000) {
      board.streamSafeSetSampleRate(SAMPLE_RATE_1000);
    }
  }

  board.loop();
}
