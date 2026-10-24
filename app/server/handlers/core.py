"""The application shell: snapshot, recording controls, resources, quit."""

from __future__ import annotations

import sys
from typing import Any, Dict

from app.server.rpc import RpcError, method


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
        "first_run": bootstrap._should_show_first_run(rt.config, rt.has_model_on_disk),
        "hotkey_defaults": {
            "start": default_start_hotkey(),
            "stop": default_stop_hotkey(),
            "cancel": default_cancel_hotkey(),
        },
        "config": {
            section: rt.config.get_section(section)
            for section in (
                "whisper", "hotkey", "audio", "clipboard", "audio_feedback",
                "history", "storage", "llm", "ui", "onboarding", "window",
            )
        },
        "log_path": rt.log_path,
    }


def _need_stack(rt: Any) -> Any:
    if rt.state_manager is None:
        raise RpcError("no_stack", rt.stack_error or "the recording stack is not running")
    return rt.state_manager


@method("recording.toggle")
def toggle(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    _need_stack(rt).toggle_recording()
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


@method("app.quit")
def quit_app(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    event = getattr(rt, "quit_event", None)
    if event is not None:
        event.set()
    return {"quitting": True}
