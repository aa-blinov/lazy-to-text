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
        phase=lambda: "",
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

    assert {"version", "platform", "state", "phase", "engine", "first_run", "config",
            "hotkey_defaults", "stack_error"} <= set(snap)
    assert snap["first_run"] is False  # a model on disk wins over the flag
    assert set(snap["config"]) >= {"whisper", "hotkey", "llm", "ui", "onboarding"}
    assert "window" not in snap["config"]


def test_quit_sets_the_event_the_main_loop_waits_on():
    rt = _rt()

    assert core.quit_app(rt, {}) == {"quitting": True}
    assert rt.quit_event.is_set()


def test_logs_list_returns_the_ring():
    assert core.logs_list(_rt(), {})["records"][0]["message"] == "hello"


# ---- credentials never leave the runtime (QA-SEC-6) --------------------------


def test_the_snapshot_carries_flags_instead_of_credentials():
    secret = "sk-PLANTED-SECRET-AAA"
    sections = {
        "llm": {"api_key": secret, "enabled": True,
                "profiles": [{"id": "a", "api_key": secret, "model": "m"},
                             {"id": "b", "api_key": "", "model": "n"}]},
        "huggingface": {"token": "hf_PLANTED"},
    }
    rt = _rt(config=SimpleNamespace(
        get_section=lambda s: sections.get(s, {}), get_setting=lambda s, k: None))

    llm = core.snapshot(rt, {})["config"]["llm"]

    assert "api_key" not in llm and llm["api_key_set"] is True
    assert [("api_key" in p, p["api_key_set"]) for p in llm["profiles"]] == [
        (False, True), (False, False)]
    assert secret not in repr(core.snapshot(rt, {}))


def test_the_last_outcome_events_can_be_asked_for():
    from app.server.events import bus

    bus.emit("delivery", {"outcome": "copied", "detail": "d", "text": "t"})
    bus.emit("model_load", {"alias": "x", "outcome": "ready"})

    events = core.last_events(_rt(), {})["events"]

    assert events["delivery"]["data"]["outcome"] == "copied"
    assert events["model_load"]["data"] == {"alias": "x", "outcome": "ready"}
    assert events["delivery"]["at"] > 0


def test_a_ticket_is_issued_for_the_event_stream():
    from app.server import tickets

    out = core.events_ticket(_rt(), {})

    assert tickets.redeem(out["ticket"]) is True
    assert out["ttl_s"] == tickets.TTL_S


# ---- no model: say which situation it is (QA-RUNTIME-22, QA-JOURNEYS-6) -------------


class _NoModelBackend:
    def health_check(self):
        return False


@pytest.mark.parametrize("state, on_disk, expect", [
    ("model_loading", True, "still loading"),
    ("idle", False, "No speech model is installed"),
    ("idle", True, "No model is loaded"),
])
def test_starting_without_a_model_is_refused_with_the_reason(state, on_disk, expect):
    manager = _State()
    manager.backend = _NoModelBackend()
    rt = _rt(state_manager=manager, state=lambda: state, has_model_on_disk=on_disk)

    if state == "model_loading":
        # a load in progress is not idle: the toggle goes to the state manager
        core.toggle(rt, {})
        assert manager.calls == ["toggle"]
        assert expect in core.not_ready_message(rt)
        return
    with pytest.raises(rpc.RpcError) as err:
        core.toggle(rt, {})

    assert err.value.code == "not_ready" and expect in err.value.message
    assert manager.calls == []


def test_a_file_run_without_a_model_says_the_same_thing():
    from app.server.handlers import files

    rt = _rt(has_model_on_disk=False)
    rt.state_manager.backend = _NoModelBackend()

    with pytest.raises(rpc.RpcError) as err:
        files._ready_backend(rt)

    assert err.value.code == "not_ready" and "No speech model is installed" in err.value.message


def test_toggle_still_stops_a_recording_when_the_model_is_gone():
    manager = _State()
    manager.backend = _NoModelBackend()
    rt = _rt(state_manager=manager, state=lambda: "recording")

    core.toggle(rt, {})

    assert manager.calls == ["toggle"]
