"""Every way a dictation can fail ends in an outcome the user can see.

QA-JOURNEYS-1, QA-JOURNEYS-2, QA-RUNTIME-1: a failed transcription, a
recording that never started and an exception out of post-processing all
used to end in silence - no ``delivery``, no history, in two of them the
words gone and in one the system output left muted.
"""

from __future__ import annotations

import http.client
import logging
import threading
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.backends.base import TranscriptionError


def _sm(tmp_path, monkeypatch, *, llm=None):
    from app.state_manager import StateManager

    monkeypatch.setattr("app.utils.get_project_logs_path", lambda: str(tmp_path))
    sm = StateManager.__new__(StateManager)
    sm.audio_recorder = MagicMock()
    sm.audio_recorder.get_audio_duration.return_value = 2.0
    sm.audio_recorder.last_error = None
    sm.backend = MagicMock()
    sm.backend.transcribe.return_value = "привет мир"
    sm.backend.current_model.return_value = "m"
    sm.backend.current_language.return_value = None
    sm.clipboard_manager = MagicMock()
    sm.clipboard_manager.deliver_transcription.return_value = "copied"
    sm.clipboard_manager.paste_combo.return_value = "Cmd+V"
    sm.config_manager = MagicMock()
    sm.config_manager.get_section.return_value = llm or {}
    sm.config_manager.get_audio_config.return_value = {"mute_output_on_record": True}
    sm.history_manager = MagicMock()
    sm.history_update_callback = None
    sm.is_processing = False
    sm.is_model_loading = False
    sm.last_transcription = None
    sm._pending_model_change = None
    sm._state_lock = threading.Lock()
    sm.logger = logging.getLogger("test.failure_outcomes")
    sm.audio_feedback = MagicMock()
    sm.audio_feedback.start_sound_seconds.return_value = 0.0
    sm.system_tray = MagicMock()
    sm.output_mute = MagicMock()
    sm.reported = []
    sm.delivery_reported_callback = lambda *a: sm.reported.append(a)
    return sm


AUDIO = np.full(16_000, 0.1, dtype=np.float32)


@pytest.mark.parametrize(
    "error",
    [
        TranscriptionError("The model failed while transcribing: boom"),
        RuntimeError("Subprocess error: TranscriptionError: The model failed while transcribing: boom"),
        RuntimeError("Subprocess worker pipe closed"),
    ],
)
def test_a_failed_transcription_reports_failed_with_a_readable_reason(tmp_path, monkeypatch, error):
    sm = _sm(tmp_path, monkeypatch)
    sm.backend.transcribe.side_effect = error

    sm._transcription_pipeline(AUDIO)

    assert len(sm.reported) == 1
    outcome, detail, text = sm.reported[0]
    assert outcome == "failed"
    assert detail and "Subprocess error" not in detail
    assert "TranscriptionError:" not in detail
    sm.history_manager.add_entry.assert_not_called()
    sm.clipboard_manager.deliver_transcription.assert_not_called()


def test_a_failed_transcription_keeps_the_audio(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)
    sm.backend.transcribe.side_effect = TranscriptionError("boom")

    sm._transcription_pipeline(AUDIO)

    kept = list((tmp_path / "unprocessed-recordings").glob("*.wav"))
    assert len(kept) == 1
    import wave

    with wave.open(str(kept[0])) as w:
        assert w.getframerate() == 16_000 and w.getnframes() == len(AUDIO)
    assert str(kept[0]) in sm.reported[0][1]


def test_only_the_last_few_unprocessed_recordings_are_kept(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)
    names = iter(f"recording-{i:04d}" for i in range(10))
    monkeypatch.setattr("app.state_manager.time.strftime", lambda _fmt: next(names))
    monkeypatch.setattr("app.state_manager.time.time", lambda: 5.0)

    for _ in range(6):
        assert sm._keep_recording(AUDIO)

    names = sorted(p.name for p in (tmp_path / "unprocessed-recordings").glob("*.wav"))
    assert names == [
        "recording-0003-000.wav", "recording-0004-000.wav", "recording-0005-000.wav",
    ]


def test_no_audio_at_all_is_an_outcome_not_silence(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)

    sm._transcription_pipeline(None)

    assert sm.reported and sm.reported[0][0] == "failed"


def test_an_error_after_transcription_reports_failed_and_keeps_the_audio(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)
    sm.clipboard_manager.deliver_transcription.side_effect = OSError("clipboard gone")

    sm._transcription_pipeline(AUDIO)

    assert [r[0] for r in sm.reported] == ["failed"]
    assert list((tmp_path / "unprocessed-recordings").glob("*.wav"))


def test_a_recorder_that_fails_to_start_restores_the_output_and_reports(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)
    sm.audio_recorder.start_recording.return_value = False
    sm.audio_recorder.last_error = "Error querying device 99"

    sm._start_recording()

    sm.output_mute.mute.assert_called_once()
    sm.output_mute.restore.assert_called_once()
    assert sm.reported[0][0] == "failed"
    assert "device 99" in sm.reported[0][1]


def test_a_recorder_that_raises_on_start_restores_the_output_and_reports(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)
    sm.audio_recorder.start_recording.side_effect = OSError("no such device")

    sm._start_recording()

    sm.output_mute.restore.assert_called_once()
    assert sm.reported[0][0] == "failed"


def test_a_stream_that_breaks_after_start_restores_the_output_and_reports(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)

    sm._on_recording_failed("Invalid sample rate")

    sm.output_mute.restore.assert_called_once()
    assert sm.reported[0][0] == "failed" and "Invalid sample rate" in sm.reported[0][1]


def test_reaching_the_time_limit_restores_the_output(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)
    sm._transcription_pipeline = MagicMock()

    sm.handle_max_recording_duration_reached(AUDIO)

    sm.output_mute.restore.assert_called_once()


# ---- the optional post-processing step never costs the words ----------------


def _llm(**over):
    base = {
        "enabled": True, "provider": "ollama", "model": "m",
        "base_url": "http://127.0.0.1:11434", "api_key": "",
    }
    base.update(over)
    return base


@pytest.mark.parametrize(
    "error",
    [
        ValueError("unknown url type: 'myserver'"),
        http.client.BadStatusLine("GARBAGE"),
        http.client.IncompleteRead(b""),
        UnicodeEncodeError("latin-1", "ключ", 0, 1, "bad"),
        RuntimeError("anything"),
    ],
)
def test_any_exception_from_the_llm_step_delivers_the_raw_text(tmp_path, monkeypatch, error):
    sm = _sm(tmp_path, monkeypatch, llm=_llm())

    with patch("app.state_manager.llm_complete", side_effect=error):
        sm._transcription_pipeline(AUDIO)

    sm.clipboard_manager.deliver_transcription.assert_called_once()
    assert sm.clipboard_manager.deliver_transcription.call_args.args[0].startswith("привет мир")
    sm.history_manager.add_entry.assert_called_once()
    assert sm.reported[0][0] == "copied"


@pytest.mark.parametrize("base_url", ["myserver", "127.0.0.1", "http://[::1", "file:///etc/passwd", "http://a b"])
def test_a_malformed_server_address_delivers_the_raw_text_and_says_why(tmp_path, monkeypatch, base_url, caplog):
    sm = _sm(tmp_path, monkeypatch, llm=_llm(base_url=base_url))

    with caplog.at_level(logging.WARNING, logger="test.failure_outcomes"):
        with patch("app.state_manager.llm_complete") as complete:
            sm._transcription_pipeline(AUDIO)

    complete.assert_not_called()
    assert sm.reported[0][0] == "copied"
    assert any(
        getattr(r, "user_message", False) and "Post-processing" in r.getMessage()
        for r in caplog.records
    )


def test_a_key_with_a_line_break_never_reaches_a_log_line(tmp_path, monkeypatch, caplog):
    secret = "sk-SECRETVALUE123"
    sm = _sm(tmp_path, monkeypatch, llm=_llm(
        provider="openai", base_url="https://api.example.com/v1",
        api_key=f"{secret}\nsecond",
    ))

    with caplog.at_level(logging.DEBUG):
        sm._transcription_pipeline(AUDIO)

    assert secret not in caplog.text
    assert sm.reported[0][0] == "copied"


def test_a_recording_too_short_to_be_speech_is_not_a_model_failure(tmp_path, monkeypatch):
    """QA-JOURNEYS-R2: a double tap of the hotkey reached the model and came
    back as "the speech model failed" with a raw ONNX message."""
    sm = _sm(tmp_path, monkeypatch)
    sm.audio_recorder.get_audio_duration.return_value = 0.05
    sm.backend.transcribe.side_effect = TranscriptionError("[ONNXRuntimeError] INVALID_ARGUMENT Conv")

    sm._transcription_pipeline(np.zeros(800, dtype=np.float32))

    sm.backend.transcribe.assert_not_called()
    assert len(sm.reported) == 1
    outcome, detail, _text = sm.reported[0]
    assert outcome == "failed"
    assert "too short" in detail
    assert "ONNX" not in detail and "model failed" not in detail
    assert not (tmp_path / "unprocessed-recordings").exists()


def test_a_press_that_ended_before_any_audio_arrived_says_too_short(tmp_path, monkeypatch):
    """QA-RC-3: no frames at all from a sub-block press is a short press,
    not a microphone that needs the app restarted."""
    sm = _sm(tmp_path, monkeypatch)
    sm.audio_recorder.empty_reason = "too_short"

    sm._transcription_pipeline(None)

    assert len(sm.reported) == 1
    outcome, detail, _text = sm.reported[0]
    assert outcome == "failed"
    assert "too short" in detail
    assert "microphone" not in detail and "restart" not in detail.lower()


def test_no_audio_from_a_running_stream_still_blames_the_microphone(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)
    sm.audio_recorder.empty_reason = "no_frames"

    sm._transcription_pipeline(None)

    assert "no audio came from the microphone" in sm.reported[0][1]


def test_a_short_buffer_is_padded_before_the_model_sees_it():
    from app.backends.onnx_backend import _MIN_MODEL_SAMPLES, _transcribe_chunked

    seen = []

    class _Model:
        def recognize(self, audio, **_kw):
            seen.append(len(audio))
            return "ok"

    assert _transcribe_chunked(_Model(), np.zeros(800, dtype=np.float32), {}) == "ok"
    assert seen == [_MIN_MODEL_SAMPLES]


def test_a_failed_transcription_carries_no_runtime_text():
    import app.backends.onnx_backend as mod

    backend = mod.OnnxAsrBackend.__new__(mod.OnnxAsrBackend)
    import threading as _t

    backend._lock = _t.RLock()
    backend._shutdown = False
    backend._status = "ready"
    backend._model = object()  # has no recognize: raises AttributeError
    backend._inference_settings = None
    backend._vad = None
    backend._vad_enabled = False
    backend._model_name = "x"
    backend._auto_language = None
    backend._language = None

    try:
        backend.transcribe(np.zeros(16_000, dtype=np.float32))
    except TranscriptionError as exc:
        assert "AttributeError" not in str(exc) and "recognize" not in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a TranscriptionError")


# ---- silence, strays and the too-short kind (QA-RUNTIME-F10, QA-JOURNEYS-F1/F7) ------


def _quiet(seconds=2.0, level=0.0):
    return np.full(int(16_000 * seconds), level, dtype=np.float32)


def test_a_silent_recording_never_reaches_the_model_and_pastes_nothing(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)

    sm._transcription_pipeline(_quiet(5.0, 0.0))

    sm.backend.transcribe.assert_not_called()
    sm.clipboard_manager.deliver_transcription.assert_not_called()
    sm.history_manager.add_entry.assert_not_called()


def test_a_silent_recording_says_which_microphone_it_came_from(tmp_path, monkeypatch, caplog):
    sm = _sm(tmp_path, monkeypatch)
    sm.audio_recorder.last_device_name = "Микрофон (iPhone)"

    with caplog.at_level(logging.INFO):
        sm._transcription_pipeline(_quiet(5.0, 0.0))

    said = [r.getMessage() for r in caplog.records if getattr(r, "user_message", False)]
    assert any('the recording from "Микрофон (iPhone)" is silent' in m for m in said), said


def test_quiet_speech_above_the_floor_still_goes_to_the_model(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)
    sm.backend.transcribe.return_value = "привет мир"

    sm._transcription_pipeline(_quiet(2.0, 0.02))

    sm.backend.transcribe.assert_called_once()
    sm.clipboard_manager.deliver_transcription.assert_called_once()


@pytest.mark.parametrize("word,seconds,level", [
    ("с", 0.4, 0.05),      # an accidental tap: one letter from 0.4 s
    ("а", 3.0, 0.005),     # a letter out of the room's noise
    ("угу", 2.0, 0.005),   # a short word out of the room's noise
])
def test_a_stray_one_word_result_is_not_pasted(tmp_path, monkeypatch, word, seconds, level):
    sm = _sm(tmp_path, monkeypatch)
    sm.audio_recorder.get_audio_duration.return_value = seconds
    sm.backend.transcribe.return_value = word

    sm._transcription_pipeline(_quiet(seconds, level))

    sm.clipboard_manager.deliver_transcription.assert_not_called()
    sm.history_manager.add_entry.assert_not_called()


def test_a_real_short_word_in_a_normal_voice_is_kept(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)
    sm.audio_recorder.get_audio_duration.return_value = 1.5
    sm.backend.transcribe.return_value = "да"

    sm._transcription_pipeline(_quiet(1.5, 0.1))

    sm.clipboard_manager.deliver_transcription.assert_called_once()


def test_a_too_short_recording_reports_its_kind_to_the_runtime(tmp_path, monkeypatch):
    sm = _sm(tmp_path, monkeypatch)
    sm.audio_recorder.get_audio_duration.return_value = 0.1
    events = []
    sm.delivery_event_callback = lambda *a: events.append(a)

    sm._transcription_pipeline(_quiet(0.1, 0.1))

    outcome, detail, text, kind = events[0]
    assert (outcome, kind) == ("failed", "too_short")
    assert "too short" in detail
    sm.backend.transcribe.assert_not_called()


def test_the_runtime_forwards_the_kind_in_the_delivery_event():
    import json

    from app.server.events import bus
    from app.server.runtime import Runtime

    # A new subscriber is first replayed the sticky events other tests left on
    # the process-wide bus, so only the delivery events are looked at.
    sub = bus.subscribe()
    try:
        Runtime._on_delivery(object(), "failed", "d", "", "too_short")
        Runtime._on_delivery(object(), "pasted", "", "text")
        deliveries = []
        while len(deliveries) < 2:
            item = sub.get(1)
            assert item is not None, "the delivery events never arrived"
            if item[0] == "delivery":
                deliveries.append(json.loads(item[1]))
    finally:
        sub.close()

    assert deliveries[0]["kind"] == "too_short"
    assert "kind" not in deliveries[1]


@pytest.mark.parametrize("platform,present,absent", [
    ("darwin", "System Settings", "Windows Sound settings"),
    ("win32", "Windows Sound settings", "System Settings"),
    ("linux", "system sound settings", "Windows"),
])
def test_the_silent_microphone_hint_names_the_platforms_own_settings(platform, present, absent, monkeypatch):
    from app import audio_recorder

    monkeypatch.setattr(audio_recorder.sys, "platform", platform)
    text = audio_recorder._where_sound_is_muted()
    assert present in text and absent not in text
