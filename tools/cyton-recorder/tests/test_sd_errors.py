"""Tests for the SD-failure token parser added to cyton_recorder."""

from __future__ import annotations

import pytest

from cyton_recorder import (
    SDCardError,
    SD_FAIL_TOKENS,
    _scan_for_sd_error,
)


@pytest.mark.parametrize(
    "frame,expected_token",
    [
        (b"$SDERR:CANARY_FAIL$$$",                        b"$SDERR:"),
        (b"$SDERR:TAIL_FAIL$$$",                          b"$SDERR:"),
        (b"$SDERR:SD_FULL$$$",                            b"$SDERR:"),
        (b"$SDERR:FILE_INCOMPLETE$$$",                    b"$SDERR:"),
        (b"initialization failed. Things to check:\n$$$", b"initialization failed"),
        (b"Could not find FAT16/FAT32\n$$$",              b"Could not find FAT16"),
        (b"createfdContiguous fail$$$",                   b"createfdContiguous fail"),
        (b"get contiguousRange fail$$$",                  b"get contiguousRange fail"),
        (b"erase block fail\n$$$",                        b"erase block fail"),
        (b"writeStart fail\n$$$",                         b"writeStart fail"),
        (b"block write fail\n$$$",                        b"block write fail"),
        (b"invalid BLOCK count\n$$$",                     b"invalid BLOCK count"),
        (b"duration exceeds uint32 block range\n$$$",     b"duration exceeds uint32"),
        (b"Failure: cannot stream over BLE at SPS > 250$$$", b"Failure: cannot stream"),
    ],
)
def test_scan_returns_token_when_frame_contains_known_failure(frame, expected_token):
    assert _scan_for_sd_error(frame) == expected_token


def test_scan_returns_none_for_clean_arm_frame():
    ok = b"%SD_DIAG fw=v3.1.5-p0 ads_id=0x3E daisy_id=NA rtc=1234 sps=250 free_blocks=31116287 file=OBCI_42.TXT$$$"
    assert _scan_for_sd_error(ok) is None


def test_scan_returns_none_for_clean_stop_frame():
    ok = b"SamplingRate: 250Hz\nTotal Elapsed Time: 1234 mS\nOverruns: 0\n$$$"
    assert _scan_for_sd_error(ok) is None


def test_sdcard_error_preserves_token_and_frame():
    frame = b"$SDERR:SD_FULL$$$"
    err = SDCardError(b"$SDERR:", frame)
    assert err.token == b"$SDERR:"
    assert err.frame == frame
    assert "$SDERR:" in str(err)


def test_all_tokens_in_registry_match_themselves():
    """Sanity: every token in SD_FAIL_TOKENS scans positive against itself."""
    for tok in SD_FAIL_TOKENS:
        assert _scan_for_sd_error(tok + b"$$$") == tok
