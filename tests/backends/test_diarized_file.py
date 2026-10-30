"""A file run split by speaker: the backend's own part, with the diarizer stubbed.

The speech model and the diarization models are fakes, so this pins what is
ours: how turns become labelled paragraphs, when the plain transcript is used
instead, and that the option crosses the worker pipe and the registry intact.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.backends import onnx_backend as ob
from app.backends.base import TranscriptionError
from app.diarization import Turn

SECOND = 16_000


def _audio(seconds=10):
    return np.zeros(seconds * SECOND, dtype=np.float32)


class _Model:
    """Reads the first sample of the chunk it is given as the text to return."""

    def __init__(self, words):
        self.words = words
        self.calls = []

    def recognize(self, chunk, **kwargs):
        self.calls.append(len(chunk))
        return self.words.pop(0)


@pytest.fixture
def turns(monkeypatch):
    holder = types.SimpleNamespace(value=[])
    monkeypatch.setattr(ob, "_diarize", lambda audio, speakers=None: holder.value)
    return holder


def test_each_turn_is_recognised_alone_and_labelled_in_order_of_appearance(turns):
    turns.value = [Turn(0, 2, 3), Turn(2.5, 4, 1), Turn(5, 7, 3)]
    model = _Model(["first", "second", "third"])

    text = ob._transcribe_by_speaker(model, _audio(), {}, 25 * SECOND, "Speaker")

    assert text == "Speaker 1: first\n\nSpeaker 2: second\n\nSpeaker 1: third"
    assert model.calls == [2 * SECOND, int(1.5 * SECOND), 2 * SECOND]


def test_one_speaker_is_not_labelled(turns):
    turns.value = [Turn(0, 2, 0), Turn(3, 5, 0)]

    assert ob._transcribe_by_speaker(_Model([]), _audio(), {}, 25 * SECOND, "Speaker") is None


def test_no_speech_is_not_labelled_either(turns):
    turns.value = []

    assert ob._transcribe_by_speaker(_Model([]), _audio(), {}, 25 * SECOND, "Speaker") is None


def test_a_turn_the_model_hears_nothing_in_is_left_out_and_numbers_stay_dense(turns):
    turns.value = [Turn(0, 2, 5), Turn(3, 5, 6), Turn(6, 8, 7)]
    model = _Model(["one", None, "three"])

    text = ob._transcribe_by_speaker(model, _audio(), {}, 25 * SECOND, "Спикер")

    assert text == "Спикер 1: one\n\nСпикер 2: three"


def test_the_diarizer_is_refused_clearly_when_its_model_is_not_on_disk(monkeypatch):
    from app import diarization_models

    monkeypatch.setattr(diarization_models, "paths", lambda: None)

    with pytest.raises(TranscriptionError, match="not downloaded"):
        ob._diarize(_audio())


def _ready_backend(monkeypatch, tmp_path, recognize):
    backend = ob.OnnxAsrBackend(model="x")
    model = MagicMock()
    model.recognize.side_effect = recognize
    backend._model = model
    backend._status = "ready"
    monkeypatch.setattr(ob, "_decode_audio_file", lambda path: _audio())
    return backend


def test_transcribe_file_falls_back_to_the_plain_text_for_one_voice(monkeypatch, tmp_path, turns):
    turns.value = [Turn(0, 5, 0)]
    backend = _ready_backend(monkeypatch, tmp_path, lambda chunk, **k: "everything")

    assert backend.transcribe_file("a.wav", diarize=True) == "everything"


def test_transcribe_file_uses_the_turns_when_there_are_two_voices(monkeypatch, tmp_path, turns):
    turns.value = [Turn(0, 3, 0), Turn(4, 7, 1)]
    words = iter(["hello", "hi"])
    backend = _ready_backend(monkeypatch, tmp_path, lambda chunk, **k: next(words))

    out = backend.transcribe_file("a.wav", diarize=True, speaker_label="Speaker")

    assert out == "Speaker 1: hello\n\nSpeaker 2: hi"


def test_a_plain_file_run_never_runs_the_diarizer(monkeypatch, tmp_path):
    monkeypatch.setattr(ob, "_diarize", lambda audio, speakers=None: pytest.fail("diarizer ran"))
    backend = _ready_backend(monkeypatch, tmp_path, lambda chunk, **k: "plain")

    assert backend.transcribe_file("a.wav") == "plain"


def test_the_registry_forwards_the_option_only_when_it_is_set():
    from app.backends.registry_backend import RegistryBackend

    inner = MagicMock()
    backend = RegistryBackend.__new__(RegistryBackend)
    backend._inner = inner

    backend.transcribe_file("a.wav")
    inner.transcribe_file.assert_called_with("a.wav")
    backend.transcribe_file("a.wav", diarize=True, speaker_label="Спикер")
    inner.transcribe_file.assert_called_with("a.wav", diarize=True, speaker_label="Спикер")


def test_the_subprocess_backend_keeps_the_plain_command_and_adds_the_option():
    from app.backends.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend.__new__(SubprocessBackend)
    sent = []
    backend._send_cmd = lambda cmd, timeout=None: sent.append(cmd) or "ok"

    backend.transcribe_file("a.wav")
    backend.transcribe_file("a.wav", diarize=True, speaker_label="Спикер")

    assert sent == [("transcribe_file", "a.wav"), ("transcribe_file", "a.wav", True, "Спикер")]


def test_the_worker_hands_the_option_to_its_backend(monkeypatch):
    from tests.backends.test_subprocess_backend import _drive_worker, _recv_response
    import app.backends.subprocess_worker as worker_mod

    fake = MagicMock()
    fake.status.return_value = "ready"
    fake.transcribe_file.return_value = "Спикер 1: a"
    monkeypatch.setattr(worker_mod, "_RegistryBackend", lambda **_kw: fake)
    parent, t, _run_all = _drive_worker([], init_kwargs={"model": "x"})
    try:
        assert _recv_response(parent, 5) == ("ok", None)
        parent.send(("cmd", 1, "transcribe_file", "/x.wav", True, "Спикер"))
        assert _recv_response(parent, 5) == ("resp", 1, "ok", "Спикер 1: a")
        fake.transcribe_file.assert_called_once_with("/x.wav", diarize=True, speaker_label="Спикер")
        parent.send(("cmd", 2, "transcribe_file", "/y.wav"))
        assert _recv_response(parent, 5)[:3] == ("resp", 2, "ok")
        fake.transcribe_file.assert_called_with("/y.wav")
    finally:
        parent.close()
        t.join(timeout=2)


def test_the_count_of_speakers_travels_to_the_diarizer_and_through_every_layer(monkeypatch):
    from app.backends.registry_backend import RegistryBackend
    from app.backends.subprocess_backend import SubprocessBackend

    seen = []
    monkeypatch.setattr(
        ob, "_diarize",
        lambda audio, speakers=None: seen.append(speakers) or [Turn(0, 1, 0), Turn(1, 2, 1)],
    )
    model = _Model(["a", "b"])
    out = ob._transcribe_by_speaker(model, _audio(3), {}, 10 * SECOND, "S", 4)
    assert seen == [4] and out.startswith("S 1: a")

    inner = MagicMock()
    registry = RegistryBackend.__new__(RegistryBackend)
    registry._inner = inner
    registry.transcribe_file("a.wav", diarize=True, speaker_label="S", speakers=3)
    inner.transcribe_file.assert_called_with("a.wav", diarize=True, speaker_label="S", speakers=3)

    sub = SubprocessBackend.__new__(SubprocessBackend)
    sent = []
    sub._send_cmd = lambda cmd, timeout=None: sent.append(cmd) or "ok"
    sub.transcribe_file("a.wav", diarize=True, speaker_label="S", speakers=3)
    assert sent == [("transcribe_file", "a.wav", True, "S", 3)]
