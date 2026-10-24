"""Long audio must reach every model in pieces the model accepts.

QA-JOURNEYS-1 / QA-RUNTIME-3: ``vosk-ru-small`` fails with an ONNX
``Reshape`` error on any input longer than about 20 s, and the chunker
cut at 25 s, so every dictation or file past that length was lost. The
limit is a property of the model's graph, so the cap is per model, a cut
lands in a pause, and a chunk the model still rejects is halved rather
than failing the recording.

No test loads a model: the fakes below reproduce the failure by
rejecting input longer than the limit measured against the real
``vosk-model-small-ru`` (a hand measurement, see CLAUDE.md).
"""

from __future__ import annotations

import numpy as np
import pytest

from app.backends import onnx_backend as ob
from app.backends.onnx_backend import (
    OnnxAsrBackend,
    _chunk_samples_for,
    _transcribe_chunked,
)
from tests.backends.test_onnx_asr_backend import (
    _install_fake_onnx_asr,
    _reset_after_probe_load,
    _wait,
)

SR = 16_000
VOSK = "alphacep/vosk-model-small-ru"
GRAPH_LIMIT = int(20.05 * SR)


class _GraphLimitedModel:
    """Raises like onnxruntime does for an input past the graph's limit."""

    def __init__(self, limit=GRAPH_LIMIT):
        self.limit = limit
        self.seen: list[int] = []

    def recognize(self, audio, **_kw):
        self.seen.append(len(audio))
        if len(audio) > self.limit:
            raise RuntimeError(
                "[ONNXRuntimeError] : 1 : FAIL : Reshape node cannot be reshaped"
            )
        return "слово"


def test_vosk_gets_a_chunk_below_its_graph_limit_and_others_keep_25_s():
    assert _chunk_samples_for(VOSK) < GRAPH_LIMIT
    assert _chunk_samples_for("alphacep/vosk-model-ru") < GRAPH_LIMIT
    assert _chunk_samples_for("istupakov/gigaam-v3-onnx") == 25 * SR
    assert _chunk_samples_for("") == 25 * SR


def test_a_minute_of_audio_goes_through_a_model_that_rejects_over_20_seconds():
    model = _GraphLimitedModel()
    audio = np.zeros(60 * SR, dtype=np.float32)

    text = _transcribe_chunked(model, audio, {}, _chunk_samples_for(VOSK))

    assert text and text.split() == ["слово"] * len(model.seen)
    assert max(model.seen) <= GRAPH_LIMIT
    assert sum(model.seen) == 60 * SR


def test_the_default_cap_is_longer_than_the_vosk_graph_accepts():
    """Why the per-model cap exists: the default is above the limit."""
    assert ob._CHUNK_SAMPLES > GRAPH_LIMIT


def test_a_chunk_the_model_rejects_is_halved_and_retried():
    """A limit nobody measured costs speed, not the recording."""
    model = _GraphLimitedModel(limit=9 * SR)
    audio = np.zeros(25 * SR, dtype=np.float32)

    text = _transcribe_chunked(model, audio, {}, 25 * SR)

    assert text
    assert max(s for s in model.seen if s <= 9 * SR) <= 9 * SR
    assert sum(s for s in model.seen if s <= 9 * SR) == 25 * SR


def test_the_cut_lands_in_a_pause_not_in_a_word():
    """Loud everywhere except a quiet gap near the end of the first window."""
    cap = 15 * SR
    audio = (np.random.default_rng(1).uniform(-0.5, 0.5, 40 * SR)).astype(np.float32)
    gap_start = int(13.6 * SR)
    audio[gap_start : gap_start + int(0.3 * SR)] = 0.0
    seen: list[tuple[int, int]] = []

    class _Rec:
        pos = 0

        def recognize(self, chunk, **_kw):
            seen.append((self.pos, self.pos + len(chunk)))
            self.pos += len(chunk)
            return "x"

    _transcribe_chunked(_Rec(), audio, {}, cap)

    first_end = seen[0][1]
    assert gap_start <= first_end <= gap_start + int(0.3 * SR) + 1_600, first_end
    assert seen[-1][1] == 40 * SR


def test_flat_audio_is_cut_exactly_at_the_cap():
    seen: list[int] = []

    class _Rec:
        def recognize(self, chunk, **_kw):
            seen.append(len(chunk))
            return "x"

    _transcribe_chunked(_Rec(), np.zeros(60 * SR, dtype=np.float32), {}, 25 * SR)

    assert seen == [25 * SR, 25 * SR, 10 * SR]


def test_the_backend_dictation_path_uses_the_per_model_cap(monkeypatch):
    model = _GraphLimitedModel()
    _install_fake_onnx_asr(monkeypatch, recognize_fn=model.recognize)

    backend = OnnxAsrBackend(model=VOSK, family="gigaam", device="cpu")
    backend.load()
    assert _wait(lambda: backend.status() == "ready")
    _reset_after_probe_load(model.seen)

    text = backend.transcribe(np.zeros(60 * SR, dtype=np.float32))

    assert text
    assert max(model.seen) <= GRAPH_LIMIT


def test_the_file_path_uses_the_per_model_cap(monkeypatch, tmp_path):
    model = _GraphLimitedModel()
    _install_fake_onnx_asr(monkeypatch, recognize_fn=model.recognize)
    monkeypatch.setattr(
        ob, "_decode_audio_file",
        lambda _p: np.zeros(90 * SR, dtype=np.float32),
    )

    backend = OnnxAsrBackend(model=VOSK, family="gigaam", device="cpu")
    backend.load()
    assert _wait(lambda: backend.status() == "ready")
    _reset_after_probe_load(model.seen)

    assert backend.transcribe_file(str(tmp_path / "long.wav"))
    assert max(model.seen) <= GRAPH_LIMIT
