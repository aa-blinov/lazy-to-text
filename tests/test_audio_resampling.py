from __future__ import annotations

import time

import numpy as np

import app.audio_resampling as resampling


def test_resampling_is_independent_of_chunk_size(monkeypatch):
    monkeypatch.setattr(resampling, "_OUTPUT_CHUNK", 7)
    audio = np.linspace(-1, 1, 101, dtype=np.float32)
    started = time.perf_counter()
    actual = resampling.resample_audio(audio, 44_100, 16_000)
    elapsed = time.perf_counter() - started

    monkeypatch.setattr(resampling, "_OUTPUT_CHUNK", 8_192)
    expected = resampling.resample_audio(audio, 44_100, 16_000)
    assert elapsed < 1
    assert actual.dtype == np.float32
    np.testing.assert_allclose(actual, expected, atol=1e-6)


def test_polyphase_resampling_preserves_stereo_channels():
    audio = np.column_stack((np.ones(4_800), np.full(4_800, -1))).astype(np.float32)

    output = resampling.resample_audio(audio, 48_000, 16_000)

    assert output.shape == (1_600, 2)
    np.testing.assert_allclose(output[20:-20, 0], 1, atol=1e-5)
    np.testing.assert_allclose(output[20:-20, 1], -1, atol=1e-5)
