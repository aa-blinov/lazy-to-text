"""The silero VAD switch.

A checkbox in Settings → Microphone: the recording is cut into its
speech segments before it reaches the model, so the silences cost
nothing.  The VAD is a second ONNX model, loaded in the worker, and
its result has a different shape than a plain transcription — a stream
of segments instead of one text.  Both are checked here.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest


def _backend_with_model(monkeypatch, recognize_return="fake transcription"):
    """A backend whose model is loaded and ready."""
    from app.backends.onnx_backend import OnnxAsrBackend

    fake_model = MagicMock()
    fake_model.recognize.return_value = recognize_return
    fake_model.with_vad.side_effect = lambda vad: fake_model

    fake_module = types.ModuleType("onnx_asr")
    fake_module.load_model = MagicMock(return_value=fake_model)
    fake_module.load_vad = MagicMock(return_value="vad-instance")
    monkeypatch.setitem(sys.modules, "onnx_asr", fake_module)

    backend = OnnxAsrBackend(model="x")
    backend._model = fake_model
    backend._status = "ready"
    return backend, fake_model, fake_module


# ---- the switch ------------------------------------------------------------


def test_the_vad_is_off_until_the_user_asks_for_it(monkeypatch):
    backend, fake_model, _ = _backend_with_model(monkeypatch)

    backend.transcribe(np.zeros(16000, dtype=np.float32))

    fake_model.with_vad.assert_not_called()


def test_turning_the_vad_on_loads_the_silero_model(monkeypatch):
    backend, _, fake_module = _backend_with_model(monkeypatch)

    backend.set_vad_enabled(True)

    fake_module.load_vad.assert_called_once_with("silero")


def test_turning_the_vad_off_drops_it(monkeypatch):
    backend, fake_model, _ = _backend_with_model(monkeypatch)
    backend.set_vad_enabled(True)

    backend.set_vad_enabled(False)
    backend.transcribe(np.zeros(16000, dtype=np.float32))

    fake_model.with_vad.assert_not_called()


def test_a_vad_that_cannot_be_loaded_leaves_the_feature_off(monkeypatch):
    """A dictation without the VAD beats no dictation."""
    backend, fake_model, fake_module = _backend_with_model(monkeypatch)
    fake_module.load_vad.side_effect = OSError("no network")

    backend.set_vad_enabled(True)  # must not raise

    backend.transcribe(np.zeros(16000, dtype=np.float32))
    fake_model.with_vad.assert_not_called()


def test_a_model_without_a_vad_adapter_is_not_left_broken(monkeypatch):
    backend, fake_model, _ = _backend_with_model(monkeypatch)
    fake_model.with_vad = None
    backend.set_vad_enabled(True)

    text = backend.transcribe(np.zeros(16000, dtype=np.float32))

    assert text == "fake transcription"


# ---- the result shape ------------------------------------------------------


def test_the_segments_the_vad_finds_are_joined_into_one_text(monkeypatch):
    """The VAD returns the speech it found, not one string.

    The segments are the same utterance split around the silences the
    VAD removed, so their texts belong together in the order they came.
    """
    from app.backends.onnx_backend import OnnxAsrBackend

    class _Segment:
        def __init__(self, text):
            self.start = 0.0
            self.end = 1.0
            self.text = text

    backend, fake_model, _ = _backend_with_model(monkeypatch)
    fake_model.recognize.return_value = iter(
        [_Segment("привет"), _Segment("мир")]
    )
    backend.set_vad_enabled(True)

    text = backend.transcribe(np.zeros(16000, dtype=np.float32))

    assert text == "привет мир"


def test_an_empty_segment_stream_is_silence_not_an_error(monkeypatch):
    """The VAD found no speech — that is "heard nothing", not a failure."""
    backend, fake_model, _ = _backend_with_model(monkeypatch)
    fake_model.recognize.return_value = iter([])
    backend.set_vad_enabled(True)

    assert backend.transcribe(np.zeros(16000, dtype=np.float32)) is None


def test_a_plain_result_still_works(monkeypatch):
    """The plain path is untouched: one object with a ``text``."""
    backend, fake_model, _ = _backend_with_model(monkeypatch)
    result = MagicMock()
    result.text = "обычный текст"
    fake_model.recognize.return_value = result

    assert backend.transcribe(np.zeros(16000, dtype=np.float32)) == "обычный текст"


# ---- the command that carries it to the worker ------------------------------


def test_the_worker_answers_the_vad_command():
    """The worker has to know the command, or the switch is a no-op."""
    import inspect

    from app.backends import subprocess_worker

    source = inspect.getsource(subprocess_worker)
    assert 'op == "set_vad_enabled"' in source


def test_the_parent_backend_forwards_the_command():
    from app.backends.subprocess_backend import SubprocessBackend

    assert hasattr(SubprocessBackend, "set_vad_enabled")


def test_the_registry_backend_forwards_the_command():
    from app.backends.registry_backend import RegistryBackend

    assert hasattr(RegistryBackend, "set_vad_enabled")
