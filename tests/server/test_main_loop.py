"""The runtime's main thread on macOS has to pump the AppKit event queue.

The macOS hotkey monitor is an ``NSEvent`` global monitor; AppKit hands it
events only while the process's main thread serves its queue. A runtime
whose main thread merely waited registered the hotkeys and never received a
key, which no unit test of the listener could show because the listener was
fine. Found by pressing the real hotkey against the real runtime.
"""

from __future__ import annotations

import sys
import threading
import types

from app.server.__main__ import _wait_for


def test_off_macos_the_main_thread_just_waits(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    done = threading.Event()
    done.set()

    _wait_for(done)  # returns at once; nothing to pump


def test_on_macos_the_event_queue_is_served_until_done(monkeypatch):
    calls = {"policy": None, "launched": False, "polls": 0, "sent": []}
    done = threading.Event()

    class _App:
        def setActivationPolicy_(self, policy):
            calls["policy"] = policy

        def finishLaunching(self):
            calls["launched"] = True

        def nextEventMatchingMask_untilDate_inMode_dequeue_(self, mask, date, mode, dequeue):
            calls["polls"] += 1
            if calls["polls"] == 3:
                done.set()
            return f"event{calls['polls']}" if calls["polls"] == 1 else None

        def sendEvent_(self, event):
            calls["sent"].append(event)

    class _NSApplication:
        @staticmethod
        def sharedApplication():
            return _App()

    appkit = types.SimpleNamespace(
        NSApplication=_NSApplication,
        NSApplicationActivationPolicyProhibited=2,
        NSDefaultRunLoopMode="default",
        NSEventMaskAny=2**64 - 1,
    )
    foundation = types.SimpleNamespace(
        NSDate=types.SimpleNamespace(dateWithTimeIntervalSinceNow_=lambda s: s)
    )
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "Foundation", foundation)

    _wait_for(done)

    assert calls["policy"] == 2, "no Dock icon for a background engine"
    assert calls["launched"] is True
    assert calls["polls"] == 3
    assert calls["sent"] == ["event1"], "a dequeued event must be dispatched"
