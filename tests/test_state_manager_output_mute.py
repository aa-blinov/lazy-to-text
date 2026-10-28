"""The system output follows the recording.

The mute has to start and stop with the microphone, and the two
acoustic signals — the start beep and the stop beep — have to stay on
the right side of it: the start beep before the mute, the stop beep
after the unmute. A user who cannot hear the confirmation has no idea
whether the keypress was caught.
"""

import logging
import threading
from unittest.mock import MagicMock

import pytest


def _manager(mute_output=True, recorder_starts=True):
    """Half-real StateManager, as the other state-manager suites build it."""
    from app.state_manager import StateManager

    sm = StateManager.__new__(StateManager)

    sm.audio_recorder = MagicMock()
    sm.audio_recorder.get_recording_status.return_value = True
    sm.audio_recorder.start_recording.return_value = recorder_starts
    sm.backend = MagicMock()
    sm.clipboard_manager = MagicMock()
    sm.config_manager = MagicMock()
    sm.config_manager.get_audio_config.return_value = {
        "mute_output_on_record": mute_output,
    }
    sm.history_manager = None
    sm.history_update_callback = None
    sm.delivery_reported_callback = None
    sm.is_processing = False
    sm.is_model_loading = False
    sm.last_transcription = None
    sm._pending_model_change = None
    sm._state_lock = threading.Lock()
    sm.logger = logging.getLogger("test.state_manager_output_mute")
    sm.audio_feedback = MagicMock()
    sm.audio_feedback.start_sound_seconds.return_value = 0.0
    sm.system_tray = MagicMock()
    sm.output_mute = MagicMock()
    return sm


# ---- the mute follows the recording -----------------------------------------


def test_starting_a_recording_mutes_the_system_output():
    sm = _manager()

    sm._start_recording()

    sm.output_mute.mute.assert_called_once()


def test_the_output_is_left_alone_when_the_feature_is_off():
    sm = _manager(mute_output=False)

    sm._start_recording()

    sm.output_mute.mute.assert_not_called()


def test_stopping_the_recording_restores_the_output():
    sm = _manager()

    sm.stop_recording()

    sm.output_mute.restore.assert_called_once()


def test_cancelling_the_recording_restores_the_output():
    sm = _manager()

    sm.cancel_active_recording()

    sm.output_mute.restore.assert_called_once()


def test_quitting_during_a_recording_restores_the_output():
    """The app can be quit mid-dictation; the machine must not stay muted."""
    sm = _manager()

    sm.shutdown()

    sm.output_mute.restore.assert_called_once()


def test_a_recorder_that_failed_to_start_leaves_no_mute_behind():
    """Nothing is being recorded, so the output stays where it was."""
    sm = _manager(recorder_starts=False)

    sm._start_recording()

    sm.output_mute.restore.assert_called_once()


# ---- the order --------------------------------------------------------------


def test_the_start_beep_is_audible_before_the_output_is_muted():
    sm = _manager()
    order = []
    sm.audio_feedback.play_start_sound.side_effect = lambda: order.append("beep")
    sm.output_mute.mute.side_effect = lambda: order.append("mute")

    sm._start_recording()

    assert order == ["beep", "mute"]


def test_the_stop_beep_is_audible_after_the_output_is_unmuted():
    sm = _manager()
    order = []
    sm.audio_feedback.play_stop_sound.side_effect = lambda: order.append("beep")
    sm.output_mute.restore.side_effect = lambda: order.append("restore")

    sm.stop_recording()

    assert order == ["restore", "beep"]


def test_the_cancel_beep_is_audible_after_the_output_is_unmuted():
    sm = _manager()
    order = []
    sm.audio_feedback.play_cancel_sound.side_effect = lambda: order.append("beep")
    sm.output_mute.restore.side_effect = lambda: order.append("restore")

    sm.cancel_active_recording()

    assert order == ["restore", "beep"]


# ---- a failure here must not break the dictation ----------------------------


def test_a_mute_that_fails_does_not_stop_the_recording():
    sm = _manager()
    sm.output_mute.mute.side_effect = OSError("no CoreAudio")

    sm._start_recording()

    sm.audio_recorder.start_recording.assert_called_once()


def test_a_restore_that_fails_does_not_stop_the_recording():
    sm = _manager()
    sm.output_mute.restore.side_effect = OSError("no CoreAudio")
    stopped = threading.Event()
    sm.audio_recorder.stop_recording.side_effect = lambda: stopped.set()

    sm.stop_recording()

    assert stopped.wait(timeout=2), "the recording stop worker did not close the microphone"
    sm.audio_recorder.stop_recording.assert_called_once()


# ---- the start cue is heard before the output goes quiet ---------------------


def test_the_mute_waits_for_the_start_cue_to_finish():
    sm = _manager()
    sm.audio_feedback.start_sound_seconds.return_value = 0.15

    sm._start_recording()

    sm.output_mute.mute.assert_not_called()
    import time

    time.sleep(0.4)
    sm.output_mute.mute.assert_called_once()


def test_a_stop_before_the_cue_ends_never_mutes_afterwards():
    sm = _manager()
    sm.audio_feedback.start_sound_seconds.return_value = 0.15
    sm._start_recording()

    sm._restore_output()
    import time

    time.sleep(0.4)

    sm.output_mute.mute.assert_not_called()
    sm.output_mute.restore.assert_called_once()
