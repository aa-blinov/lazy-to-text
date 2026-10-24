"""Settings: hotkeys with validation, recording mode and the other switches.

The Qt reference is ``ShortcutsView`` for what a value may be and
``AppController._on_shortcuts_save`` / ``_on_hotkeys_reset`` for what a
change has to touch while the app runs. Nothing here waits for a restart.

Deliberate differences from Qt, each of them a bug it had:

* Reset hotkeys reaches the running listener. Qt wrote the defaults to the
  file and the form and left the listener on the old bindings.
* Reset does not drag the VAD switch back to off. Qt rebuilt the form from
  an argument list that had no ``vad_enabled``, so the checkbox fell to its
  default while the stored value stayed on.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional

from app import hotkey_rules, ui_prefs
from app.hotkey_rules import Issue
from app.server.rpc import RpcError, method, need

log = logging.getLogger(__name__)

_MAX_DURATION_CAP_S = 3600
_MIN_HOLD_RANGE_S = (0.0, 2.0)


# ---- reading ---------------------------------------------------------------


def _issue_json(issue: Issue) -> Dict[str, Any]:
    return {
        "message": issue.english(),
        "template": issue.template,
        "args": list(issue.args),
    }


def _defaults() -> Dict[str, str]:
    from app.config_manager import DEFAULT_CONFIG

    hotkey = DEFAULT_CONFIG.get("hotkey", {})
    return {
        "mode": hotkey.get("mode", "two_keys"),
        "start": hotkey.get("start_recording_hotkey", ""),
        "stop": hotkey.get("stop_recording_hotkey", ""),
        "cancel": hotkey.get("cancel_recording_hotkey", ""),
        "push_to_talk_key": hotkey.get("push_to_talk_key", "") or "",
    }


def _resolve_mode(mode: Any, start: str, stop: str) -> str:
    resolved = mode if mode in hotkey_rules.MODES else "two_keys"
    # A config from before the mode field encoded toggle as Start == Stop.
    if resolved == "two_keys" and start and start.strip().lower() == stop.strip().lower():
        return "toggle"
    return resolved


def validate_fields(
    mode: str, start: str, stop: str, cancel: str, ptt: str,
    platform: Optional[str] = None,
) -> Dict[str, Issue]:
    """The refusals for the fields the mode actually uses.

    Keyed ``start`` / ``stop`` / ``cancel`` / ``ptt``. A field the mode does
    not use is not checked: Stop mirrors Start in toggle mode, Start and Stop
    are idle in push-to-talk, and Cancel is persisted empty in both, so an
    error on any of them would be noise about a value nothing reads.
    """
    if mode == "push_to_talk":
        found = hotkey_rules.check_all(
            start=ptt, stop="", cancel="", mode=mode, platform=platform
        )
        return {"ptt": found["start"]} if "start" in found else {}
    if mode == "toggle":
        found = hotkey_rules.check_all(
            start=start, stop=start, cancel="", mode=mode, platform=platform
        )
        return {"start": found["start"]} if "start" in found else {}
    return dict(hotkey_rules.check_all(
        start=start, stop=stop, cancel=cancel, mode="two_keys", platform=platform
    ))


def _read(rt: Any) -> Dict[str, Any]:
    from app.system_audio import system_output_mute_supported
    from app.version import current_version

    cfg = rt.config
    hotkey = cfg.get_section("hotkey")
    audio = cfg.get_section("audio")
    clipboard = cfg.get_section("clipboard")
    feedback = cfg.get_section("audio_feedback")
    ui = cfg.get_section("ui")

    start = str(hotkey.get("start_recording_hotkey") or "")
    stop = str(hotkey.get("stop_recording_hotkey") or "")
    cancel = str(hotkey.get("cancel_recording_hotkey") or "")
    ptt = str(hotkey.get("push_to_talk_key") or "")
    mode = _resolve_mode(hotkey.get("mode"), start, stop)

    # What the file holds may never have passed validation (hand edit,
    # an older build). Say so, so the field is marked at load.
    stored_errors = {
        field: _issue_json(issue)
        for field, issue in validate_fields(mode, start, stop, cancel, ptt).items()
    }

    defaults = _defaults()
    return {
        "platform": sys.platform,
        "version": current_version(),
        "hotkey": {
            "mode": mode,
            "start": start,
            "stop": start if mode == "toggle" else stop,
            "cancel": cancel,
            "push_to_talk_key": ptt,
            "push_to_talk_min_hold_seconds": float(
                hotkey.get("push_to_talk_min_hold_seconds", 0.2) or 0.0
            ),
        },
        "hotkey_errors": stored_errors,
        "defaults": defaults,
        "audio": {
            "device": audio.get("device"),
            "mute_output_on_record": bool(audio.get("mute_output_on_record", False)),
            "vad_enabled": bool(audio.get("vad_enabled", False)),
            "max_duration": int(audio.get("max_duration", 300) or 0),
        },
        "clipboard": {
            "auto_paste": bool(clipboard.get("auto_paste", True)),
            "preserve_clipboard": bool(clipboard.get("preserve_clipboard", False)),
        },
        "audio_feedback": {"enabled": bool(feedback.get("enabled", True))},
        "ui": {
            "theme": ui_prefs.normalise_theme(ui.get("theme")),
            "palette": ui_prefs.normalise_palette(ui.get("palette")),
            "language": ui_prefs.normalise_language(ui.get("language")),
            "text_scale": ui_prefs.clamp_text_scale(ui.get("text_scale", 1.0)),
        },
        "capabilities": {
            "mute_output": system_output_mute_supported(),
            "recording_stack": rt.state_manager is not None,
        },
        "choices": {
            "text_scales": list(ui_prefs.TEXT_SCALE_PRESETS),
            "palettes": list(ui_prefs.PALETTES),
            "languages": [
                {"code": code, "name": ui_prefs.NATIVE_NAMES[code]}
                for code in ui_prefs.SUPPORTED_LANGUAGES
            ],
            "themes": list(ui_prefs.THEMES),
            "modes": list(hotkey_rules.MODES),
            "ptt_solo_keys": sorted(
                hotkey_rules.ptt_solo_keys_for_platform(sys.platform)
            ),
            "max_duration_cap": _MAX_DURATION_CAP_S,
            "min_hold_range": list(_MIN_HOLD_RANGE_S),
        },
    }


@method("settings.get")
def get(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return _read(rt)


# ---- hotkeys ---------------------------------------------------------------


def _mode_param(params: Dict[str, Any]) -> str:
    mode = need(params, "mode", str)
    if mode not in hotkey_rules.MODES:
        raise RpcError("bad_params", f"mode must be one of {', '.join(hotkey_rules.MODES)}")
    return mode


def _text(params: Dict[str, Any], key: str, fallback: str) -> str:
    value = params.get(key, fallback)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise RpcError("bad_params", f"parameter {key} has the wrong type")
    return value.strip()


@method("settings.validate_hotkeys")
def validate_hotkeys(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Check what the form holds without saving it, field by field."""
    mode = _mode_param(params)
    errors = validate_fields(
        mode,
        _text(params, "start", ""),
        _text(params, "stop", ""),
        _text(params, "cancel", ""),
        _text(params, "push_to_talk_key", ""),
    )
    return {"errors": {k: _issue_json(v) for k, v in errors.items()}}


def _fallback(field: str, persisted: Dict[str, str], defaults: Dict[str, str]) -> str:
    """What stays on disk for a field that was just refused.

    The value already stored, if that is itself usable, otherwise the
    shipped default. Never the text that was refused, and never an empty
    string: that would unbind the hotkey, which is the same failure.
    """
    stored = persisted.get(field, "")
    allow_empty = field == "cancel"
    solo = field == "ptt"
    if stored and hotkey_rules.check_hotkey(
        stored, allow_empty=allow_empty, push_to_talk=solo
    ) is None:
        return stored
    return defaults.get(field, "")


def _push_listener(rt: Any, only: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Hand the stored hotkey settings to the running listener.

    A listener that raises must not lose the saved config, so the failure is
    reported to the caller instead of propagating.
    """
    listener = getattr(rt, "hotkey_listener", None)
    if listener is None:
        return {"live": False, "live_error": getattr(rt, "stack_error", None) or "no listener"}
    if only is None:
        hotkey = rt.config.get_section("hotkey")
        only = {
            "mode": hotkey.get("mode", "two_keys"),
            "push_to_talk_key": hotkey.get("push_to_talk_key") or "",
            "start_recording_hotkey": hotkey.get("start_recording_hotkey", ""),
            "stop_recording_hotkey": hotkey.get("stop_recording_hotkey", ""),
            "cancel_combination": (hotkey.get("cancel_recording_hotkey") or "").strip() or None,
            "push_to_talk_min_hold_seconds": float(
                hotkey.get("push_to_talk_min_hold_seconds", 0.2) or 0.0
            ),
        }
    try:
        listener.change_hotkey_configs(only)
    except Exception as exc:
        log.warning("Failed to push hotkey changes live: %s", exc)
        return {"live": False, "live_error": str(exc)}
    return {"live": True, "live_error": None}


@method("settings.set_hotkeys")
def set_hotkeys(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Save the recording mode and its bindings, apply them live.

    Each refused field keeps its previous valid value; the rest still save.
    The result carries the refusals so the form can say why next to the
    field, and ``settings`` with what is stored now.
    """
    cfg = rt.config
    stored = _read(rt)["hotkey"]
    mode = _mode_param(params)
    start = _text(params, "start", stored["start"])
    stop = _text(params, "stop", stored["stop"])
    cancel = _text(params, "cancel", stored["cancel"])
    ptt = _text(params, "push_to_talk_key", stored["push_to_talk_key"])

    errors = validate_fields(mode, start, stop, cancel, ptt)
    defaults = _defaults()
    persisted = {
        "start": stored["start"], "stop": stored["stop"],
        "cancel": stored["cancel"], "ptt": stored["push_to_talk_key"],
    }
    for field, value in (("start", start), ("stop", stop), ("cancel", cancel), ("ptt", ptt)):
        if field in errors:
            value = _fallback(field, persisted, defaults)
        if field == "start":
            start = value
        elif field == "stop":
            stop = value
        elif field == "cancel":
            cancel = value
        else:
            ptt = value

    # What each mode writes: Stop is Start in toggle mode (the listener folds
    # equal bindings into one), Cancel is stored empty outside two-key mode,
    # and a binding the mode does not use is left as it was so switching back
    # finds it.
    updates: Dict[str, Any] = {"mode": mode}
    if mode != "push_to_talk":
        updates["start_recording_hotkey"] = start
        updates["stop_recording_hotkey"] = start if mode == "toggle" else stop
    else:
        updates["push_to_talk_key"] = ptt
    updates["cancel_recording_hotkey"] = cancel if mode == "two_keys" else ""
    for key, value in updates.items():
        cfg.update_user_setting("hotkey", key, value)

    result = _push_listener(rt)
    result["errors"] = {k: _issue_json(v) for k, v in errors.items()}
    result["settings"] = _read(rt)
    return result


@method("settings.reset_hotkeys")
def reset_hotkeys(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Mode and all four bindings back to the shipped defaults, live.

    Auto-paste, the minimum hold and every other setting stay as they are.
    """
    defaults = _defaults()
    cfg = rt.config
    cfg.update_user_setting("hotkey", "mode", defaults["mode"])
    cfg.update_user_setting("hotkey", "start_recording_hotkey", defaults["start"])
    cfg.update_user_setting("hotkey", "stop_recording_hotkey", defaults["stop"])
    cfg.update_user_setting("hotkey", "cancel_recording_hotkey", defaults["cancel"])
    cfg.update_user_setting("hotkey", "push_to_talk_key", defaults["push_to_talk_key"])
    result = _push_listener(rt)
    result["settings"] = _read(rt)
    return result


# ---- single values ---------------------------------------------------------


def _flag(value: Any) -> bool:
    if not isinstance(value, bool):
        raise RpcError("bad_params", "expected true or false")
    return value


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RpcError("bad_params", "expected a number")
    if value != value:
        raise RpcError("bad_params", "expected a number")
    return float(value)


def _apply_auto_paste(rt: Any, value: bool) -> None:
    clipboard = getattr(rt.state_manager, "clipboard_manager", None)
    updater = getattr(clipboard, "update_auto_paste", None)
    if callable(updater):
        updater(value)


def _apply_preserve_clipboard(rt: Any, value: bool) -> None:
    clipboard = getattr(rt.state_manager, "clipboard_manager", None)
    if clipboard is not None:
        clipboard.preserve_clipboard = value


def _apply_mute(rt: Any, value: bool) -> None:
    # State manager reads the stored value at the start of each recording,
    # so persisting it is the whole of applying it.
    return None


def _apply_vad(rt: Any, value: bool) -> None:
    from app.server.handlers import models

    models.push_vad(rt, value)


def _apply_max_duration(rt: Any, value: int) -> None:
    recorder = getattr(rt.state_manager, "audio_recorder", None)
    if recorder is not None:
        recorder.max_duration = value


def _apply_feedback(rt: Any, value: bool) -> None:
    # The state manager holds the sound player behind a null-object wrapper.
    wrapper = getattr(rt.state_manager, "audio_feedback", None)
    player = getattr(wrapper, "_component", wrapper)
    if player is not None and hasattr(player, "enabled"):
        player.enabled = value


def _apply_min_hold(rt: Any, value: float) -> None:
    _push_listener(rt, {"push_to_talk_min_hold_seconds": value})


def _check_mute_supported(value: bool) -> bool:
    from app.system_audio import system_output_mute_supported

    if not system_output_mute_supported():
        raise RpcError("unsupported", "Muting the output is not available on this platform")
    return _flag(value)


def _norm_max_duration(value: Any) -> int:
    seconds = int(_number(value))
    if seconds < 0 or seconds > _MAX_DURATION_CAP_S:
        raise RpcError("bad_params", f"maximum length must be 0..{_MAX_DURATION_CAP_S} seconds")
    return seconds


def _norm_min_hold(value: Any) -> float:
    seconds = _number(value)
    low, high = _MIN_HOLD_RANGE_S
    if seconds < low or seconds > high:
        raise RpcError("bad_params", f"minimum hold must be {low}..{high} seconds")
    return round(seconds, 3)


def _norm_palette(value: Any) -> str:
    if value not in ui_prefs.PALETTES:
        raise RpcError("bad_params", f"palette must be one of {', '.join(ui_prefs.PALETTES)}")
    return value


def _norm_theme(value: Any) -> str:
    if value not in ui_prefs.THEMES:
        raise RpcError("bad_params", f"theme must be one of {', '.join(ui_prefs.THEMES)}")
    return value


def _norm_language(value: Any) -> str:
    if value not in ui_prefs.SUPPORTED_LANGUAGES:
        raise RpcError("bad_params", "language must be en or ru")
    return value


# key -> (section, name, normalise, apply live or None)
_SETTERS = {
    "clipboard.auto_paste": ("clipboard", "auto_paste", _flag, _apply_auto_paste),
    "clipboard.preserve_clipboard": (
        "clipboard", "preserve_clipboard", _flag, _apply_preserve_clipboard,
    ),
    "audio.mute_output_on_record": (
        "audio", "mute_output_on_record", _check_mute_supported, _apply_mute,
    ),
    "audio.vad_enabled": ("audio", "vad_enabled", _flag, _apply_vad),
    "audio.max_duration": ("audio", "max_duration", _norm_max_duration, _apply_max_duration),
    "audio_feedback.enabled": ("audio_feedback", "enabled", _flag, _apply_feedback),
    "hotkey.push_to_talk_min_hold_seconds": (
        "hotkey", "push_to_talk_min_hold_seconds", _norm_min_hold, _apply_min_hold,
    ),
    "ui.theme": ("ui", "theme", _norm_theme, None),
    "ui.palette": ("ui", "palette", _norm_palette, None),
    "ui.language": ("ui", "language", _norm_language, None),
    "ui.text_scale": ("ui", "text_scale", lambda v: ui_prefs.clamp_text_scale(_number(v)), None),
}


@method("settings.set")
def set_value(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Persist one setting and apply it to the running app.

    ``key`` is ``section.name`` from the whitelist; the stored (normalised)
    value is returned. Hotkeys and the device have their own methods because
    they are validated together.
    """
    key = need(params, "key", str)
    entry = _SETTERS.get(key)
    if entry is None:
        raise RpcError("bad_params", f"unknown setting: {key}")
    if "value" not in params:
        raise RpcError("bad_params", "missing parameter: value")
    section, name, normalise, apply = entry
    value = normalise(params["value"])
    rt.config.update_user_setting(section, name, value)
    live_error = None
    if apply is not None:
        try:
            apply(rt, value)
        except Exception as exc:
            # The value is saved; only the live half failed.
            log.warning("Could not apply %s live: %s", key, exc)
            live_error = str(exc)
    return {"key": key, "value": value, "live_error": live_error}
