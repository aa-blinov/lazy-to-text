"""What the optional LLM step does to a dictation, and what happens
when it cannot.

The contract under test is one sentence: **a failure in post-processing
must never cost the user their words.** The alternative — refusing to
deliver when the step fails — means one dropped Wi-Fi packet or an
Ollama that was never started swallows whatever somebody just spoke
into a microphone.

The cost of that choice is that raw text can arrive where tidied text
was asked for, and that cost is only acceptable if it is *visible*.
So the same tests also pin that the fallback says so, and that it says
it without writing the dictation into the log file on the way.
"""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

from app.llm import LLMError, LLMUnavailable

SPOKEN = "привет мир как дела сегодня"


def _state_manager(section=None, transcribed=SPOKEN, outcome="pasted"):
    """Half-real StateManager, as the other pipeline suites build it."""
    from app.state_manager import StateManager

    sm = StateManager.__new__(StateManager)
    sm.audio_recorder = MagicMock()
    sm.audio_recorder.get_audio_duration.return_value = 1.5
    sm.backend = MagicMock()
    sm.backend.transcribe.return_value = transcribed
    sm.clipboard_manager = MagicMock()
    sm.clipboard_manager.deliver_transcription.return_value = outcome
    sm.clipboard_manager.paste_combo.return_value = "Cmd+V"
    sm.config_manager = MagicMock()
    sm.config_manager.get_section.return_value = (
        {} if section is None else section
    )
    sm.history_manager = MagicMock()
    sm.history_update_callback = None
    sm.delivery_reported_callback = None
    sm.system_tray = MagicMock()
    sm.audio_feedback = MagicMock()
    sm.is_processing = False
    sm.is_model_loading = False
    sm.last_transcription = None
    sm._pending_model_change = None
    sm._state_lock = threading.Lock()
    sm.logger = logging.getLogger("test.llm_pipeline")
    return sm


ON = {
    "enabled": True,
    "provider": "ollama",
    "model": "qwen2.5:7b",
    "base_url": "http://127.0.0.1:11434",
    "mode": "clean",
}


# ---- the step is optional ---------------------------------------------------


def test_an_unconfigured_step_never_touches_the_network():
    """Off is the default, and "off" has to mean the app makes no
    outbound connection at all — not that it connects and gets ignored."""
    sm = _state_manager(section={})

    with patch("app.llm.client._open") as urlopen:
        assert sm._postprocess_with_llm(SPOKEN) == SPOKEN

    urlopen.assert_not_called()


def test_enabling_the_box_without_naming_a_model_is_still_off():
    """Ticking "rewrite before pasting" and not yet typing a model is
    the state a user reaches first. It must not become a 404."""
    sm = _state_manager(section={"enabled": True, "model": ""})

    with patch("app.llm.client._open") as urlopen:
        assert sm._postprocess_with_llm(SPOKEN) == SPOKEN

    urlopen.assert_not_called()


# ---- it works ---------------------------------------------------------------


def test_the_reply_is_what_gets_delivered():
    sm = _state_manager(section=ON)

    with patch("app.state_manager.llm_complete", return_value="Привет, мир!"):
        sm._transcription_pipeline(b"audio")

    delivered = sm.clipboard_manager.deliver_transcription.call_args[0][0]
    assert delivered == "Привет, мир!\u00A0"


def test_history_records_what_the_user_actually_received():
    """Not the raw recognition. History is the record of a dictation, and
    the dictation the user experienced is the one that was pasted — a
    history entry showing text they never got is its own kind of lie."""
    sm = _state_manager(section=ON)

    with patch("app.state_manager.llm_complete", return_value="Привет, мир!"):
        sm._transcription_pipeline(b"audio")

    stored = sm.history_manager.add_entry.call_args.kwargs["text"]
    assert stored == "Привет, мир!"


def test_the_step_reports_that_it_ran_and_what_it_cost():
    """A cloud call is seconds, not the sub-second the recogniser takes.
    A dictation that goes quiet with no explanation is
    indistinguishable from a hang, and the whole point of the step being
    visible is that the wait was ours and not the app's."""
    sm = _state_manager(section=ON)
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    sm.logger.addHandler(handler)
    sm.logger.setLevel(logging.DEBUG)

    try:
        with patch("app.state_manager.llm_complete", return_value="ok"):
            sm._transcription_pipeline(b"audio")
    finally:
        sm.logger.removeHandler(handler)

    reports = [
        r for r in records
        if getattr(r, "user_message", False) and "Post-processed" in r.getMessage()
    ]
    assert reports, "a successful post-processing step said nothing"
    message = reports[0].getMessage()
    assert "ollama" in message and "qwen2.5:7b" in message, message


# ---- it fails ---------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        LLMUnavailable("could not reach (ConnectionRefusedError)"),
        LLMError("the server answered HTTP 500"),
        LLMError("the model returned no text"),
    ],
)
def test_a_failed_step_still_delivers_the_words(error):
    """The whole reason the fallback exists. A dictation app that drops
    what somebody said because an optional feature could not reach a
    server has broken its one promise."""
    sm = _state_manager(section=ON)

    with patch("app.state_manager.llm_complete", side_effect=error):
        sm._transcription_pipeline(b"audio")

    delivered = sm.clipboard_manager.deliver_transcription.call_args[0][0]
    assert delivered == f"{SPOKEN}\u00A0"


def test_the_fallback_is_announced_and_not_silent():
    """Delivering raw text where tidied text was asked for is the price
    of never losing a dictation. The user has to be able to see they
    are being charged it, or the step is just a slower app."""
    sm = _state_manager(section=ON)
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    sm.logger.addHandler(handler)
    sm.logger.setLevel(logging.DEBUG)

    try:
        with patch("app.state_manager.llm_complete",
                   side_effect=LLMUnavailable("no daemon")):
            sm._transcription_pipeline(b"audio")
    finally:
        sm.logger.removeHandler(handler)

    failures = [
        r for r in records
        if r.levelno >= logging.WARNING and getattr(r, "user_message", False)
    ]
    assert failures, "the fallback was silent"
    assert "HTTP 500" not in failures[0].getMessage()
    assert "no daemon" in failures[0].getMessage()


def test_the_fallback_does_not_write_the_dictation_to_the_log_file():
    """``_NoSensitiveToFile`` drops records tagged ``sensitive`` from
    ``app.log`` — but only from records that carry the tag. This step
    may be talking to a cloud provider, so neither the input nor the
    output is logged, flagged or otherwise: the dictation must not
    reach a file that is unbounded, on disk, and not cleared by "Clear
    history"."""
    sm = _state_manager(section=ON)
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    sm.logger.addHandler(handler)
    sm.logger.setLevel(logging.DEBUG)

    try:
        with patch("app.state_manager.llm_complete",
                   side_effect=LLMUnavailable("no daemon")):
            sm._transcription_pipeline(b"audio")
    finally:
        sm.logger.removeHandler(handler)

    from app.bootstrap import _NoSensitiveToFile

    keep = _NoSensitiveToFile()
    for record in records:
        if SPOKEN in record.getMessage():
            assert not keep.filter(record), (
                "the dictation reached a record that app.log would write"
            )


def test_a_step_that_fails_still_lets_history_record_the_dictation():
    sm = _state_manager(section=ON)

    with patch("app.state_manager.llm_complete",
               side_effect=LLMUnavailable("no daemon")):
        sm._transcription_pipeline(b"audio")

    stored = sm.history_manager.add_entry.call_args.kwargs["text"]
    assert stored == SPOKEN


# ---- which profile a dictation runs -------------------------------------
#
# The step resolves a profile per dictation rather than reading the flat
# keys, and the reason it can do that without a migration is that a
# section with no ``profiles`` key resolves to the one profile the flat
# keys describe. Both paths are pinned here, because the fallback is the
# thing that lets an existing install keep working.


def _section_with_profiles(**overrides):
    section = dict(ON)
    section.update(
        {
            "active_profile": "work",
            "profiles": [
                {**ON, "id": "work", "name": "Work"},
                {
                    "id": "letters",
                    "name": "Letters",
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "base_url": "https://api.openai.com/v1",
                    "mode": "formal",
                },
            ],
        }
    )
    section.update(overrides)
    return section


def test_a_dictation_runs_the_active_profile():
    sm = _state_manager(section=_section_with_profiles())

    with patch("app.state_manager.llm_complete", return_value="ok") as call:
        sm._transcription_pipeline(b"audio")

    settings = call.call_args[0][1]
    assert settings.model == "qwen2.5:7b"
    assert settings.provider == "ollama"


def test_an_override_runs_that_profile_for_this_dictation():
    sm = _state_manager(section=_section_with_profiles())

    with patch("app.state_manager.llm_complete", return_value="ok") as call:
        sm._postprocess_with_llm("текст", "letters")

    settings = call.call_args[0][1]
    assert settings.provider == "openai"
    assert settings.mode == "formal"


def test_an_override_does_not_become_the_default():
    """It is resolved per dictation and never written to the config.
    An override that persisted would silently change every later
    dictation, which is the opposite of what "for this one" says."""
    section = _section_with_profiles()
    sm = _state_manager(section=section)

    with patch("app.state_manager.llm_complete", return_value="ok"):
        sm._postprocess_with_llm("текст", "letters")

    assert section["active_profile"] == "work"
    assert sm.profile_override_id() == ""


def test_a_profile_with_its_own_prompt_sends_that_prompt():
    section = _section_with_profiles(
        profiles=[
            {
                **ON,
                "id": "work",
                "name": "Work",
                "custom_prompt": "Only fix commas.",
            }
        ],
        active_profile="work",
    )
    sm = _state_manager(section=section)

    with patch("app.state_manager.llm_complete", return_value="ok") as call:
        sm._postprocess_with_llm("текст")

    settings = call.call_args[0][1]
    assert settings.system_prompt.startswith("Only fix commas.")


def test_a_legacy_config_still_post_processes():
    """No ``profiles`` key at all — the shape every existing install has
    on disk. The step has to run exactly as it did before."""
    sm = _state_manager(section=dict(ON))

    with patch("app.state_manager.llm_complete", return_value="Привет") as call:
        result = sm._postprocess_with_llm("привет")

    assert result == "Привет"
    settings = call.call_args[0][1]
    assert settings.model == "qwen2.5:7b"
    assert settings.system_prompt, "the mode's own prompt must still be sent"


def test_the_override_is_read_from_the_manager_itself():
    """The picker and the pipeline are on different threads, so the
    value is read at dictation time rather than captured when the
    button was pressed."""
    sm = _state_manager(section=_section_with_profiles())

    sm.set_profile_override("letters")

    with patch("app.state_manager.llm_complete", return_value="ok") as call:
        sm._transcription_pipeline(b"audio")

    assert call.call_args[0][1].provider == "openai"


def test_clearing_the_override_goes_back_to_the_default():
    sm = _state_manager(section=_section_with_profiles())

    sm.set_profile_override("letters")
    sm.set_profile_override("")

    with patch("app.state_manager.llm_complete", return_value="ok") as call:
        sm._postprocess_with_llm("текст")

    assert call.call_args[0][1].provider == "ollama"
