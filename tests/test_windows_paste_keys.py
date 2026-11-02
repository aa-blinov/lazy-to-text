"""The Windows paste keystroke and the keys the person may still be holding.

A short dictation is transcribed before the fingers are up, so the paste often
arrives while the stop hotkey (Ctrl+F3 by default) is still down. Sent
carelessly, the keystroke released the person's own Ctrl, and the F3 still
repeating reached the focused window as a bare F3 (Find; Paste Name in Excel):
a dialog instead of a paste.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import app.clipboard_manager as cm

CTRL, V, ALT, SHIFT, F3 = 0x11, ord("V"), 0x12, 0x10, 0x72


class _Keyboard:
    """A fake win32api: which keys are down, and what the code sent."""

    def __init__(self, down=(), releases=None):
        self.down = set(down)
        self.releases = releases or {}  # key -> number of polls before it lets go
        self.events = []

    def GetAsyncKeyState(self, vk):  # noqa: N802 - the real name
        if vk in self.releases:
            self.releases[vk] -= 1
            if self.releases[vk] <= 0:
                self.down.discard(vk)
        return 0x8000 if vk in self.down else 0

    def keybd_event(self, vk, scan, flags, extra):
        self.events.append(("up" if flags else "down", vk))


@pytest.fixture
def keyboard(monkeypatch):
    def install(**kw):
        board = _Keyboard(**kw)
        monkeypatch.setattr(cm.sys, "platform", "win32")
        monkeypatch.setattr(cm, "win32api", board)
        monkeypatch.setattr(cm, "win32con", SimpleNamespace(VK_CONTROL=CTRL, VK_RETURN=0x0D, KEYEVENTF_KEYUP=2))
        monkeypatch.setattr(cm, "_KEY_RELEASE_WAIT_S", 0.05)
        return board
    return install


def _manager():
    manager = cm.ClipboardManager.__new__(cm.ClipboardManager)
    manager.logger = logging.getLogger("test.paste")
    manager.key_simulation_delay = 0.0
    manager.auto_paste = True
    manager.copied_before_paste = False
    return manager


def test_with_nothing_held_it_presses_and_releases_ctrl_itself(keyboard):
    board = keyboard()

    assert _manager()._send_paste_combo() is True

    assert board.events == [("down", CTRL), ("down", V), ("up", V), ("up", CTRL)]


def test_a_ctrl_the_person_is_holding_is_left_down(keyboard):
    """Releasing it would hand the rest of Ctrl+F3 to the window as a bare F3."""
    board = keyboard(down={CTRL})

    assert _manager()._send_paste_combo() is True

    assert board.events == [("down", V), ("up", V)]
    assert ("up", CTRL) not in board.events


def test_it_waits_for_the_function_key_of_the_hotkey_to_come_up(keyboard):
    board = keyboard(down={CTRL, F3}, releases={F3: 3})

    assert _manager()._send_paste_combo() is True

    assert F3 not in board.down  # it waited for the release rather than sending over it
    assert board.events == [("down", V), ("up", V)]


def test_a_function_key_that_stays_down_does_not_block_the_paste(keyboard):
    board = keyboard(down={CTRL, F3})

    assert _manager()._send_paste_combo() is True

    assert board.events == [("down", V), ("up", V)]


def test_alt_held_the_whole_time_means_no_keystroke_and_the_text_stays_on_the_clipboard(keyboard):
    """Ctrl+Alt+V is Paste Special in Office: a dialog, not a paste."""
    board = keyboard(down={ALT})

    assert _manager()._send_paste_combo() is False

    assert board.events == []


def test_shift_that_is_let_go_in_time_lets_the_paste_through(keyboard):
    board = keyboard(down={SHIFT}, releases={SHIFT: 2})

    assert _manager()._send_paste_combo() is True

    assert board.events == [("down", CTRL), ("down", V), ("up", V), ("up", CTRL)]


def test_a_refused_paste_is_reported_as_copied_not_pasted(keyboard, monkeypatch):
    keyboard(down={ALT})
    box = {}
    monkeypatch.setattr(cm.pyperclip, "paste", lambda: box.get("t", ""))
    monkeypatch.setattr(cm.pyperclip, "copy", lambda t: box.__setitem__("t", t))
    manager = _manager()

    assert manager.deliver_transcription("привет") == "copied"
    assert box["t"] == "привет"
