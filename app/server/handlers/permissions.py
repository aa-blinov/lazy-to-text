"""macOS permissions: what is missing, how to ask, and what a grant restarts.

The Qt reference is the three banners of ``ShortcutsView`` and
``AppController._on_macos_permissions_changed``. Everything is a no-op on
other platforms: each state reads ``null`` there and no banner is shown.

``permissions``   sticky   the payload of ``permissions.status``, published
                           whenever a refresh finds something different

A grant made in System Settings is picked up the next time the renderer
calls ``permissions.refresh`` (it does on showing Settings and on window
focus). No restart: a False to True flip rebuilds the hotkey listener, which
on macOS builds a fresh event tap against the new state.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any, Dict, Optional

from app import hotkey_rules, macos_permissions
from app.server.events import bus
from app.server.rpc import RpcError, method, need

log = logging.getLogger(__name__)

bus.add_sticky("permissions")

_KINDS = ("accessibility", "microphone", "post_event")
_RECHECK_S = 0.25


def _mic_status() -> Optional[str]:
    from app.gui.views import _microphone_check

    return _microphone_check.microphone_authorization_status()


def _banners(listen: Optional[bool], post: Optional[bool], mic: Optional[str],
             mode: str, ptt_key: str, auto_paste: bool) -> Dict[str, str]:
    """Which banner each capability shows: ``hidden`` or the state to fix."""
    accessibility = "hidden"
    if listen is False:
        # Push-to-talk on a solo modifier is the path that is known to work
        # on macOS; the generic "hotkeys will not fire" warning would be
        # wrong about it.
        solo_ptt = mode == "push_to_talk" and hotkey_rules.is_push_to_talk_solo_key(
            ptt_key, platform="darwin"
        )
        if not solo_ptt:
            accessibility = "untrusted"

    microphone = "hidden"
    if mic == "not_determined":
        microphone = "not_determined"
    elif mic in ("denied", "restricted"):
        microphone = "denied"

    post_event = "untrusted" if (auto_paste and post is False) else "hidden"
    return {"accessibility": accessibility, "microphone": microphone, "post_event": post_event}


def status(rt: Any) -> Dict[str, Any]:
    cfg = rt.config
    listen = macos_permissions.is_listen_event_access_trusted()
    post = macos_permissions.is_post_event_access_trusted()
    mic = _mic_status()
    banners = _banners(
        listen, post, mic,
        str(cfg.get_setting("hotkey", "mode") or "two_keys"),
        str(cfg.get_setting("hotkey", "push_to_talk_key") or ""),
        bool(cfg.get_setting("clipboard", "auto_paste")),
    )
    return {
        "platform": sys.platform,
        "applicable": sys.platform == "darwin",
        "listen": listen,
        "post_event": post,
        "microphone": mic,
        "banners": banners,
    }


def _became_granted(previous: Optional[Dict[str, Any]], now: Dict[str, Any]) -> bool:
    if previous is None:
        return False
    if previous.get("listen") is False and now.get("listen") is True:
        return True
    before = previous.get("microphone")
    return before not in (None, "authorized") and now.get("microphone") == "authorized"


def _apply_grant(rt: Any) -> None:
    """What a new grant makes possible without a restart."""
    listener = getattr(rt, "hotkey_listener", None)
    if listener is None:
        return
    try:
        listener.stop_listening()
        listener.start_listening()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Failed to refresh macOS hotkey listener: %s", exc)


def refresh(rt: Any) -> Dict[str, Any]:
    now = status(rt)
    previous = getattr(rt, "_permissions_last", None)
    rt._permissions_last = now
    if _became_granted(previous, now):
        _apply_grant(rt)
    if previous != now:
        bus.emit("permissions", now)
    return now


@method("permissions.status")
def get_status(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return status(rt)


@method("permissions.refresh")
def refresh_method(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Re-read every gate; a grant since the last call is applied and published."""
    return refresh(rt)


def _recheck_later(rt: Any) -> None:
    timer = threading.Timer(_RECHECK_S, lambda: refresh(rt))
    timer.daemon = True
    timer.start()


@method("permissions.request")
def request(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """The banner's button: ask the OS, or open the pane when it will not ask.

    ``kind`` is ``accessibility`` (listening to the hotkeys), ``post_event``
    (the auto-paste keystrokes) or ``microphone``. A refusal without a prompt
    opens the right System Settings pane, so the click is never a no-op. The
    state is re-read shortly after.
    """
    kind = need(params, "kind", str)
    if kind not in _KINDS:
        raise RpcError("bad_params", f"kind must be one of {', '.join(_KINDS)}")
    if sys.platform != "darwin":
        return {"action": "none"}

    if kind == "accessibility":
        granted = macos_permissions.request_listen_event_access()
        action = "prompt" if granted else "opened_settings"
        if not granted:
            macos_permissions.open_accessibility_settings()
    elif kind == "post_event":
        granted = macos_permissions.request_post_event_access()
        action = "prompt" if granted else "opened_settings"
        if not granted:
            macos_permissions.open_accessibility_settings()
    else:
        from app.gui.views import _microphone_check

        current = _microphone_check.microphone_authorization_status()
        if current == "not_determined":
            _microphone_check.request_microphone_access(
                on_result=lambda _granted: refresh(rt)
            )
            action = "prompt"
        elif current in ("denied", "restricted"):
            _microphone_check.open_microphone_settings()
            action = "opened_settings"
        else:
            action = "none"
    _recheck_later(rt)
    return {"action": action}


@method("permissions.open_settings")
def open_settings(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Open the System Settings pane for ``kind`` without asking first."""
    kind = need(params, "kind", str)
    if kind not in _KINDS:
        raise RpcError("bad_params", f"kind must be one of {', '.join(_KINDS)}")
    if kind == "microphone":
        from app.gui.views import _microphone_check

        opened = _microphone_check.open_microphone_settings()
    else:
        opened = macos_permissions.open_accessibility_settings()
    return {"opened": bool(opened)}
