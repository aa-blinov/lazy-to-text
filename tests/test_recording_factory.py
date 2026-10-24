"""The recording stack factory: config in, wired domain objects out.

It is glue between ``ConfigManager`` and the domain constructors, and the
runtime cannot start without it. Every constructor is replaced by a recorder
so the test opens no microphone and registers no global hotkey.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.recording_factory as factory


class _Config:
    config_path = None

    def get_whisper_config(self):
        return {"model": "gigaam-v3-ctc", "device": "cpu", "beam_size": 3}

    def get_audio_config(self):
        return {"channels": 1, "dtype": "float32", "max_duration": 42, "device": None}

    def get_clipboard_config(self):
        return {"auto_paste": False}

    def get_audio_feedback_config(self):
        return {"enabled": False}

    def get_hotkey_config(self):
        return {"start_recording_hotkey": "ctrl+f8", "stop_recording_hotkey": "ctrl+f9",
                "cancel_recording_hotkey": "  ", "mode": "two_keys",
                "push_to_talk_key": ""}


def _recorder(name):
    class _Recorded:
        instances = []

        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs
            type(self).instances.append(self)

        def recover_if_left_muted(self):
            return None

        def current_model(self):
            return self.kwargs.get("model", "stub")

        def handle_max_recording_duration_reached(self):
            return None

    _Recorded.__name__ = name
    return _Recorded


@pytest.fixture
def stubbed(monkeypatch):
    classes = {}
    for name in ("AudioFeedback", "AudioRecorder", "ClipboardManager", "SystemOutputMute",
                 "StateManager", "HotkeyListener", "SubprocessBackend"):
        classes[name] = _recorder(name)
        monkeypatch.setattr(factory, name, classes[name])
    return classes


def test_the_stack_is_wired_from_the_config(stubbed):
    state, hotkeys, backend = factory.build_recording_stack(_Config())

    assert backend is stubbed["SubprocessBackend"].instances[0]
    assert backend.kwargs["model"] == "gigaam-v3-ctc"
    assert backend.kwargs["beam_size"] == 3
    assert state.kwargs["backend"] is backend
    assert hotkeys.kwargs["state_manager"] is state
    recorder = stubbed["AudioRecorder"].instances[0]
    assert recorder.kwargs["max_duration"] == 42
    assert recorder.on_max_duration_reached == state.handle_max_recording_duration_reached


def test_a_blank_cancel_hotkey_means_none(stubbed):
    _state, hotkeys, _backend = factory.build_recording_stack(_Config())

    assert hotkeys.kwargs["cancel_combination"] is None
    assert hotkeys.kwargs["push_to_talk_key"] is None


def test_a_backend_spawned_early_is_reused(stubbed):
    early = stubbed["SubprocessBackend"]()
    stubbed["SubprocessBackend"].instances.clear()

    _state, _hotkeys, backend = factory.build_recording_stack(_Config(), backend=early)

    assert backend is early
    assert stubbed["SubprocessBackend"].instances == []


def test_the_mute_marker_lives_next_to_the_config(stubbed, tmp_path):
    config = _Config()
    config.config_path = tmp_path / "config.yaml"

    factory.build_recording_stack(config)

    marker = stubbed["SystemOutputMute"].instances[0].kwargs["state_path"]
    assert Path(marker).parent == tmp_path


def test_a_failed_mute_recovery_does_not_stop_the_stack(stubbed, monkeypatch):
    def _boom(self):
        raise RuntimeError("coreaudio said no")

    monkeypatch.setattr(stubbed["SystemOutputMute"], "recover_if_left_muted", _boom)

    state, _hotkeys, _backend = factory.build_recording_stack(_Config())

    assert state is stubbed["StateManager"].instances[0]
