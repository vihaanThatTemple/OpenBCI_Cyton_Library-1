"""Unit tests for the Protocol layer (no hardware, no Tkinter)."""

from __future__ import annotations

import pytest

from cyton_recorder import (
    DURATION_COMMANDS,
    HANDSHAKE_CMD,
    START_CMD,
    STOP_CMD,
    Protocol,
    ProtocolTimeout,
)


def test_handshake_sends_v_and_returns_banner(fake_serial):
    fake_serial.queue_response(b"OpenBCI V3 8-16 channel\n$$$")
    proto = Protocol(transport=fake_serial)

    response = proto.handshake()

    assert fake_serial.writes == [HANDSHAKE_CMD]
    assert response == b"OpenBCI V3 8-16 channel\n$$$"
    assert fake_serial.drained == 1  # drains stale bytes before handshake


def test_handshake_timeout_raises(fake_serial):
    proto = Protocol(transport=fake_serial)
    # No response queued.
    with pytest.raises(ProtocolTimeout):
        proto.handshake()


@pytest.mark.parametrize("label,expected_byte", [
    ("5 min",  b"A"),
    ("15 min", b"S"),
    ("30 min", b"F"),
    ("1 hr",   b"G"),
    ("2 hr",   b"H"),
    ("4 hr",   b"J"),
])
def test_arm_sends_correct_duration_letter(fake_serial, label, expected_byte):
    fake_serial.queue_response(b"Corresponding SD file OBCI_01.TXT\n$$$")
    proto = Protocol(transport=fake_serial)

    proto.arm(label)

    assert fake_serial.writes == [expected_byte]


def test_arm_unknown_duration_raises(fake_serial):
    proto = Protocol(transport=fake_serial)
    with pytest.raises(ValueError):
        proto.arm("99 min")


def test_arm_timeout_raises_when_sd_silent(fake_serial, monkeypatch):
    monkeypatch.setattr("cyton_recorder.FILE_OPEN_TIMEOUT_S", 0.1)
    proto = Protocol(transport=fake_serial)
    with pytest.raises(ProtocolTimeout):
        proto.arm("5 min")


def test_start_sends_b_and_expects_no_response(fake_serial):
    proto = Protocol(transport=fake_serial)
    proto.start()
    assert fake_serial.writes == [START_CMD]


def test_stop_sends_j_and_returns_footer(fake_serial):
    fake_serial.queue_response(b"SamplingRate: 1000Hz\nOverruns: 0\n$$$")
    proto = Protocol(transport=fake_serial)

    response = proto.stop()

    assert fake_serial.writes == [STOP_CMD]
    assert response.endswith(b"$$$")


def test_stop_timeout_raises(fake_serial):
    proto = Protocol(transport=fake_serial)
    with pytest.raises(ProtocolTimeout):
        proto.stop()


def test_duration_command_table_matches_firmware():
    # Firmware is examples/BoardSDOnly1000Hz/SD_Card_Stuff.ino
    # — these letters MUST match the switch in sdProcessChar().
    assert DURATION_COMMANDS["5 min"]  == b"A"
    assert DURATION_COMMANDS["15 min"] == b"S"
    assert DURATION_COMMANDS["30 min"] == b"F"
    assert DURATION_COMMANDS["1 hr"]   == b"G"
    assert DURATION_COMMANDS["2 hr"]   == b"H"
    assert DURATION_COMMANDS["4 hr"]   == b"J"
