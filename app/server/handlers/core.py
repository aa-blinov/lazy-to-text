"""The application shell: snapshot, recording controls, resources, quit."""

from __future__ import annotations

import sys
from typing import Any, Dict

from app.server import redact, tickets
from app.server.events import bus
from app.server.rpc import RpcError, method

#: Outcomes that arrive on events the renderer may not be listening to at
#: that moment (a reload, a reconnect after sleep). ``app.last_events``
#: answers with the last payload of each, so none of them is lost for good.
bus.keep_last("delivery", "model_load", "model_delete", "llm_test")


@method("app.ping")
def ping(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return {"pong": True}


@method("app.snapshot")
def snapshot(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Everything a window needs to draw its first frame.

    Later changes arrive as events; this is the baseline they apply to.
    """
    from app import bootstrap
    from app.config_manager import (
        default_cancel_hotkey,
        default_start_hotkey,
        default_stop_hotkey,
    )
    from app.version import current_version

    return {
        "version": current_version(),
        "platform": sys.platform,
        "state": rt.state(),
        "engine": rt.engine(),
        "stack_error": rt.stack_error,
        "first_run": bootstrap._should_show_first_run(rt.config, rt.has_model_on_disk)
        and not getattr(rt, "first_run_deferred", False),
        "hotkey_defaults": {
            "start": default_start_hotkey(),
            "stop": default_stop_hotkey(),
            "cancel": default_cancel_hotkey(),
        },
        "config": {
            section: redact.public(rt.config.get_section(section))
            for section in (
                "whisper", "hotkey", "audio", "clipboard", "audio_feedback",
                "history", "storage", "llm", "ui", "onboarding",
            )
        },
        "log_path": rt.log_path,
    }


def _need_stack(rt: Any) -> Any:
    if rt.state_manager is None:
        raise RpcError("no_stack", rt.stack_error or "the recording stack is not running")
    return rt.state_manager


def not_ready_message(rt: Any) -> str:
    """What to tell a person when there is no model to run: which of the
    three situations they are in, not a "wait" that nothing will end."""
    try:
        loading = rt.state() == "model_loading"
    except Exception:  # pragma: no cover - defensive
        loading = False
    if loading:
        return "A model is still loading. Wait for it to finish."
    if not getattr(rt, "has_model_on_disk", True):
        return "No speech model is installed yet. Open Models and download one."
    return "No model is loaded. Open Models and choose one."


@method("recording.toggle")
def toggle(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Start a recording when idle and ready, stop it when recording.

    With no model ready, starting is refused with ``not_ready`` and the
    sentence for the situation. It used to answer ``{state: "idle"}`` and
    leave the reason in a log line.
    """
    manager = _need_stack(rt)
    if rt.state() == "idle":
        backend = getattr(manager, "backend", None)
        health = getattr(backend, "health_check", None)
        if callable(health) and not health():
            raise RpcError("not_ready", not_ready_message(rt))
    manager.toggle_recording()
    return {"state": rt.state()}


@method("recording.stop")
def stop(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    stopped = _need_stack(rt).stop_recording(use_auto_enter=False)
    return {"stopped": bool(stopped), "state": rt.state()}


@method("recording.cancel")
def cancel(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    cancelled = _need_stack(rt).cancel_recording_hotkey_pressed()
    return {"cancelled": bool(cancelled), "state": rt.state()}


@method("resources.sample")
def resources(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return rt.sampler.sample() if rt.sampler is not None else {}


@method("logs.list")
def logs_list(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return {"records": list(rt.log_ring)}


@method("app.last_events")
def last_events(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """The last payload of each outcome event, with the time it was sent.

    ``{events: {name: {at, data}}}`` for ``delivery``, ``model_load``,
    ``model_delete`` and ``llm_test``; a name that has not happened since the
    runtime started is absent. File results have their own methods.
    """
    return {"events": bus.last()}


@method("app.events_ticket")
def events_ticket(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """A one-time ticket for ``GET /events?ticket=...``.

    ``EventSource`` cannot send a header, so the stream used to carry the
    launch token in its URL. A ticket is valid for ``ttl_s`` seconds and for
    one stream, which is all a URL should hold. An automatic reconnect needs
    a new one.
    """
    return {"ticket": tickets.issue(), "ttl_s": tickets.TTL_S}


@method("app.quit")
def quit_app(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    event = getattr(rt, "quit_event", None)
    if event is not None:
        event.set()
    return {"quitting": True}
