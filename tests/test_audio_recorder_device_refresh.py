"""A phone or headset that comes and goes must not leave the recorder on a stale list.

PortAudio freezes its device list when it starts. A microphone connected later is
not in it; one disconnected still is; every index after the change is shifted. The
symptom is "Error opening InputStream: Internal PortAudio error [PaErrorCode -9986]".
The recorder keeps the microphone's *name*, rebuilds the list when an open fails,
and looks the name up again.
"""

from __future__ import annotations

import logging

import pytest

from app import audio_recorder
from app.audio_recorder import AudioRecorder


def _mic(name, rate=16000.0):
    return {"name": name, "max_input_channels": 1, "default_samplerate": rate, "hostapi": 0}


class _Sd:
    #: What PortAudio saw when it started.
    stale = [_mic("Built-in"), _mic("iPhone Microphone")]
    #: What it sees after it is rebuilt.
    fresh = [_mic("Built-in")]
    devices = list(stale)
    terminated = 0
    opened: list = []
    open_error = None

    @classmethod
    def reset(cls):
        cls.devices = list(cls.stale)
        cls.terminated = 0
        cls.opened = []
        cls.open_error = None

    @classmethod
    def query_devices(cls, device=None, kind=None):
        if kind == "input":
            return cls.devices[0]
        if device is None:
            return cls.devices
        if not isinstance(device, int) or not 0 <= device < len(cls.devices):
            raise ValueError(f"Error querying device {device}")
        return cls.devices[device]

    @classmethod
    def _terminate(cls):
        cls.terminated += 1

    @classmethod
    def _initialize(cls):
        cls.devices = list(cls.fresh)

    class InputStream:
        def __init__(self, **kw):
            device = kw["device"]
            gone = device is not None and not (0 <= device < len(_Sd.devices))
            stale_handle = device is not None and _Sd.devices is not None and _Sd.open_error == "stale" and device == 1
            if gone or stale_handle:
                raise OSError("Error opening InputStream: Internal PortAudio error [PaErrorCode -9986]")
            if _Sd.open_error and _Sd.open_error != "stale":
                raise OSError(_Sd.open_error)
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
    _Sd.reset()
    _Sd.fresh = [_mic("Built-in")]
    monkeypatch.setattr(audio_recorder, "sd", _Sd)
    monkeypatch.setattr(AudioRecorder, "RECORDING_SLEEP_INTERVAL", 10)
    return _Sd


def _stop(rec):
    rec.is_recording = False
    if rec.recording_thread is not None:
        rec.recording_thread.join(timeout=2)


def test_the_chosen_microphone_is_remembered_by_name():
    rec = AudioRecorder(device=1)

    assert rec.device_name == "iPhone Microphone"


def test_a_saved_name_wins_over_an_index_that_has_shifted(fake_sd):
    fake_sd.devices = [_mic("Built-in"), _mic("Speakerphone"), _mic("USB mic")]

    rec = AudioRecorder(device=1, device_name="USB mic")

    assert rec.device == 2


def test_the_list_is_searched_again_by_name_after_it_changes(fake_sd):
    rec = AudioRecorder(device=1)
    fake_sd.devices = [_mic("Built-in"), _mic("Headset"), _mic("iPhone Microphone")]

    rec.rebind_device()

    assert rec.device == 2


def test_a_microphone_that_is_gone_means_the_default_until_it_returns(fake_sd, caplog):
    rec = AudioRecorder(device=1)
    fake_sd.devices = [_mic("Built-in")]

    with caplog.at_level(logging.WARNING):
        rec.rebind_device()

    assert rec.device is None
    assert rec.device_name == "iPhone Microphone", "the choice is kept for when it comes back"
    assert any(getattr(r, "user_message", False) and "not connected" in r.getMessage() for r in caplog.records)

    fake_sd.devices = [_mic("Built-in"), _mic("iPhone Microphone")]
    rec.rebind_device()
    assert rec.device == 1


def test_an_open_that_fails_on_a_stale_list_is_retried_on_a_rebuilt_one(fake_sd):
    rec = AudioRecorder(device=1)
    fake_sd.open_error = "stale"   # the old handle for index 1 is dead
    fake_sd.fresh = [_mic("Built-in"), _mic("Headset"), _mic("iPhone Microphone")]

    assert rec.start_recording() is True

    assert fake_sd.terminated == 1, "the audio system was restarted once"
    assert fake_sd.opened and fake_sd.opened[0]["device"] == 2
    _stop(rec)


def test_a_microphone_that_is_gone_is_opened_by_default_after_the_rebuild(fake_sd):
    rec = AudioRecorder(device=1)
    fake_sd.open_error = "stale"

    assert rec.start_recording() is True

    assert fake_sd.opened[0]["device"] is None
    _stop(rec)


def test_an_open_that_still_fails_reports_the_first_error(fake_sd):
    rec = AudioRecorder()
    fake_sd.open_error = "Invalid sample rate"

    assert rec.start_recording() is False

    assert "Invalid sample rate" in rec.last_error
    assert fake_sd.terminated == 1, "one rebuild, not a loop"


def test_the_list_is_not_rebuilt_under_an_open_stream(fake_sd):
    rec = AudioRecorder()
    rec.is_recording = True

    assert rec.refresh_devices() is False
    assert fake_sd.terminated == 0

    rec.is_recording = False
    rec._testing = True
    assert rec.refresh_devices() is False
    assert fake_sd.terminated == 0


def test_a_rebuild_drops_a_disconnected_microphone_from_the_list(fake_sd):
    rec = AudioRecorder(device=1)

    assert rec.refresh_devices() is True

    assert [name for _, name in rec.list_input_devices()] == ["Built-in"]
    assert rec.device is None
