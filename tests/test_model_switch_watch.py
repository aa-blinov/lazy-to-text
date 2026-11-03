"""The watcher that follows a model switch must not end it early.

A switch passes through the backend's ``stopped`` status while the old model is
let go and before the new one starts. The watcher used to take that as the end:
it cleared the loading flag, the switch read as cancelled, a Cancel then found
nothing to cancel, and the download that followed was never selected.
"""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock

import pytest


def _state_manager(statuses):
    """A state manager whose backend reports ``statuses`` one poll at a time."""
    from app.state_manager import StateManager

    sm = StateManager.__new__(StateManager)
    sm.backend = MagicMock()
    script = iter(statuses)
    last = {"value": statuses[-1]}

    def status():
        try:
            last["value"] = next(script)
        except StopIteration:
            pass
        return last["value"]

    sm.backend.status.side_effect = status
    sm.is_model_loading = True
    sm._model_change_seq = 0
    sm._state_lock = threading.Lock()
    sm.logger = logging.getLogger("test.model_switch_watch")
    sm.system_tray = MagicMock()
    sm.audio_feedback = MagicMock()
    return sm


@pytest.fixture
def fast_clock(monkeypatch):
    import app.state_manager as module

    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    monkeypatch.setattr(module, "_STOPPED_GRACE_S", 0.05)
    return module


def test_a_stop_that_passes_does_not_end_the_switch(fast_clock):
    sm = _state_manager(["stopped", "loading", "loading", "ready"])
    seq = sm._model_change_seq

    sm._watch_model_change("gigaam-v2", timeout=5, seq=seq)

    assert sm.is_model_loading is False  # it ended on ready, not on the first stop
    assert sm.backend.status.call_count == 4


def test_a_stop_that_lasts_ends_the_switch(fast_clock):
    sm = _state_manager(["stopped"])  # stays stopped
    sm._watch_model_change("gigaam-v2", timeout=5, seq=sm._model_change_seq)

    assert sm.is_model_loading is False
    assert sm.backend.status.call_count >= 2  # it waited for the grace before deciding


def test_abandoning_the_switch_ends_its_watcher_at_once(fast_clock):
    sm = _state_manager(["loading"] * 50)
    seq = sm._model_change_seq
    sm.abandon_model_change()

    sm._watch_model_change("gigaam-v2", timeout=5, seq=seq)

    assert sm.is_model_loading is False
    assert sm.backend.status.call_count == 0  # it saw the bumped sequence before polling
