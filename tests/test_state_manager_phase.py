"""Which part of processing is running, as the interface reads it."""

import threading

from app.state_manager import StateManager


def _manager():
    manager = StateManager.__new__(StateManager)
    manager._state_lock = threading.Lock()
    manager.is_processing = False
    manager._phase = ""
    return manager


def test_no_phase_while_idle_even_if_a_stale_one_was_left():
    manager = _manager()
    manager._phase = "postprocessing"

    assert manager.get_current_phase() == ""


def test_the_postprocessing_phase_shows_only_while_processing():
    manager = _manager()
    manager.is_processing = True
    assert manager.get_current_phase() == ""

    manager._phase = "postprocessing"
    assert manager.get_current_phase() == "postprocessing"
