"""The start and stop sounds: the list, the choice, a file of one's own, a preview."""

from __future__ import annotations

import logging
import os
import re
import shutil
import wave
from pathlib import Path
from typing import Any, Dict, List

from app import sound_presets
from app.server import safe_paths
from app.server.events import bus
from app.server.rpc import RpcError, method, need

log = logging.getLogger(__name__)

_SLOTS = {"start": ("start_sound", sound_presets.DEFAULT_START),
          "stop": ("stop_sound", sound_presets.DEFAULT_STOP)}
_MAX_BYTES = 4 * 1024 * 1024
_MAX_SECONDS = 8.0


def _slot(params: Dict[str, Any]) -> str:
    slot = need(params, "slot", str)
    if slot not in _SLOTS:
        raise RpcError("bad_params", "slot must be start or stop", field="slot")
    return slot


def _config_dir(rt: Any) -> Path:
    return Path(rt.config.base_dir)


def _current(rt: Any, slot: str) -> str:
    key, default = _SLOTS[slot]
    value = rt.config.get_setting("audio_feedback", key)
    return default if value is None else str(value)


def _accepted(rt: Any, value: Any) -> str:
    if not isinstance(value, str):
        raise RpcError("bad_params", "value must be a path or an empty string", field="value")
    checked = sound_presets.accepted(value, _config_dir(rt))
    if checked is None:
        raise RpcError("bad_params", "That sound is not on the list.", field="value")
    return checked


def _player(rt: Any) -> Any:
    wrapper = getattr(getattr(rt, "state_manager", None), "audio_feedback", None)
    return getattr(wrapper, "_component", wrapper)


def _custom_files(rt: Any) -> List[Dict[str, str]]:
    folder = sound_presets.custom_dir(_config_dir(rt))
    if not folder.is_dir():
        return []
    return [{"value": str(p), "name": p.stem} for p in sorted(folder.glob("*.wav"))]


@method("sounds.list")
def list_sounds(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """``{presets: [{id, label, value}], custom: [{value, name}], start, stop}``."""
    return {
        "presets": [{"id": p.id, "label": p.label, "value": p.value} for p in sound_presets.PRESETS],
        "custom": _custom_files(rt),
        "start": _current(rt, "start"),
        "stop": _current(rt, "stop"),
    }


@method("sounds.set")
def set_sound(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Choose the sound of the start or the stop cue; it applies at once."""
    from app.server.handlers.settings import persist_problem

    slot = _slot(params)
    if "value" not in params:
        raise RpcError("bad_params", "missing parameter: value")
    value = _accepted(rt, params["value"])
    key, _ = _SLOTS[slot]
    rt.config.update_user_setting("audio_feedback", key, value)
    player = _player(rt)
    if player is not None and hasattr(player, "set_sounds"):
        player.set_sounds(**{slot: value})
    bus.emit("settings", {"keys": [f"audio_feedback.{key}"]})
    return {"slot": slot, "value": value, "save_error": persist_problem(rt)}


@method("sounds.preview")
def preview(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Play a sound from the list once, so it can be heard before it is chosen."""
    value = _accepted(rt, params.get("value", ""))
    player = _player(rt)
    seconds = player.preview(value) if player is not None and hasattr(player, "preview") else 0.0
    return {"played": seconds > 0, "seconds": seconds}


@method("sounds.add")
def add(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Copy a WAV file of the person's choosing into the app's own folder.

    Short, plain PCM only: every platform's player takes it, and a cue that
    takes seconds is not a cue.
    """
    path = safe_paths.check_input_path(params.get("path"))
    if not path.lower().endswith(".wav"):
        raise RpcError("bad_params", "Only WAV files can be used as a sound.", field="path")
    if os.path.getsize(path) > _MAX_BYTES:
        raise RpcError("bad_params", "That file is too large for a sound. Keep it under 4 MB.", field="path")
    try:
        with wave.open(path, "rb") as clip:
            seconds = clip.getnframes() / float(clip.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError, OSError):
        raise RpcError("bad_params", "That file is not a WAV sound this app can play.", field="path") from None
    if seconds <= 0 or seconds > _MAX_SECONDS:
        raise RpcError("bad_params", "A sound has to be between a fraction of a second and 8 seconds long.", field="path")
    folder = sound_presets.custom_dir(_config_dir(rt))
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w.\- ]", "_", Path(path).stem).strip(" .")[:60] or "sound"
    target = folder / f"{stem}.wav"
    number = 2
    while target.exists():
        target = folder / f"{stem} {number}.wav"
        number += 1
    shutil.copyfile(path, target)
    return {"value": str(target), "name": target.stem, "seconds": seconds}


@method("sounds.remove")
def remove(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Delete a custom sound. A cue that used it goes back to its default."""
    value = need(params, "value", str)
    if not sound_presets.is_custom(value, _config_dir(rt)):
        raise RpcError("bad_params", "Only your own sounds can be removed.", field="value")
    target = os.path.realpath(value)
    reset = []
    for slot, (key, default) in _SLOTS.items():
        if os.path.realpath(_current(rt, slot)) == target:
            set_sound(rt, {"slot": slot, "value": default})
            reset.append(slot)
    try:
        os.remove(target)
    except OSError as exc:
        raise RpcError("write_failed", safe_paths.os_reason(exc)) from exc
    return {"removed": True, "reset": reset}
