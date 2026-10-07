"""What the pipeline reports, and what it does with the answer.

Three outcomes came out of ``deliver_transcription`` replacing a bool:
``pasted`` / ``copied`` / ``failed``. Two things depend on that
distinction being carried all the way to the end of the pipeline, and
both are checked here because getting either wrong is invisible in
normal use — a delivered dictation silently missing from History, or a
UI callback taking the whole pipeline down with it.
"""

import logging
import threading
from unittest.mock import MagicMock

import pytest


def _pipeline(outcome, *, history=None, detail_combo="Cmd+V"):
    """Half-real StateManager wired to report ``outcome``.

    Mirrors the helper in ``test_state_manager_cancel`` so the three
    suites stay in sync.
    """
    from app.state_manager import StateManager

    sm = StateManager.__new__(StateManager)

    sm.audio_recorder = MagicMock()
    sm.audio_recorder.get_audio_duration.return_value = 1.5
    sm.backend = MagicMock()
    sm.backend.transcribe.return_value = "привет мир"
    sm.backend.current_model.return_value = "test-model"
    sm.backend.current_language.return_value = None
    sm.clipboard_manager = MagicMock()
    sm.clipboard_manager.deliver_transcription.return_value = outcome
    sm.clipboard_manager.paste_combo.return_value = detail_combo
    sm.history_manager = MagicMock() if history is not False else None
    sm.history_update_callback = None
    sm.delivery_reported_callback = None
    sm.is_processing = False
    sm.is_model_loading = False
    sm.last_transcription = None
    sm._pending_model_change = None
    sm._state_lock = threading.Lock()
    sm.logger = logging.getLogger("test.state_manager_delivery")
    sm.audio_feedback = MagicMock()
    sm.system_tray = MagicMock()
    return sm


# ---- the three outcomes reach the user -------------------------------------


@pytest.mark.parametrize(
    "outcome, detail",
    [
        ("pasted", ""),
        ("copied", "Press Cmd+V in your app"),
        ("failed", ""),
    ],
)
def test_every_outcome_is_reported_to_the_ui(outcome, detail):
    """The window the user is looking at is not this app, so the answer
    has to be handed to the overlay — once, with the fact that changes
    what they do next."""
    sm = _pipeline(outcome)
    reported = []
    sm.delivery_reported_callback = lambda *args: reported.append(args)

    sm._transcription_pipeline(b"audio")

    assert reported == [(outcome, detail)]


def test_the_reported_detail_uses_this_platform_s_shortcut():
    """The detail is the shortcut the user has to press themselves, so a
    hardcoded Ctrl+V would send a Mac user pressing the wrong key."""
    sm = _pipeline("copied", detail_combo="Cmd+Shift+V")
    reported = []
    sm.delivery_reported_callback = lambda *args: reported.append(args)

    sm._transcription_pipeline(b"audio")

    assert reported[0][1] == "Press Cmd+Shift+V in your app"


def test_a_missing_ui_callback_does_not_break_the_pipeline():
    """The callback is optional — the headless CLI-ish runs never
    install one."""
    sm = _pipeline("pasted")
    sm.delivery_reported_callback = None

    sm._transcription_pipeline(b"audio")  # must not raise

    assert sm.last_transcription == "привет мир"


def test_a_raising_ui_callback_does_not_cost_the_user_their_dictation():
    """A UI callback raising used to land in the pipeline's own
    ``except``, which then reported a delivered dictation as a
    processing error — and skipped History entirely."""
    sm = _pipeline("pasted")

    def boom(outcome, detail):
        raise RuntimeError("overlay is gone")

    sm.delivery_reported_callback = boom

    sm._transcription_pipeline(b"audio")  # must not raise

    assert sm.last_transcription == "привет мир"
    sm.history_manager.add_entry.assert_called_once()


# ---- what gets into History ------------------------------------------------


@pytest.mark.parametrize("outcome", ["pasted", "copied"])
def test_a_delivered_dictation_reaches_history(outcome):
    """``copied`` used to be excluded, because the old bool only went
    true when the *keystroke* landed. The text was on the clipboard
    waiting to be pasted and History never heard about it."""
    sm = _pipeline(outcome, history=True)

    sm._transcription_pipeline(b"audio")

    sm.history_manager.add_entry.assert_called_once()
    assert sm.history_manager.add_entry.call_args.kwargs["text"] == (
        "привет мир"
    )
    assert sm.last_transcription == "привет мир"


def test_a_failed_delivery_writes_no_history_entry():
    """Nothing was delivered anywhere, so there is nothing to recover."""
    sm = _pipeline("failed", history=True)

    sm._transcription_pipeline(b"audio")

    sm.history_manager.add_entry.assert_not_called()
    assert sm.last_transcription is None


def test_history_still_runs_when_the_app_has_history_disabled():
    sm = _pipeline("pasted", history=False)

    sm._transcription_pipeline(b"audio")

    assert sm.last_transcription == "привет мир"


# ---- the log line says the same thing --------------------------------------


@pytest.mark.parametrize(
    "outcome, expected",
    [
        ("pasted", "paste keystroke posted"),
        ("copied", "paste it yourself"),
        ("failed", "never reached the clipboard"),
    ],
)
def test_the_delivery_log_line_names_the_outcome(
    outcome, expected, caplog
):
    """The Logs view is what a user reads the next morning to work out
    what happened, so the line has to distinguish the three."""
    sm = _pipeline(outcome)

    with caplog.at_level(logging.INFO, logger="test.state_manager_delivery"):
        sm._transcription_pipeline(b"audio")

    delivery_lines = [
        r.getMessage() for r in caplog.records
        if "Delivery" in r.getMessage()
    ]
    assert len(delivery_lines) == 1, delivery_lines
    assert expected in delivery_lines[0]


def test_the_delivery_log_line_is_marked_as_addressed_to_the_user(caplog):
    """The tag is what the Logs view ranks by — untagged bookkeeping and
    a sentence the app chose to speak used to render identically."""
    sm = _pipeline("pasted")

    with caplog.at_level(logging.INFO, logger="test.state_manager_delivery"):
        sm._transcription_pipeline(b"audio")

    delivery = [r for r in caplog.records if "Delivery" in r.getMessage()]
    assert len(delivery) == 1
    assert getattr(delivery[0], "user_message", False) is True


def test_an_empty_transcription_reports_no_delivery():
    """There is nothing to confirm — the pipeline must not announce a
    delivery that never happened."""
    sm = _pipeline("pasted")
    sm.backend.transcribe.return_value = ""
    reported = []
    sm.delivery_reported_callback = lambda *args: reported.append(args)

    sm._transcription_pipeline(b"audio")

    assert reported == []
    assert sm.last_transcription is None