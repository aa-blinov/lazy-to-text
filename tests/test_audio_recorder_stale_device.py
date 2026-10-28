"""A microphone that is gone must not take the recording stack with it.

QA-RUNTIME-5 / QA-JOURNEYS-2: ``audio.device: 99`` (an unplugged USB or
Bluetooth microphone) made the recorder's constructor raise, so there was
no stack, no hotkeys and no way out; a start that failed on the recording
thread had already answered "started".
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import pytest

from app import audio_recorder
from app.audio_recorder import AudioRecorder


class _Sd:
    """Two inputs, device 99 does not exist."""

    devices = [
        {"name": "Built-in", "max_input_channels": 1, "default_samplerate": 16000.0},
        {"name": "Speakers", "max_input_channels": 0, "default_samplerate": 44100.0},
    ]
    fail_open = None
    opened: list = []

    @classmethod
    def query_devices(cls, device=None, kind=None):
        if kind == "input":
            return cls.devices[0]
        if device is None:
            return cls.devices
        if not isinstance(device, int) or not 0 <= device < len(cls.devices):
            raise ValueError(f"Error querying device {device}")
        return cls.devices[device]

    class InputStream:
        def __init__(self, **kw):
            if _Sd.fail_open:
                raise OSError(_Sd.fail_open)
            self.kw = kw
            _Sd.opened.append(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    @staticmethod
    def sleep(ms):
        import time

        time.sleep(ms / 1000)

    @staticmethod
    def query_hostapis():
        return []


@pytest.fixture(autouse=True)
def fake_sd(monkeypatch):
    _Sd.fail_open = None
    _Sd.opened = []
    monkeypatch.setattr(audio_recorder, "sd", _Sd)
    monkeypatch.setattr(AudioRecorder, "RECORDING_SLEEP_INTERVAL", 10)
    return _Sd


def test_a_saved_device_that_no_longer_exists_falls_back_to_the_default(caplog):
    with caplog.at_level(logging.WARNING):
        rec = AudioRecorder(device=99)

    assert rec.device is None
    assert rec.last_error is None
    assert any(
        getattr(r, "user_message", False) and "system default" in r.getMessage()
        for r in caplog.records
    )


def test_recording_works_after_the_fallback(fake_sd):
    rec = AudioRecorder(device=99)

    assert rec.start_recording() is True
    assert fake_sd.opened and fake_sd.opened[0]["device"] is None
    rec.is_recording = False
    rec.recording_thread.join(timeout=2)


def test_a_device_that_vanishes_after_start_up_is_replaced_at_the_next_start(fake_sd):
    rec = AudioRecorder(device=0)
    rec.device = 7  # unplugged since the stack was built
    rec.device_name = None  # and no name to find it by

    assert rec.start_recording() is True
    assert fake_sd.opened[0]["device"] is None
    rec.is_recording = False
    rec.recording_thread.join(timeout=2)


def test_a_stream_that_cannot_open_makes_start_recording_return_false(fake_sd, caplog):
    rec = AudioRecorder()
    fake_sd.fail_open = "Invalid sample rate"

    with caplog.at_level(logging.ERROR):
        assert rec.start_recording() is False

    assert rec.is_recording is False
    assert "Invalid sample rate" in rec.last_error
    assert any(getattr(r, "user_message", False) for r in caplog.records)


def test_a_missing_default_input_does_not_stop_the_constructor(monkeypatch):
    def nothing(*a, **k):
        raise OSError("no devices")

    monkeypatch.setattr(_Sd, "query_devices", staticmethod(nothing))

    rec = AudioRecorder()

    assert "No microphone" in rec.last_error


def test_set_device_refuses_an_index_that_is_not_an_input():
    rec = AudioRecorder()

    with pytest.raises(ValueError):
        rec.set_device(99)
    with pytest.raises(ValueError):
        rec.set_device(1)  # an output
    assert rec.set_device(0) == 0
    assert rec.set_device(None) is None


def test_a_stream_that_breaks_after_start_is_reported(fake_sd):
    reported: list = []
    rec = AudioRecorder()
    rec.on_recording_failed = reported.append

    class _Slow(_Sd.InputStream):
        def __init__(self, **kw):
            super().__init__(**kw)
            self._first = True

        def __enter__(self):
            return self

    # Open succeeds, then the record loop's sleep raises (device unplugged).
    calls = {"n": 0}

    def boom(ms):
        calls["n"] += 1
        if rec._start_returned and calls["n"] > 2:
            raise OSError("device unplugged")

    fake_sd.InputStream = _Slow
    fake_sd.sleep = staticmethod(boom)
    try:
        assert rec.start_recording() is True
        rec.recording_thread.join(timeout=3)
    finally:
        fake_sd.InputStream = _Sd.InputStream
    assert reported and "unplugged" in reported[0]


def test_audio_captured_before_the_stream_broke_is_still_transcribed(fake_sd):
    handed: list = []
    rec = AudioRecorder(on_max_duration_reached=handed.append)
    rec._start_returned = True
    rec.audio_data = [np.full(1600, 0.2, dtype=np.float32)]
    rec._capture_sample_rate = 16000
    rec.last_error = "device unplugged"

    rec._report_stream_failure()

    assert len(handed) == 1 and len(handed[0]) == 1600
