"""Tests for _fmt() elapsed-time formatter."""

import pytest

from cyton_recorder import _fmt


@pytest.mark.parametrize("seconds,expected", [
    (0, "00:00"),
    (5, "00:05"),
    (59, "00:59"),
    (60, "01:00"),
    (599, "09:59"),  # 9:59
    (3599, "59:59"),
    (3600, "1:00:00"),
    (3661, "1:01:01"),
    (4 * 3600, "4:00:00"),
])
def test_fmt(seconds, expected):
    assert _fmt(seconds) == expected
