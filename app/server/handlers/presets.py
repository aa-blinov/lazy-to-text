"""Post-processing: the language-model switch, presets and the catalogues.

The Qt reference is ``AppController._on_llm_changed`` and the
``_on_preset_*`` family. A preset is stored as one ``llm.profiles`` list
plus the flat keys mirrored from whichever preset is active; both halves
are written here exactly as the Qt controller writes them, so either
interface can read what the other saved.

Every mutating method answers with the whole state (``presets.get``), so a
screen never has to merge a partial reply into what it already holds.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from app.llm import (
    DEFAULT_TIMEOUT_S,
    MAX_OUTPUT_TOKENS,
    MAX_TIMEOUT_S,
    MIN_TIMEOUT_S,
    MODES,
    PROVIDERS,
    REASONING_EFFORTS,
    SHARED_NOTE,
    LLMError,
    LLMSettings,
    Profile,
    active_profile_id,
    complete,
    default_url_for,
    is_local_url,
    next_profile_id,
    profile_from_mapping,
    profiles_from_config,
    profiles_to_config,
    with_profile,
)
from app.server.events import bus
from app.server.rpc import RpcError, method, need

log = logging.getLogger(__name__)

_FLAT_KEYS = (
    "provider", "model", "base_url", "api_key", "mode",
    "timeout_s", "reasoning_effort", "max_tokens",
)

#: What the connection test sends. A fixed sentence: the user's own words
#: never go to a model for a button press, and nothing here is logged.
_TEST_TEXT = "um so this is a quick test of the connection you know"


def _section(rt: Any) -> Dict[str, Any]:
    return rt.config.get_section("llm") or {}


def _profiles(rt: Any) -> List[Profile]:
    return list(profiles_from_config(_section(rt)))


def _write_profiles(rt: Any, profiles: List[Profile]) -> None:
    rt.config.update_user_setting("llm", "profiles", profiles_to_config(tuple(profiles)))


def _sync_flat_keys(rt: Any, profiles: Optional[List[Profile]] = None) -> None:
    """Mirror the active preset onto the flat keys every older code path reads."""
    section = _section(rt)
    profiles = profiles if profiles is not None else _profiles(rt)
    chosen = next((p for p in profiles if p.id == active_profile_id(section)), None)
    if chosen is None:
        return
    flat = with_profile(section, chosen)
    for key in _FLAT_KEYS:
        rt.config.update_user_setting("llm", key, flat[key])


def _ensure_first_preset(rt: Any) -> None:
    """Write the implicit preset out as a real one, once (Qt does it at launch)."""
    raw = _section(rt).get("profiles")
    if isinstance(raw, list) and raw:
        return
    _write_profiles(rt, _profiles(rt))


def _profile_dict(profile: Profile) -> Dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "provider": profile.provider,
        "model": profile.model,
        "base_url": profile.base_url,
        "api_key": profile.api_key,
        "mode": profile.mode,
        "custom_prompt": profile.custom_prompt,
        "timeout_s": profile.timeout_s,
        "reasoning_effort": profile.reasoning_effort,
        "max_tokens": profile.max_tokens,
        "remote": profile.remote,
    }


def _override_id(rt: Any) -> str:
    getter = getattr(rt.state_manager, "profile_override_id", None)
    return getter() if callable(getter) else ""


def _state(rt: Any) -> Dict[str, Any]:
    section = _section(rt)
    profiles = _profiles(rt)
    return {
        "enabled": bool(section.get("enabled", False)),
        "active_id": active_profile_id(section),
        "override_id": _override_id(rt),
        "profiles": [_profile_dict(p) for p in profiles],
    }


def _changed(rt: Any) -> Dict[str, Any]:
    bus.emit("presets", {})
    return _state(rt)


def _find(profiles: List[Profile], profile_id: str) -> Profile:
    for profile in profiles:
        if profile.id == profile_id:
            return profile
    raise RpcError("not_found", f"no such preset: {profile_id}")


# ---- reads ------------------------------------------------------------------


@method("presets.catalogue")
def catalogue(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Static choices and limits; labels are English source text."""
    return {
        "providers": [
            {"id": p.id, "label": p.label, "url": p.url, "local": is_local_url(p.url) if p.url else None}
            for p in PROVIDERS
        ],
        "modes": [{"id": m.id, "label": m.label, "description": m.description} for m in MODES],
        "efforts": list(REASONING_EFFORTS),
        "shared_note": SHARED_NOTE,
        "limits": {
            "timeout_min": MIN_TIMEOUT_S,
            "timeout_max": MAX_TIMEOUT_S,
            "timeout_default": DEFAULT_TIMEOUT_S,
            "max_tokens_max": MAX_OUTPUT_TOKENS,
        },
    }


@method("presets.get")
def get(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_first_preset(rt)
    return _state(rt)


@method("presets.privacy")
def privacy(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Whether an address stays on this machine; asked while the user types."""
    url = str(params.get("base_url") or "").strip()
    provider = str(params.get("provider") or "ollama")
    resolved = url or default_url_for(provider)
    return {"local": bool(is_local_url(resolved))}


# ---- the switch -------------------------------------------------------------


@method("llm.set_enabled")
def set_enabled(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    enabled = need(params, "enabled", bool)
    rt.config.update_user_setting("llm", "enabled", enabled)
    return _changed(rt)


# ---- presets ----------------------------------------------------------------


@method("presets.update")
def update(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite one preset as a whole value; a partial merge could keep a stale field."""
    payload = need(params, "profile", dict)
    profile_id = str(payload.get("id") or "").strip()
    if not profile_id:
        raise RpcError("bad_params", "profile.id is required")
    profiles = _profiles(rt)
    existing = _find(profiles, profile_id)
    merged = {**profile_dict_without_remote(existing), **payload}
    updated = profile_from_mapping(merged, fallback_id=profile_id)
    profiles[profiles.index(existing)] = updated
    _write_profiles(rt, profiles)
    _sync_flat_keys(rt, profiles)
    return _changed(rt)


def profile_dict_without_remote(profile: Profile) -> Dict[str, Any]:
    data = _profile_dict(profile)
    data.pop("remote", None)
    return data


@method("presets.create")
def create(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Another preset, starting from the first: the server and model are the
    two fields nobody recalls from memory."""
    existing = _profiles(rt)
    created_id = next_profile_id(tuple(existing))
    base = existing[0]
    copy = profile_from_mapping(
        {**profile_dict_without_remote(base), "id": created_id, "name": f"{base.name} copy"},
        fallback_id=created_id,
    )
    _write_profiles(rt, existing + [copy])
    _sync_flat_keys(rt, existing + [copy])
    result = _changed(rt)
    result["created_id"] = created_id
    return result


@method("presets.duplicate")
def duplicate(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    source_id = need(params, "id", str)
    profiles = _profiles(rt)
    source = _find(profiles, source_id)
    new_id = next_profile_id(tuple(profiles), base=source_id)
    # The key goes with the copy: a duplicate that silently lost it would
    # fail with a 401 that reads like a revoked key.
    copy = profile_from_mapping(
        {**profile_dict_without_remote(source), "id": new_id, "name": f"{source.name} copy"},
        fallback_id=new_id,
    )
    profiles.append(copy)
    _write_profiles(rt, profiles)
    result = _changed(rt)
    result["created_id"] = new_id
    return result


@method("presets.delete")
def delete(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    profile_id = need(params, "id", str)
    profiles = _profiles(rt)
    _find(profiles, profile_id)
    remaining = [p for p in profiles if p.id != profile_id]
    if not remaining:
        raise RpcError("last_preset", "the only preset cannot be deleted")
    # Read before writing: get_section hands out the live dict, so after the
    # write the deleted id no longer resolves and would read as not active.
    was_active = active_profile_id(_section(rt)) == profile_id
    _write_profiles(rt, remaining)
    if was_active:
        rt.config.update_user_setting("llm", "active_profile", remaining[0].id)
    _sync_flat_keys(rt, remaining)
    if _override_id(rt) == profile_id:
        _set_override(rt, "")
    return _changed(rt)


@method("presets.activate")
def activate(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    profile_id = need(params, "id", str)
    profiles = _profiles(rt)
    _find(profiles, profile_id)
    rt.config.update_user_setting("llm", "active_profile", profile_id)
    _sync_flat_keys(rt, profiles)
    return _changed(rt)


@method("presets.reset_key")
def reset_key(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Discard one preset's key; routed through the preset, never the flat keys."""
    profile_id = need(params, "id", str)
    profiles = _profiles(rt)
    target = _find(profiles, profile_id)
    was_active = profile_id == active_profile_id(_section(rt))
    cleared = profile_from_mapping(
        {**profile_dict_without_remote(target), "api_key": ""}, fallback_id=profile_id
    )
    profiles[profiles.index(target)] = cleared
    _write_profiles(rt, profiles)
    if was_active:
        _sync_flat_keys(rt, profiles)
    return _changed(rt)


def _set_override(rt: Any, profile_id: str) -> None:
    setter = getattr(rt.state_manager, "set_profile_override", None)
    if callable(setter):
        setter(profile_id)


@method("presets.set_override")
def set_override(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Pin a preset for the next dictation; never written to the config."""
    profile_id = str(params.get("id") or "").strip()
    if profile_id:
        _find(_profiles(rt), profile_id)
    if rt.state_manager is None:
        raise RpcError("no_stack", rt.stack_error or "the recording stack is not running")
    _set_override(rt, profile_id)
    return _changed(rt)


# ---- connection test --------------------------------------------------------


def _settings_for_test(profile: Profile) -> LLMSettings:
    return LLMSettings.from_config(
        {
            **with_profile({}, profile),
            "enabled": True,
            "system_prompt": profile.prompt(),
        }
    )


def _run_test(test_id: str, profile: Profile) -> None:
    started = time.monotonic()
    settings = _settings_for_test(profile)
    ok = True
    message = ""
    try:
        if not settings.model.strip():
            raise LLMError("no model is named")
        complete(_TEST_TEXT, settings)
    except LLMError as exc:
        ok = False
        message = str(exc)
    except Exception as exc:  # pragma: no cover - the type only, never its text
        ok = False
        message = f"the request failed ({type(exc).__name__})"
    bus.emit(
        "llm_test",
        {
            "test_id": test_id,
            "id": profile.id,
            "ok": ok,
            "message": message,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        },
    )


@method("presets.test")
def test(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Start a small request with a preset's settings; the answer is the
    ``llm_test`` event. Takes the editor's current values when given, so a
    field that has not yet been saved is what is tested."""
    test_id = str(params.get("test_id") or "")
    raw = params.get("profile")
    if isinstance(raw, dict):
        profile = profile_from_mapping(raw, fallback_id=str(raw.get("id") or "default"))
    else:
        profile = _find(_profiles(rt), need(params, "id", str))
    threading.Thread(
        target=_run_test, args=(test_id, profile), name="llm-test", daemon=True
    ).start()
    return {"started": True, "test_id": test_id}
