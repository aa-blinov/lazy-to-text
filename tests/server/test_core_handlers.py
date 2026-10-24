"""The shell's own methods, against a runtime built from stand-ins."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from app.server import rpc
from app.server.handlers import core


class _State:
    def __init__(self):
        self.calls = []
        self.recording = False

    def toggle_recording(self):
        self.calls.append("toggle")

    def stop_recording(self, use_auto_enter=False):
        self.calls.append("stop")
        return True

    def cancel_recording_hotkey_pressed(self):
        self.calls.append("cancel")
        return False


def _rt(**over):
    base = dict(
        state=lambda: "idle",
        engine=lambda: {"provider": None, "model": "", "alias": ""},
        state_manager=_State(),
        stack_error=None,
        log_ring=[{"id": 1, "message": "hello"}],
        sampler=None,
        quit_event=threading.Event(),
        has_model_on_disk=True,
        log_path="",
        config=SimpleNamespace(
            get_section=lambda s: {"section": s},
            get_setting=lambda s, k: None,
        ),
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_the_recording_controls_reach_the_state_manager():
    rt = _rt()

    core.toggle(rt, {})
    core.stop(rt, {})
    result = core.cancel(rt, {})

    assert rt.state_manager.calls == ["toggle", "stop", "cancel"]
    assert result == {"cancelled": False, "state": "idle"}


def test_without_a_stack_the_controls_say_why():
    rt = _rt(state_manager=None, stack_error="no audio device")

    with pytest.raises(rpc.RpcError) as err:
        core.toggle(rt, {})

    assert err.value.code == "no_stack"
    assert "no audio device" in err.value.message


def test_the_snapshot_carries_everything_a_first_frame_needs():
    snap = core.snapshot(_rt(), {})

    assert {"version", "platform", "state", "engine", "first_run", "config",
            "hotkey_defaults", "stack_error"} <= set(snap)
    assert snap["first_run"] is False  # a model on disk wins over the flag
    assert set(snap["config"]) >= {"whisper", "hotkey", "llm", "ui", "onboarding"}


def test_quit_sets_the_event_the_main_loop_waits_on():
    rt = _rt()

    assert core.quit_app(rt, {}) == {"quitting": True}
    assert rt.quit_event.is_set()


def test_logs_list_returns_the_ring():
    assert core.logs_list(_rt(), {})["records"][0]["message"] == "hello"
