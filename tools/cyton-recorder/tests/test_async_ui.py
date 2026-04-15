"""Tests for RecorderApp._run_async — verifies the threading helper posts
results back without requiring a real Tk event loop."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cyton_recorder import RecorderApp


def _make_app() -> RecorderApp:
    """Create a RecorderApp without constructing any Tk widgets.

    We skip __init__ entirely and inject a MagicMock root so that
    root.after() calls can be inspected.  root.after is configured to
    invoke the callback immediately (synchronously) so tests don't need
    to spin an event loop.
    """
    app = RecorderApp.__new__(RecorderApp)

    def instant_after(delay_ms, callback, *args):
        callback(*args)

    app.root = MagicMock()
    app.root.after.side_effect = instant_after
    return app


def test_run_async_success_path_calls_on_success():
    app = _make_app()

    results = []

    def work():
        return 42

    def on_success(value):
        results.append(("ok", value))

    def on_error(exc):
        results.append(("err", exc))

    app._run_async(work, on_success, on_error)

    # Give the daemon thread a moment to complete.
    deadline = time.monotonic() + 2.0
    while not results and time.monotonic() < deadline:
        time.sleep(0.01)

    assert results == [("ok", 42)]


def test_run_async_error_path_calls_on_error():
    app = _make_app()

    results = []
    boom = ValueError("something broke")

    def work():
        raise boom

    def on_success(value):
        results.append(("ok", value))

    def on_error(exc):
        results.append(("err", exc))

    app._run_async(work, on_success, on_error)

    deadline = time.monotonic() + 2.0
    while not results and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(results) == 1
    kind, exc = results[0]
    assert kind == "err"
    assert exc is boom


def test_run_async_posts_via_root_after():
    """Confirm root.after(0, callback, result) is the mechanism used."""
    app = RecorderApp.__new__(RecorderApp)
    app.root = MagicMock()

    # Don't use side_effect — let after be a plain mock so we can inspect calls.
    called = threading.Event()

    def work():
        return "payload"

    def on_success(v):
        pass  # pragma: no cover

    def on_error(exc):
        pass  # pragma: no cover

    # Override after to record the call and signal the event.
    def recording_after(delay_ms, callback, *args):
        called.set()

    app.root.after.side_effect = recording_after

    app._run_async(work, on_success, on_error)
    assert called.wait(timeout=2.0), "root.after was never called"

    # The first positional arg must be 0 (immediate dispatch).
    delay = app.root.after.call_args[0][0]
    assert delay == 0


def test_run_async_thread_is_daemon():
    """Background threads must be daemon so they don't block process exit."""
    app = _make_app()

    thread_flags = []

    original_thread_init = threading.Thread.__init__

    import cyton_recorder

    threads_created = []
    original_start = threading.Thread.start

    # Patch Thread.start to capture the thread object before it starts.
    def capturing_start(self_thread):
        threads_created.append(self_thread)
        original_start(self_thread)

    done = threading.Event()

    def work():
        done.wait(timeout=0.5)
        return None

    def on_success(v):
        pass

    def on_error(exc):
        pass

    import unittest.mock as mock
    with mock.patch.object(threading.Thread, "start", capturing_start):
        app._run_async(work, on_success, on_error)

    assert threads_created, "No thread was started"
    assert threads_created[0].daemon, "Background thread must be daemon=True"
    done.set()
