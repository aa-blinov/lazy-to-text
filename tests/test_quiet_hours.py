"""Quiet hours: a daily window in which the sound cues stay silent."""

from __future__ import annotations

import wave
from datetime import datetime

import pytest

from app import audio_feedback as af


@pytest.mark.parametrize("text, minutes", [("00:00", 0), ("07:05", 425), ("23:59", 1439)])
def test_a_clock_time_parses(text, minutes):
    assert af.parse_clock(text) == minutes


@pytest.mark.parametrize("text", ["", "7:05", "24:00", "12:60", "ab:cd", "12-30", None, 830])
def test_anything_else_is_not_a_clock_time(text):
    assert af.parse_clock(text) is None


@pytest.mark.parametrize("now, expected", [
    ("21:59", False), ("22:00", True), ("23:59", True), ("00:00", True),
    ("07:59", True), ("08:00", False), ("12:00", False),
])
def test_a_window_may_run_past_midnight(now, expected):
    assert af.in_quiet_hours(af.parse_clock(now), "22:00", "08:00") is expected


def test_a_window_inside_one_day():
    assert af.in_quiet_hours(af.parse_clock("13:00"), "12:00", "14:00") is True
    assert af.in_quiet_hours(af.parse_clock("14:00"), "12:00", "14:00") is False


def test_equal_times_or_bad_times_make_no_window():
    assert af.in_quiet_hours(0, "09:00", "09:00") is False
    assert af.in_quiet_hours(0, "nonsense", "08:00") is False


def _player(hour, minute=0, **kw):
    kw.setdefault("quiet_hours", True)
    return af.AudioFeedback(enabled=True, clock=lambda: datetime(2026, 11, 2, hour, minute), **kw)


def test_cues_are_silent_inside_the_window_and_back_after_it(monkeypatch):
    played = []
    monkeypatch.setattr(af.AudioFeedback, "_play_sound_file_async", lambda self, path: played.append(path))

    night = _player(23, start_sound="a.wav", stop_sound="b.wav", cancel_sound="c.wav")
    night.play_start_sound()
    night.play_stop_sound()
    night.play_cancel_sound()
    assert played == [] and night.start_sound_seconds() == 0.0

    day = _player(12, start_sound="a.wav", stop_sound="b.wav", cancel_sound="c.wav")
    day.play_start_sound()
    assert len(played) == 1


def test_quiet_hours_do_not_change_the_switch_the_person_set():
    night = _player(23)
    assert night.enabled is True and night.sounding() is False


def test_quiet_hours_off_means_no_window():
    assert _player(23, quiet_hours=False).sounding() is True


def test_a_preview_is_heard_in_quiet_hours(monkeypatch, tmp_path):
    played = []
    monkeypatch.setattr(af.AudioFeedback, "_play_sound_file_async", lambda self, path: played.append(path))
    wav = tmp_path / "x.wav"
    with wave.open(str(wav), "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(8000)
        clip.writeframes(b"\0\0" * 80)

    _player(23).preview(str(wav))

    assert played
