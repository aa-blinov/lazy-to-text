"""A completed dictation must release callback-sized audio chunks at once."""

import logging
import threading

import numpy as np


def test_processing_detaches_chunks_from_the_idle_recorder():
    from app.audio_recorder import AudioRecorder

    recorder = AudioRecorder.__new__(AudioRecorder)
    recorder._audio_data_lock = threading.Lock()
    recorder.audio_data = [
        np.full(8000, 0.2, dtype=np.float32),
        np.full(8000, 0.3, dtype=np.float32),
    ]
    recorder._capture_sample_rate = 16_000
    recorder.sample_rate = 16_000
    recorder.logger = logging.getLogger("test.audio_buffer_lifetime")

    audio = recorder._process_audio_data()

    assert audio is not None
    assert len(audio) == 16_000
    assert recorder.audio_data == []
    assert np.isclose(audio[0], 0.2)
    assert np.isclose(audio[-1], 0.3)
