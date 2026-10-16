"""A recording thread that will not finish must not keep the microphone.

The stop path waits for the recording thread, and the thread owns the input
stream. When the thread outlives that wait, the stream stays open, the device
stays busy, and the next recording gets no audio. The fake stream below holds
the "device" while it is open and blocks on exit until it is aborted, which is
the shape of the failure in the field.
"""
from __future__ import annotations

import threading

import numpy as np
import pytest


class _FakeInputStream:
    instances: list = []
    holders: list = []
    opened = threading.Event()
    stuck_on_exit = True
    releases_on_abort = True
    feeds_audio = True

    def __init__(self, samplerate=None, channels=1, callback=None, dtype=None, device=None):
        self.callback = callback
        self.aborted = False
        self.released = threading.Event()
        _FakeInputStream.instances.append(self)

    def __enter__(self):
        # A device that another stream still holds delivers nothing, the
        # same way the microphone behaved after the stuck stop.
        busy = bool(_FakeInputStream.holders)
        _FakeInputStream.holders.append(self)
        if _FakeInputStream.feeds_audio and not busy:
            self.callback(np.full((160, 1), 0.2, dtype=np.float32), 160, None, None)
        _FakeInputStream.opened.set()
        return self

    def __exit__(self, *exc):
        if _FakeInputStream.stuck_on_exit:
            self.released.wait()
        _FakeInputStream.holders.remove(self)
        return False

    def abort(self, ignore_errors=True):
        self.aborted = True
        if _FakeInputStream.releases_on_abort:
            self.released.set()


@pytest.fixture
def recorder(monkeypatch):
    from app import audio_recorder

    monkeypatch.setattr(audio_recorder.AudioRecorder, "_test_microphone", lambda self: None)
    monkeypatch.setattr(audio_recorder.AudioRecorder, "THREAD_JOIN_TIMEOUT", 0.5)
    monkeypatch.setattr(audio_recorder.AudioRecorder, "ABORT_TIMEOUT", 0.5)
    monkeypatch.setattr(audio_recorder.AudioRecorder, "RECORDING_SLEEP_INTERVAL", 10)
    monkeypatch.setattr(audio_recorder.sd, "InputStream", _FakeInputStream)

    _FakeInputStream.instances = []
    _FakeInputStream.holders = []
    _FakeInputStream.opened = threading.Event()
    _FakeInputStream.stuck_on_exit = True
    _FakeInputStream.releases_on_abort = True
    _FakeInputStream.feeds_audio = True

    rec = audio_recorder.AudioRecorder()
    yield rec

    for stream in _FakeInputStream.instances:
        stream.released.set()
    if rec.recording_thread is not None:
        rec.recording_thread.join(timeout=2)


def _start_and_wait_for_stream(rec):
    assert rec.start_recording() is True
    assert _FakeInputStream.opened.wait(timeout=2)


def test_stop_aborts_a_recording_thread_that_will_not_finish(recorder, caplog):
    _start_and_wait_for_stream(recorder)

    audio = recorder.stop_recording()

    assert _FakeInputStream.instances[-1].aborted
    assert not recorder.recording_thread.is_alive()
    assert audio is not None and len(audio) > 0
    assert "still alive after stopping" in caplog.text


def test_next_recording_is_refused_while_the_last_stream_still_holds_the_microphone(recorder, caplog):
    _FakeInputStream.releases_on_abort = False
    _start_and_wait_for_stream(recorder)
    recorder.stop_recording()

    assert recorder.start_recording() is False
    assert len(_FakeInputStream.instances) == 1
    assert recorder.is_recording is False
    assert "Restart the app" in caplog.text


def test_recording_works_again_once_the_stuck_stream_is_aborted(recorder):
    _start_and_wait_for_stream(recorder)
    recorder.stop_recording()

    _FakeInputStream.stuck_on_exit = False
    _FakeInputStream.opened = threading.Event()
    assert recorder.start_recording() is True
    assert _FakeInputStream.opened.wait(timeout=2)
    audio = recorder.stop_recording()

    assert audio is not None and len(audio) > 0
    assert len(_FakeInputStream.instances) == 2


def test_a_normal_stop_neither_warns_nor_aborts(recorder, caplog):
    _FakeInputStream.stuck_on_exit = False
    _start_and_wait_for_stream(recorder)

    audio = recorder.stop_recording()

    assert audio is not None
    assert not _FakeInputStream.instances[-1].aborted
    assert "still alive after stopping" not in caplog.text


def test_no_callbacks_are_reported_as_no_audio_from_the_microphone(recorder, caplog):
    _FakeInputStream.feeds_audio = False
    _FakeInputStream.stuck_on_exit = False
    _start_and_wait_for_stream(recorder)

    audio = recorder.stop_recording()

    assert audio is None
    assert "No audio from the microphone" in caplog.text
