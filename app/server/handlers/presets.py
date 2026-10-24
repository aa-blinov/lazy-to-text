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
import math
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

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


def _remote(profile: Profile) -> bool:
    """Whether the dictation would leave this machine; never raises.

    A stored address that cannot be parsed counts as remote, the safe
    direction, and the screen is told about it through ``base_url_error``.
    """
    try:
        return bool(profile.remote)
    except ValueError:
        return True


def _stored(profile: Profile) -> Dict[str, Any]:
    """Every field, the key included. For writing back, never for a reply."""
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
    }


def _profile_dict(profile: Profile) -> Dict[str, Any]:
    """A preset as a screen sees it: the key is a flag, never the value."""
    data = _stored(profile)
    data.pop("api_key")
    data["api_key_set"] = bool(profile.api_key.strip())
    data["base_url_error"] = address_problem(profile.base_url) or None
    data["remote"] = _remote(profile)
    return data


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


# ---- what a preset may hold --------------------------------------------------

_MAX_URL = 2048
_MAX_KEY = 1024
_MAX_NAME = 80
_MAX_MODEL = 200
_MAX_PROMPT = 20_000


def _has_control(text: str, *, allow_newlines: bool = False) -> bool:
    for ch in text:
        if allow_newlines and ch in "\n\r\t":
            continue
        if ord(ch) < 32 or ord(ch) == 127:
            return True
    return False


def address_problem(value: str) -> str:
    """A sentence about what is wrong with a server address, or ``""``.

    Empty is allowed (the provider's own address is used). Only ``http`` and
    ``https`` are contacted, a name must follow, and credentials never
    belong in the address: they would be written to the log as part of it,
    and the request does not use them. The check is also the reason a
    mistyped address cannot be saved: ``urlsplit`` raises on a missing
    bracket, and what raised when the address was read back took every
    preset call down with it.
    """
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) > _MAX_URL:
        return "That address is too long."
    if _has_control(text) or any(ch.isspace() for ch in text):
        return "The address cannot contain spaces or line breaks."
    try:
        parts = urlsplit(text)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError:
        return "That is not a valid address. Check the brackets and the port number."
    if parts.scheme.lower() not in ("http", "https"):
        return ("The address must start with http:// or https://, for example "
                "http://localhost:11434.")
    if not host:
        return "The address needs a host name after http:// or https://."
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return ("Do not put a user name or password in the address. "
                "Use the API key field instead.")
    return ""


def _key_problem(key: str) -> str:
    if _has_control(key):
        return "The API key cannot contain line breaks or other control characters."
    try:
        key.encode("latin-1")
    except UnicodeEncodeError:
        return "The API key can only contain plain letters, digits and symbols."
    if any(ch.isspace() for ch in key):
        return "The API key cannot contain spaces."
    if len(key) > _MAX_KEY:
        return "That API key is too long."
    return ""


def _bad(field: str, message: str) -> RpcError:
    return RpcError("bad_params", message, field=field)


def _text_field(payload: Dict[str, Any], field: str, limit: int,
                *, allow_newlines: bool = False) -> Optional[str]:
    if field not in payload or payload[field] is None:
        return None
    value = payload[field]
    if not isinstance(value, str):
        raise _bad(field, f"{field} must be text")
    if len(value) > limit:
        raise _bad(field, f"{field} is too long (at most {limit} characters)")
    if _has_control(value, allow_newlines=allow_newlines):
        raise _bad(field, f"{field} cannot contain control characters")
    return value


def _number_field(payload: Dict[str, Any], field: str) -> Optional[float]:
    if field not in payload or payload[field] is None:
        return None
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad(field, f"{field} must be a number")
    try:
        number = float(value)
    except OverflowError:
        raise _bad(field, f"{field} must be a number") from None
    if not math.isfinite(number):
        raise _bad(field, f"{field} must be a number")
    return number


def clean_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The fields of *payload* that were sent, checked and normalised.

    Raises ``bad_params`` naming the field. A field that was not sent is
    absent from the result, so the stored value stays; this is what lets a
    preset that already holds a value this build would refuse (a hand-edited
    address) be saved again without touching it. ``api_key`` is only
    present when a non-empty key was sent: absent, null and the empty string
    all mean "keep the stored key", and removing one is ``presets.reset_key``.
    Unknown fields, including the derived ``remote``, ``api_key_set`` and
    ``base_url_error`` a screen may send back, are ignored.
    """
    out: Dict[str, Any] = {}

    name = _text_field(payload, "name", _MAX_NAME)
    if name is not None:
        out["name"] = name.strip()
    model = _text_field(payload, "model", _MAX_MODEL)
    if model is not None:
        out["model"] = model.strip()
    prompt = _text_field(payload, "custom_prompt", _MAX_PROMPT, allow_newlines=True)
    if prompt is not None:
        out["custom_prompt"] = prompt

    provider = _text_field(payload, "provider", 64)
    if provider is not None:
        provider = provider.strip()
        if provider not in {p.id for p in PROVIDERS}:
            raise _bad("provider", "That provider is not in the list.")
        out["provider"] = provider

    url = _text_field(payload, "base_url", _MAX_URL + 1)
    if url is not None:
        problem = address_problem(url)
        if problem:
            raise _bad("base_url", problem)
        out["base_url"] = url.strip()

    key = _text_field(payload, "api_key", _MAX_KEY + 1)
    if key is not None and key != "":
        key = key.strip()
        problem = _key_problem(key)
        if problem:
            raise _bad("api_key", problem)
        if key:
            out["api_key"] = key

    mode = _text_field(payload, "mode", 64)
    if mode is not None:
        mode = mode.strip()
        if mode not in {m.id for m in MODES}:
            raise _bad("mode", "That mode is not in the list.")
        out["mode"] = mode

    effort = _text_field(payload, "reasoning_effort", 32)
    if effort is not None:
        effort = effort.strip()
        if effort and effort not in REASONING_EFFORTS:
            raise _bad("reasoning_effort", "That effort is not in the list.")
        out["reasoning_effort"] = effort

    timeout = _number_field(payload, "timeout_s")
    if timeout is not None:
        out["timeout_s"] = int(max(MIN_TIMEOUT_S, min(MAX_TIMEOUT_S, round(timeout))))
    tokens = _number_field(payload, "max_tokens")
    if tokens is not None:
        out["max_tokens"] = int(max(0, min(MAX_OUTPUT_TOKENS, round(tokens))))
    return out


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
    raw = params.get("base_url")
    url = raw.strip() if isinstance(raw, str) else ""
    provider = params.get("provider")
    provider = provider if isinstance(provider, str) and provider else "ollama"
    problem = address_problem(url)
    if problem:
        # Asked on every keystroke: a half-typed address is the normal case
        # and has to be an answer, not an error.
        return {"local": False, "valid": False, "message": problem}
    resolved = url or default_url_for(provider)
    try:
        local = bool(is_local_url(resolved))
    except ValueError:
        return {"local": False, "valid": False,
                "message": "That is not a valid address."}
    return {"local": local, "valid": True, "message": ""}


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
    raw_id = payload.get("id")
    profile_id = raw_id.strip() if isinstance(raw_id, str) else ""
    if not profile_id:
        raise RpcError("bad_params", "profile.id is required", field="id")
    profiles = _profiles(rt)
    existing = _find(profiles, profile_id)
    changes = clean_fields(payload)
    merged = {**profile_dict_without_remote(existing), **changes, "id": profile_id}
    updated = profile_from_mapping(merged, fallback_id=profile_id)
    profiles[profiles.index(existing)] = updated
    _write_profiles(rt, profiles)
    _sync_flat_keys(rt, profiles)
    return _changed(rt)


def profile_dict_without_remote(profile: Profile) -> Dict[str, Any]:
    """The stored fields, key included, for merging an edit over them."""
    return _stored(profile)


@method("presets.create")
def create(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Another preset, starting from the first: the server and model are the
    two fields nobody recalls from memory. The key is not copied."""
    existing = _profiles(rt)
    created_id = next_profile_id(tuple(existing))
    base = existing[0]
    # Without the key: a new preset is pointed somewhere new, and the first
    # preset's key must not travel to whatever server it ends up naming.
    copy = profile_from_mapping(
        {**profile_dict_without_remote(base), "id": created_id,
         "name": f"{base.name} copy", "api_key": ""},
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


#: Seconds past the preset's own timeout that the test waits before it
#: gives up on the request thread. The timeout applies to each socket read,
#: so a server that answers one byte at a time can outlast it.
_TEST_GRACE_S = 3.0


def _run_test(test_id: str, profile: Profile, refusal: str = "") -> None:
    started = time.monotonic()
    ok = True
    message = refusal
    if refusal:
        ok = False
    else:
        outcome: Dict[str, Any] = {}

        def request() -> None:
            try:
                settings = _settings_for_test(profile)
                if not settings.model.strip():
                    raise LLMError("no model is named")
                complete(_TEST_TEXT, settings)
            except LLMError as exc:
                outcome["error"] = str(exc)
            except Exception as exc:  # the type only, never its text
                outcome["error"] = f"the request failed ({type(exc).__name__})"

        worker = threading.Thread(target=request, daemon=True, name="llm-test-request")
        worker.start()
        worker.join(profile.timeout_s + _TEST_GRACE_S)
        if worker.is_alive():
            ok = False
            message = (f"the server did not finish answering within "
                       f"{profile.timeout_s} seconds")
        elif "error" in outcome:
            ok = False
            message = outcome["error"]
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
    field that has not yet been saved is what is tested.

    The editor does not hold the stored key, so a ``profile`` that names a
    stored preset by ``id`` and sends no key is tested with that preset's own
    key. A field that is not acceptable (an address that is not a URL) does
    not fail the call: the test starts and the event says why, so the screen
    has one place to look. The request has an overall deadline.
    """
    raw_test_id = params.get("test_id")
    test_id = raw_test_id if isinstance(raw_test_id, str) else ""
    raw = params.get("profile")
    refusal = ""
    if isinstance(raw, dict):
        stored_id = raw.get("id")
        base: Dict[str, Any] = {}
        if isinstance(stored_id, str) and stored_id.strip():
            match = next((p for p in _profiles(rt) if p.id == stored_id.strip()), None)
            if match is not None:
                base = profile_dict_without_remote(match)
        try:
            changes = clean_fields(raw)
        except RpcError as exc:
            changes, refusal = {}, exc.message
        merged = {**base, **changes}
        merged["id"] = (stored_id.strip() if isinstance(stored_id, str) and stored_id.strip()
                        else "default")
        profile = profile_from_mapping(merged, fallback_id=merged["id"])
    else:
        profile = _find(_profiles(rt), need(params, "id", str))
        problem = address_problem(profile.base_url)
        if problem:
            refusal = problem
    threading.Thread(
        target=_run_test, args=(test_id, profile, refusal), name="llm-test", daemon=True
    ).start()
    return {"started": True, "test_id": test_id}
