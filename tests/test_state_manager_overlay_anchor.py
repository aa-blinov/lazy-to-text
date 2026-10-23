"""The capsule must not move while a dictation is being processed.

The overlay is anchored to the screen the user is looking at, and the
anchor is resolved once per appearance.  So anything that hides the
overlay in the middle of a dictation makes it re-anchor — and the
fallback for an unresolvable anchor is the *primary* screen, which is
where the capsule was seen jumping to.

The dip was real: the state machine reported "idle" between the
recording ending and the pipeline starting, because the busy flag was
set after the recorder had already been stopped.  The overlay read
"idle", hid itself, and appeared again on the next state.
"""

import logging
import threading
from unittest.mock import MagicMock

import pytest


def _manager():
    """Half-real StateManager, as the other state-manager suites build it."""
    from app.state_manager import StateManager

    sm = StateManager.__new__(StateManager)
    sm.audio_recorder = MagicMock()
    sm.audio_recorder.get_recording_status.return_value = True
    sm.backend = MagicMock()
    sm.clipboard_manager = MagicMock()
    sm.config_manager = MagicMock()
    sm.config_manager.get_audio_config.return_value = {}
    sm.history_manager = None
    sm.history_update_callback = None
    sm.delivery_reported_callback = None
    sm.is_processing = False
    sm.is_model_loading = False
    sm.last_transcription = None
    sm._pending_model_change = None
    sm._state_lock = threading.Lock()
    sm.logger = logging.getLogger("test.output_mute_state")
    sm.audio_feedback = MagicMock()
    sm.system_tray = MagicMock()
    sm.output_mute = MagicMock()
    return sm


def test_the_app_is_marked_busy_before_the_recorder_is_stopped():
    """The order is the whole fix.

    While the recorder is being stopped the app is neither recording
    nor processing, and the state machine says so.  The overlay reads
    that state, hides itself, and re-anchors on the next one.
    """
    sm = _manager()
    seen = {}

    def _stop():
        seen["is_processing"] = sm.is_processing
        return None

    sm.audio_recorder.stop_recording.side_effect = _stop

    sm.stop_recording()

    assert seen["is_processing"] is True, (
        "the app was idle while the recorder was stopping — the state "
        "machine dips through 'idle' there and the overlay re-anchors"
    )


def test_the_state_never_dips_to_idle_between_recording_and_processing():
    sm = _manager()
    states = []

    def _stop():
        states.append(sm.get_current_state())
        return None

    sm.audio_recorder.stop_recording.side_effect = _stop

    sm.stop_recording()

    assert states == ["processing"], states


# ---- the overlay's anchor ---------------------------------------------------


def test_the_anchor_survives_the_processing_state(qtbot):
    """Recording → processing → delivery is one appearance.

    The anchor is the screen the user is looking at.  Re-resolving it
    mid-dictation is what moves the capsule, and the fallback for an
    unresolvable anchor is the primary screen.
    """
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.set_state("recording")
    anchor = overlay._screen
    assert anchor is not None

    overlay.set_state("processing")
    assert overlay._screen is anchor

    overlay.set_state("idle")
    overlay.set_state("recording")
    # A new dictation re-anchors: the screen the user is on may have
    # changed since the last one.
    assert overlay._screen is not None
