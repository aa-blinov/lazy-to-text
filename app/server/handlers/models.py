"""Model management: catalogue, cache, selection, deletion, inference
settings, storage location and the Hugging Face token.

The reference for every side effect is ``app/gui/controllers/app_controller.py``
(``_on_model_selected``, ``_on_cancel_load_requested``,
``_on_model_delete_requested``, ``_on_inference_settings_changed``) and
``_storage_mixin.py``. Where this module does something the Qt controller
does not, the contract file (``contracts/rpc-models.md``) says so.

Nothing here blocks the channel thread for long: a model switch is handed
to the state manager, which already runs it on its own thread; deletion,
storage moves and size measurement start a thread and report by event.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.server.events import bus
from app.server.rpc import RpcError, method, need

log = logging.getLogger(__name__)

# How long a restore of the previous model waits for an abandoned load
# thread to unwind before giving up. The backend refuses a new load while
# the old one is still inside native code, so asking earlier would be
# refused silently.
_RESTORE_WAIT_S = 120.0

# Spoken languages the Whisper panel offers. The code is what the engine
# takes; the label is the English source string the renderer translates.
LANGUAGES = (
    ("Auto-detect", None),
    ("Russian", "ru"),
    ("English", "en"),
    ("Spanish", "es"),
    ("French", "fr"),
    ("German", "de"),
    ("Chinese", "zh"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
    ("Arabic", "ar"),
    ("Hindi", "hi"),
    ("Portuguese", "pt"),
    ("Italian", "it"),
    ("Polish", "pl"),
    ("Dutch", "nl"),
    ("Turkish", "tr"),
    ("Ukrainian", "uk"),
)


# ---- per-runtime bookkeeping ----------------------------------------------


class _Ctx:
    """What the handlers remember between calls, kept on the runtime."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        # The pre-click state ``models.select`` snapshots so a cancel can
        # put everything back, exactly as ``_pre_select_snapshot`` does.
        self.snapshot: Optional[Dict[str, Any]] = None
        # The alias the user just picked. It counts as active while its
        # weights are still arriving, so the card can say "Loading" before
        # there is anything on disk to be active.
        self.selecting: Optional[str] = None
        # Incremented by every select; a restore that started before the
        # user chose again must not overwrite their choice.
        self.generation = 0
        self.load_alias = ""
        self.deleting: set[str] = set()
        self.storage_busy = False
        self.push_lock = threading.Lock()
        self.push_pending: Any = None
        self.push_thread: Optional[threading.Thread] = None
        self.stop = threading.Event()
        self.watcher: Optional[threading.Thread] = None
        self.restore_thread: Optional[threading.Thread] = None
        # How the last load ended, kept for a window that was not listening
        # when ``model_load`` went out: ``{alias, outcome, at}`` or None.
        self.last_load: Optional[Dict[str, Any]] = None


def _ctx(rt: Any) -> _Ctx:
    ctx = getattr(rt, "_models_ctx", None)
    if ctx is None:
        ctx = _Ctx()
        try:
            rt._models_ctx = ctx
        except AttributeError:  # pragma: no cover - slotted stand-ins
            pass
    return ctx


# ---- catalogue -------------------------------------------------------------


def _settings_kind(info: Any) -> Optional[str]:
    family = getattr(info, "onnx_family", "")
    if family == "whisper":
        return "whisper"
    if family == "parakeet":
        return "parakeet"
    return None


def _settings_class(kind: Optional[str]):
    from app.inference_settings import InferenceSettings, ParakeetInferenceSettings

    return ParakeetInferenceSettings if kind == "parakeet" else InferenceSettings


def _load_settings(rt: Any, alias: str):
    from app.model_mapping import get_model

    try:
        kind = _settings_kind(get_model(alias))
    except KeyError:
        kind = "whisper"
    try:
        raw = rt.config.get_setting("model_overrides", alias)
    except Exception:  # pragma: no cover - defensive
        raw = None
    return _settings_class(kind).from_mapping(raw)


def _card(info: Any, siblings: List[str]) -> Dict[str, Any]:
    from app.model_mapping import measurement_for, model_url

    wer, rtf = measurement_for(info.alias)
    return {
        "alias": info.alias,
        "canonical": info.canonical,
        "display_name": info.display_name,
        "size_mb": info.size_mb,
        "vram_gb": info.vram_gb,
        "speed": info.speed,
        "quality": info.quality,
        "languages": info.languages,
        "description": info.description,
        "compute_type": info.compute_type,
        "family": info.family,
        "onnx_family": info.onnx_family,
        "recommended": bool(info.recommended),
        "pitch": info.pitch,
        "url": model_url(info),
        "wer": wer or None,
        "rtf": rtf or None,
        "prefer_cpu": bool(info.prefer_cpu_provider),
        "auto_language": info.auto_language,
        "shared_with": siblings,
        "inference": {"kind": _settings_kind(info)},
    }


def _siblings(info: Any) -> List[str]:
    from app.model_mapping import MODELS

    return [m.alias for m in MODELS
            if m.canonical == info.canonical and m.alias != info.alias]


def _info_or_raise(alias: str):
    from app.model_mapping import get_model

    try:
        return get_model(alias)
    except KeyError:
        raise RpcError("unknown_model", f"no such model: {alias}") from None


def _cached_map() -> Dict[str, bool]:
    from app.model_mapping import MODELS
    from app.utils import is_cached_for_info

    out: Dict[str, bool] = {}
    for info in MODELS:
        try:
            out[info.alias] = bool(is_cached_for_info(info))
        except Exception:  # pragma: no cover - defensive
            out[info.alias] = False
    return out


def _configured_alias(rt: Any) -> Optional[str]:
    """The alias ``whisper.model`` names, or None when it names nothing the
    registry knows. A retired id is never remapped (spec 002)."""
    from app.model_mapping import alias_for, get_model

    raw = rt.config.get_setting("whisper", "model")
    if not isinstance(raw, str) or not raw.strip():
        return None
    alias = alias_for(raw.strip())
    try:
        get_model(alias)
    except KeyError:
        return None
    return alias


def _active_alias(rt: Any, cached: Dict[str, bool]) -> Optional[str]:
    """The card that is active: the configured model when its weights are on
    disk, or while it is the one being fetched. Qt marks a configured but
    absent model active only right after a click; this makes that rule hold
    for a reload too, so a failed download does not leave a card claiming to
    be loaded."""
    alias = _configured_alias(rt)
    if alias is None:
        return None
    ctx = _ctx(rt)
    if cached.get(alias) or ctx.selecting == alias or rt.state() == "model_loading":
        return alias
    return None


def _engine_ready(rt: Any) -> bool:
    """Whether the backend actually has a model loaded.

    ``active`` follows the configuration and the disk, so a model that is on
    disk and configured reads as active even when nothing loaded it (the
    weights were put back after a start that skipped the load). ``ready`` is
    the part only the backend knows.
    """
    try:
        return rt.backend.status() == "ready"
    except Exception:
        return False


def _state(rt: Any, cached: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    ctx = _ctx(rt)
    cached = cached if cached is not None else _cached_map()
    state = rt.state()
    return {
        "active": _active_alias(rt, cached),
        "state": state,
        "loading": state == "model_loading",
        "cached": cached,
        "deleting": sorted(ctx.deleting),
        "storage_busy": ctx.storage_busy,
        "last_load": ctx.last_load,
        "ready": _engine_ready(rt),
    }


def _publish(rt: Any) -> Dict[str, Any]:
    snapshot = _state(rt)
    try:
        rt.has_model_on_disk = any(snapshot["cached"].values())
    except Exception:  # pragma: no cover - defensive
        pass
    bus.emit("models", snapshot)
    return snapshot


@method("models.list")
def list_models(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Every card in catalogue order, with the live state next to it."""
    from app.model_mapping import MODELS, display_order

    ordered = display_order(MODELS)
    cards = []
    for info in ordered:
        card = _card(info, _siblings(info))
        if card["inference"]["kind"] is not None:
            card["inference"]["values"] = _load_settings(rt, info.alias).to_mapping()
        cards.append(card)
    return {
        "models": cards,
        "languages": [{"label": label, "code": code} for label, code in LANGUAGES],
        **_state(rt),
    }


@method("models.state")
def state(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return _state(rt)


# ---- selection --------------------------------------------------------------


def _need_stack(rt: Any) -> Any:
    if rt.state_manager is None:
        raise RpcError("no_stack", rt.stack_error or "the recording stack is not running")
    return rt.state_manager


def _select(rt: Any, alias: str) -> Dict[str, Any]:
    """The whole sequence of ``_on_model_selected``."""
    info = _info_or_raise(alias)
    sm = _need_stack(rt)
    ctx = _ctx(rt)

    if rt.state() == "model_loading":
        # Qt wrote the config first and let the state manager refuse; that
        # left ``whisper.model`` naming a model that never started loading.
        raise RpcError("busy", "A model is already loading. Cancel it or wait.")
    with ctx.lock:
        deleting = bool(ctx.deleting & ({alias} | set(_siblings(info))))
        moving = ctx.storage_busy
    if deleting:
        # The load that follows would have to fetch the weights again, and
        # the card would have said "not downloading" when it was clicked.
        raise RpcError("busy", "That model is being deleted. Wait for it to finish.")
    if moving:
        raise RpcError("busy", "The models folder is being changed. Wait for it to finish.")

    cached = _cached_map()
    if (_active_alias(rt, cached) == alias and cached.get(alias)
            and _engine_ready(rt)):
        return {"alias": alias, "noop": True, "downloading": False, "state": rt.state()}

    previous = _active_alias(rt, cached)
    snapshot = {
        "alias": previous,
        "config_model": rt.config.get_setting("whisper", "model"),
        "config_compute": rt.config.get_setting("whisper", "compute_type"),
    }
    with ctx.lock:
        ctx.generation += 1
        ctx.snapshot = snapshot
        ctx.selecting = alias

    rt.config.update_user_setting("whisper", "model", alias)
    rt.config.update_user_setting("whisper", "compute_type", info.compute_type)
    push_inference(rt, _load_settings(rt, alias))

    try:
        accepted = sm.request_model_change(alias, info.compute_type)
    except Exception as exc:
        _rollback(rt, snapshot)
        raise RpcError("internal", f"could not start the switch: {exc}") from exc
    if accepted is False:
        _rollback(rt, snapshot)
        raise RpcError("busy", "The model could not be switched right now.")

    _publish(rt)
    return {
        "alias": alias,
        "noop": False,
        "downloading": not cached.get(alias, False),
        "state": rt.state(),
    }


def _rollback(rt: Any, snapshot: Optional[Dict[str, Any]]) -> None:
    """Put ``whisper.model`` and ``whisper.compute_type`` back."""
    ctx = _ctx(rt)
    with ctx.lock:
        ctx.snapshot = None
        ctx.selecting = None
    if snapshot is None:
        return
    prev_model = snapshot.get("config_model")
    # An empty string when there was no previous model, as Qt writes it.
    rt.config.update_user_setting("whisper", "model", prev_model if prev_model is not None else "")
    prev_compute = snapshot.get("config_compute")
    if prev_compute is not None:
        rt.config.update_user_setting("whisper", "compute_type", prev_compute)


@method("models.select")
def select(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return _select(rt, need(params, "alias", str))


@method("models.download")
def download(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Qt has one code path for Download and Select: a card that is not on
    disk is fetched by selecting it. Kept as its own method so the renderer
    can say what it means, and so a cached model is refused here instead of
    being re-selected by accident."""
    alias = need(params, "alias", str)
    info = _info_or_raise(alias)
    ctx = _ctx(rt)
    with ctx.lock:
        deleting = bool(ctx.deleting & ({alias} | set(_siblings(info))))
    if deleting:
        # Still on disk while the delete runs, so it would read as cached.
        raise RpcError("busy", "That model is being deleted. Wait for it to finish.")
    if _cached_map().get(alias):
        raise RpcError("already_cached", "That model is already downloaded.")
    return _select(rt, alias)


@method("models.cancel_load")
def cancel_load(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Stop the load or download in progress, and say truthfully whether it stopped.

    The state manager's own flag is what ``cancel_model_change`` consults, and
    that flag can already be down while the backend is still loading (its
    watcher reads the previous model's cached ``ready`` right after a switch
    starts and clears the flag). When the state manager says there is nothing
    to cancel but the runtime's state is still ``model_loading``, the backend
    is asked directly and the flag is cleared here, so a download the user
    can see running is not reported as "nothing to cancel".
    """
    sm = _need_stack(rt)
    ctx = _ctx(rt)
    try:
        cancelled = bool(sm.cancel_model_change())
    except Exception as exc:
        log.warning("cancel_model_change raised: %s", exc)
        raise RpcError("internal", "The load could not be cancelled. "
                                   "The Logs have the details.") from exc
    if not cancelled and rt.state() == "model_loading":
        cancelled = _cancel_in_backend(rt, sm)
    if not cancelled:
        # A cancel that raced a finished load changes nothing.
        return {"cancelled": False, **_state(rt)}

    with ctx.lock:
        snapshot = ctx.snapshot
        generation = ctx.generation
    _rollback(rt, snapshot)
    restored = snapshot.get("alias") if snapshot else None
    result = {"cancelled": True, "restored": restored, **_state(rt)}
    if restored:
        _restore_previous(rt, restored, generation)
    _publish(rt)
    return result


def _cancel_in_backend(rt: Any, sm: Any) -> bool:
    """Cancel a load the state manager no longer tracks. True if one was running."""
    backend = getattr(rt, "backend", None)
    try:
        status = backend.status() if backend is not None else ""
    except Exception:  # pragma: no cover - defensive
        status = ""
    target = getattr(backend, "cancel_load", None)
    if status != "loading" or not callable(target):
        return False
    log.info("Cancelling a model load the state manager no longer tracked",
             extra={"user_message": True})
    try:
        target()
    except Exception as exc:
        log.warning("backend.cancel_load raised: %s", exc)
        return False
    clear = getattr(sm, "set_model_loading", None)
    if callable(clear):
        try:
            clear(False)
        except Exception:  # pragma: no cover - defensive
            pass
    return True


def _restore_previous(rt: Any, alias: str, generation: int) -> None:
    """Load the model that was active before the cancelled switch.

    The backend drops its model the moment a switch starts and a cancel
    leaves it stopped, so restoring the card and the config alone leaves a
    card that claims a model nothing has loaded, and re-selecting it is a
    no-op. The reload waits for the abandoned load thread to unwind, because
    the backend refuses a second load until then.
    """
    ctx = _ctx(rt)
    info = _info_or_raise(alias)
    sm = rt.state_manager

    def run() -> None:
        deadline = time.monotonic() + _RESTORE_WAIT_S
        probe = getattr(rt.backend, "load_in_flight", None)
        while callable(probe) and time.monotonic() < deadline:
            try:
                if not probe():
                    break
            except Exception:  # pragma: no cover - defensive
                break
            if ctx.stop.wait(0.2):
                return
        with ctx.lock:
            if ctx.generation != generation:
                return  # the user chose something else meanwhile
        # The state manager refuses while it still reads a load in progress
        # (the abandoned attempt, or the worker's status push that has not
        # arrived yet); a refused restore is retried, a dropped one leaves
        # the app on "Loading..." with nothing loading.
        retry_until = time.monotonic() + _RESTORE_WAIT_S
        while True:
            try:
                accepted = sm.request_model_change(alias, info.compute_type)
            except Exception as exc:
                log.warning("Could not reload %s after the cancel: %s", alias, exc,
                            extra={"user_message": True})
                return
            if accepted is not False or time.monotonic() > retry_until:
                break
            with ctx.lock:
                if ctx.generation != generation:
                    return
            if ctx.stop.wait(0.2):
                return
        if accepted is False:
            log.warning("Could not reload %s after the cancel.", alias,
                        extra={"user_message": True})

    thread = threading.Thread(target=run, daemon=True, name=f"restore-model:{alias}")
    ctx.restore_thread = thread
    thread.start()


# ---- deletion ---------------------------------------------------------------


@method("models.delete_info")
def delete_info(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """What a delete would free, measured on disk, for the confirmation."""
    from app.utils import cached_model_size

    info = _info_or_raise(need(params, "alias", str))
    cached = _cached_map()
    active = _active_alias(rt, cached)
    return {
        "alias": info.alias,
        "cached": bool(cached.get(info.alias)),
        "size_bytes": int(cached_model_size(info.canonical)),
        "catalogue_mb": info.size_mb,
        "shared_with": _siblings(info),
        "in_use": active in ([info.alias] + _siblings(info))
        or rt.state() == "model_loading",
    }


@method("models.delete")
def delete(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    from app.utils import cached_model_size, delete_cached_for_info

    info = _info_or_raise(need(params, "alias", str))
    ctx = _ctx(rt)
    cached = _cached_map()
    active = _active_alias(rt, cached)
    # A variant that shares the repository shares the files: deleting this
    # card would pull the weights out from under the active one.
    if rt.state() == "model_loading" or active in ([info.alias] + _siblings(info)):
        raise RpcError("in_use", "The active model cannot be deleted.")
    if not cached.get(info.alias):
        raise RpcError("not_cached", "That model is not downloaded.")
    with ctx.lock:
        if info.alias in ctx.deleting:
            raise RpcError("busy", "That model is already being deleted.")
        if ctx.storage_busy:
            raise RpcError("busy", "The models folder is being changed. Wait for it to finish.")
        if ctx.selecting in ([info.alias] + _siblings(info)):
            # A select that has started but is not yet visible to the check above.
            raise RpcError("in_use", "The active model cannot be deleted.")
        ctx.deleting.add(info.alias)
    _publish(rt)

    def work() -> None:
        freed = 0
        error = ""
        deleted = False
        try:
            freed = int(cached_model_size(info.canonical))
            deleted = bool(delete_cached_for_info(info))
            if not deleted:
                error = "The folder could not be removed. A file may be in use; see the log."
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Deleting %s raised: %s", info.alias, exc)
            error = "The folder could not be removed. A file may be in use; see the log."
        finally:
            with ctx.lock:
                ctx.deleting.discard(info.alias)
        if deleted:
            log.info("Deleted cached weights for %s", info.alias)
        else:
            log.warning("Delete returned False for %s", info.alias)
        bus.emit("model_delete", {
            "alias": info.alias,
            "deleted": deleted,
            "error": error,
            "freed_bytes": freed if deleted else 0,
            "shared_with": _siblings(info),
        })
        _publish(rt)
        _measure_storage(rt)

    threading.Thread(target=work, daemon=True, name=f"delete-model:{info.alias}").start()
    return {"started": True}


# ---- inference settings -----------------------------------------------------


@method("models.inference.get")
def inference_get(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    info = _info_or_raise(need(params, "alias", str))
    kind = _settings_kind(info)
    values = _load_settings(rt, info.alias).to_mapping() if kind else {}
    return {"alias": info.alias, "kind": kind, "values": values}


def _valid_languages() -> set:
    return {code for _label, code in LANGUAGES if code}


def _checked_inference(values: Dict[str, Any]) -> Dict[str, Any]:
    """The fields of *values* that are acceptable, or ``bad_params`` naming one.

    Anything that would be silently replaced by a default is refused instead:
    a beam size of ``"abc"`` stored as 5 looks like a saved setting.
    """
    out: Dict[str, Any] = {}
    for key, value in values.items():
        if key == "language":
            if value is None or value in ("", "auto"):
                out[key] = None
            elif isinstance(value, str) and value in _valid_languages():
                out[key] = value
            else:
                raise RpcError("bad_params", "That language is not in the list.", field=key)
        elif key in ("vad_filter", "timestamps"):
            if not isinstance(value, bool):
                raise RpcError("bad_params", f"{key} must be true or false", field=key)
            out[key] = value
        elif key == "initial_prompt":
            if value is not None and not isinstance(value, str):
                raise RpcError("bad_params", "initial_prompt must be text", field=key)
            if isinstance(value, str) and (len(value) > 2000 or "\x00" in value):
                raise RpcError("bad_params", "That prompt is too long.", field=key)
            out[key] = value
        elif key in ("beam_size", "temperature"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RpcError("bad_params", f"{key} must be a number", field=key)
            try:
                finite = math.isfinite(float(value))
            except OverflowError:
                finite = False
            if not finite:
                raise RpcError("bad_params", f"{key} must be a number", field=key)
            out[key] = value
    return out


@method("models.inference.set")
def inference_set(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Persist under ``model_overrides.<alias>`` and, on the active card,
    push to the running backend. Only the fields sent change; the rest keep
    the saved value, so a partial update cannot reset a neighbour. A value
    that is not acceptable is refused (``bad_params``, with the field);
    numbers outside the range are clamped."""
    info = _info_or_raise(need(params, "alias", str))
    kind = _settings_kind(info)
    if kind is None:
        raise RpcError("no_settings", "That model has no inference settings.")
    values = need(params, "values", dict)
    merged = _load_settings(rt, info.alias).to_mapping()
    merged.update({k: v for k, v in _checked_inference(values).items() if k in merged})
    settings = _settings_class(kind).from_mapping(merged)
    rt.config.update_user_setting("model_overrides", info.alias, settings.to_mapping())
    pushed = False
    if _active_alias(rt, _cached_map()) == info.alias:
        push_inference(rt, settings)
        pushed = True
    return {"alias": info.alias, "kind": kind, "values": settings.to_mapping(), "pushed": pushed}


def push_inference(rt: Any, settings: Any) -> None:
    """Hand settings to the backend off the calling thread.

    Latest wins: a burst of edits (a field typed into) collapses to the last
    one instead of queueing a worker round trip per keystroke.
    """
    ctx = _ctx(rt)
    with ctx.push_lock:
        ctx.push_pending = settings
        thread = ctx.push_thread
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(target=_drain_pushes, args=(rt, ctx),
                                  daemon=True, name="push-inference-settings")
        ctx.push_thread = thread
    thread.start()


def _drain_pushes(rt: Any, ctx: _Ctx) -> None:
    while True:
        with ctx.push_lock:
            settings = ctx.push_pending
            if settings is None:
                ctx.push_thread = None
                return
            ctx.push_pending = None
        target = getattr(rt.backend, "update_inference_settings", None)
        if target is None:
            with ctx.push_lock:
                ctx.push_thread = None
            return
        try:
            target(settings)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Live inference-settings push raised: %s", exc)


def push_vad(rt: Any, enabled: bool) -> None:
    """Turn the silero VAD on or off in the running backend.

    Public because the global switch lives in Settings: that screen's handler
    calls this after it persists ``audio.vad_enabled``. The first enable
    downloads a small model, hence the thread.
    """
    target = getattr(getattr(rt, "backend", None), "set_vad_enabled", None)
    if target is None:
        return

    def run() -> None:
        try:
            target(bool(enabled))
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Live VAD push raised: %s", exc)

    threading.Thread(target=run, daemon=True, name="push-vad-setting").start()


# ---- storage ---------------------------------------------------------------


def _storage_summary(rt: Any) -> Dict[str, Any]:
    from app.utils import get_models_root

    configured = rt.config.get_setting("storage", "models_dir")
    is_default = not (configured and str(configured).strip())
    root = get_models_root(configured)
    return {
        "path": root,
        "is_default": is_default,
        "configured": configured or "",
        "exists": Path(root).is_dir(),
        "busy": _ctx(rt).storage_busy,
    }


def _measure_storage(rt: Any) -> None:
    from app.utils import cached_models_size

    root = _storage_summary(rt)["path"]

    def work() -> None:
        try:
            size = int(cached_models_size(root))
        except Exception:  # pragma: no cover - defensive
            size = 0
        bus.emit("storage", {"phase": "size", "path": root, "size_bytes": size})

    threading.Thread(target=work, daemon=True, name="measure-storage").start()


@method("models.storage.get")
def storage_get(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Where the weights live. The size follows as a ``storage`` event with
    ``phase: "size"``, because walking a multi-gigabyte cache is not a
    request-sized job."""
    summary = _storage_summary(rt)
    _measure_storage(rt)
    return {**summary, "size_bytes": None}


def _resolve(path: str) -> Path:
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError):
        return Path(os.path.abspath(path))


def _same_dir(a: str, b: str) -> bool:
    return _resolve(a) == _resolve(b)


def _relation(chosen: str, current: str) -> Optional[str]:
    """How a destination relates to the folder the weights are in now.

    ``"same"``, ``"inside"`` (a subfolder of the current root: moving the
    weights there copies a tree into itself) or ``"contains"`` (a parent of
    the current root). ``None`` for an unrelated folder. Resolved through
    links, because a link into the current root is the same thing.
    """
    new, old = _resolve(chosen), _resolve(current)
    if new == old:
        return "same"
    if old in new.parents:
        return "inside"
    if new in old.parents:
        return "contains"
    return None


_RELATION_MESSAGES = {
    "inside": "That folder is inside the current models folder. Choose a "
              "folder that is not part of it.",
    "contains": "That folder contains the current models folder. Choose a "
                "folder that is not a parent of it.",
}


def _check_destination(chosen: str, current: str, *, allow_same: bool) -> Optional[str]:
    """Refuse a destination that overlaps the current root; returns the relation."""
    relation = _relation(chosen, current)
    if relation in _RELATION_MESSAGES:
        raise RpcError("bad_path", _RELATION_MESSAGES[relation], field="path")
    if relation == "same" and not allow_same:
        raise RpcError("bad_path", "That is the folder already in use.", field="path")
    return relation


@method("models.storage.plan")
def storage_plan(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """What choosing ``path`` would do, so the renderer can ask Move, Leave
    or Cancel before anything changes. A folder that is inside, or a parent
    of, the current models folder is refused with ``bad_path``."""
    from app.utils import cached_models_size

    chosen = need(params, "path", str).strip()
    if not chosen or not os.path.isdir(chosen):
        raise RpcError("bad_path", "That is not a folder.", field="path")
    if not os.access(chosen, os.W_OK):
        raise RpcError("bad_path", "That folder cannot be written to.", field="path")
    current = _storage_summary(rt)["path"]
    same = _check_destination(chosen, current, allow_same=True) == "same"
    return {
        "path": chosen,
        "current": current,
        "same": same,
        "old_size": 0 if same else int(cached_models_size(current)),
        "destination_has_models": bool(cached_models_size(chosen)) if not same else False,
    }


@method("models.storage.apply")
def storage_apply(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Change the models folder. ``move`` relocates the ``hub`` folder first;
    without it old weights stay where they are and only new downloads go to
    the new place. Progress and the outcome arrive as ``storage`` events.

    The same checks as ``models.storage.plan`` run again here, because a
    caller need not have asked: the folder has to exist, be writable, and not
    be inside or a parent of the current models folder.
    """
    chosen = need(params, "path", str).strip()
    move = bool(params.get("move", False))
    if not chosen or not os.path.isdir(chosen):
        raise RpcError("bad_path", "That is not a folder.", field="path")
    if not os.access(chosen, os.W_OK):
        raise RpcError("bad_path", "That folder cannot be written to.", field="path")
    _check_destination(chosen, _storage_summary(rt)["path"], allow_same=True)
    return _start_storage_change(rt, chosen, move)


@method("models.storage.reset")
def storage_reset(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Back to the built-in default; nothing is moved."""
    return _start_storage_change(rt, "", False)


def _start_storage_change(rt: Any, chosen: str, move: bool) -> Dict[str, Any]:
    ctx = _ctx(rt)
    if rt.state() == "model_loading":
        raise RpcError("busy", "A model is loading. Wait for it or cancel it first.")
    with ctx.lock:
        if ctx.storage_busy:
            raise RpcError("busy", "A storage change is already running.")
        if ctx.deleting:
            raise RpcError("busy", "A model is being deleted. Wait for it to finish.")
        ctx.storage_busy = True
    threading.Thread(target=_storage_worker, args=(rt, chosen, move),
                     daemon=True, name="storage-change").start()
    return {"started": True}


def _friendly_reason(reason: str) -> Optional[str]:
    """A code for the renderer, or None for the cases Qt does not surface
    (a source that was never there, source and destination the same)."""
    text = (reason or "").lower()
    if "missing" in text or "same" in text:
        return None
    if "destination already exists" in text:
        return "destination_exists"
    if "copy failed" in text or "overlap" in text:
        return "copy_failed"
    if "permission" in text or "access" in text:
        return "in_use"
    return "other"


def _tree_files(root: Path) -> Dict[str, int]:
    """``{relative path: size}`` of every regular file under *root*, links not followed."""
    found: Dict[str, int] = {}
    for current, _dirs, names in os.walk(root, followlinks=False):
        for name in names:
            full = Path(current) / name
            try:
                if full.is_symlink():
                    found[str(full.relative_to(root))] = -1
                elif full.is_file():
                    found[str(full.relative_to(root))] = full.stat().st_size
            except OSError:
                found[str(full.relative_to(root))] = -2
    return found


def move_hub(src: str, dst: str) -> Dict[str, Any]:
    """Move the ``hub`` folder, and never delete the source before the copy is proved.

    Same result shape as ``app.utils.move_cached_dir``. A rename is tried
    first. Across volumes the tree is copied to a destination that did not
    exist, compared with the source file by file (names and sizes), and only
    then is the source removed; a copy that does not match is removed again
    and the source is left exactly as it was. A destination that equals,
    contains or sits inside the source is refused before anything is touched.
    """
    source, target = Path(src), Path(dst)
    if not source.exists():
        return {"moved": False, "reason": "source missing"}
    if _resolve(src) == _resolve(dst):
        return {"moved": False, "reason": "source and destination are the same"}
    if _relation(dst, src) in ("inside", "contains"):
        return {"moved": False, "reason": "copy failed: the folders overlap"}
    if target.exists():
        return {"moved": False, "reason": "destination already exists"}
    before = _tree_files(source)
    moved_bytes = sum(size for size in before.values() if size > 0)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("Cannot create %s: %s", target.parent, exc)
        return {"moved": False, "reason": "permission: the destination cannot be created"}
    try:
        os.rename(source, target)
        log.info("Moved the models folder (rename)")
        return {"moved": True, "bytes": moved_bytes}
    except OSError as rename_exc:
        log.info("Rename failed (%s); copying instead", rename_exc)
    try:
        shutil.copytree(source, target, symlinks=True)
        after = _tree_files(target)
    except (OSError, shutil.Error) as exc:
        log.error("Copy of the models folder failed: %s", exc)
        shutil.rmtree(target, ignore_errors=True)
        return {"moved": False, "reason": "copy failed"}
    if after != before:
        log.error("The copy of the models folder does not match the original; "
                  "the original is kept")
        shutil.rmtree(target, ignore_errors=True)
        return {"moved": False, "reason": "copy failed: the copy did not match"}
    try:
        shutil.rmtree(source)
    except OSError as exc:
        # The copy is complete and verified; leftovers in the old place are
        # only wasted space, and a locked file is the usual reason.
        log.warning("The old models folder could not be fully removed: %s", exc)
        shutil.rmtree(source, ignore_errors=True)
    return {"moved": True, "bytes": moved_bytes}


def _storage_worker(rt: Any, chosen: str, move: bool) -> None:
    from app import bootstrap
    from app.utils import cached_models_size, get_models_root

    ctx = _ctx(rt)
    try:
        old_root = _storage_summary(rt)["path"]
        target = get_models_root(chosen)
        if _same_dir(target, old_root) and chosen:
            bus.emit("storage", {"phase": "done", "path": old_root, "changed": False})
            return
        if chosen and _relation(chosen, old_root) in _RELATION_MESSAGES:
            # Checked when the call arrived; the folders may have changed since.
            bus.emit("storage", {"phase": "error",
                                 "message": _RELATION_MESSAGES[_relation(chosen, old_root)]})
            return
        if chosen and not os.access(chosen, os.W_OK):
            bus.emit("storage", {"phase": "error",
                                 "message": "That folder cannot be written to."})
            return
        old_size = int(cached_models_size(old_root))
        outcome: Dict[str, Any] = {"moved": False, "bytes": 0, "skipped": None, "reason": ""}
        if move and chosen and old_size > 0:
            bus.emit("storage", {"phase": "moving", "done_bytes": 0, "total_bytes": old_size})
            done = threading.Event()
            result: Dict[str, Any] = {}

            def mover() -> None:
                try:
                    result.update(move_hub(str(Path(old_root) / "hub"),
                                           str(Path(chosen) / "hub")))
                except Exception:
                    log.exception("Unexpected error during cache move")
                    result.update({"moved": False, "reason": "copy failed: unexpected error"})
                finally:
                    done.set()

            threading.Thread(target=mover, daemon=True, name="move-storage-cache").start()
            # A rename is instant and a cross-drive copy is minutes; polling the
            # destination is the only progress a copy offers.
            while not done.wait(0.5):
                try:
                    seen = int(cached_models_size(chosen))
                except Exception:  # pragma: no cover - defensive
                    seen = 0
                bus.emit("storage", {"phase": "moving", "done_bytes": min(seen, old_size),
                                     "total_bytes": old_size})
            outcome["moved"] = bool(result.get("moved"))
            outcome["bytes"] = int(result.get("bytes", 0) or 0)
            if not outcome["moved"]:
                outcome["skipped"] = _friendly_reason(str(result.get("reason", "")))
                outcome["reason"] = str(result.get("reason", ""))

        rt.config.update_user_setting("storage", "models_dir", chosen)
        bootstrap._apply_storage_path(chosen)
        left = old_size if (not outcome["moved"] and old_size > 0 and chosen) else 0
        bus.emit("storage", {
            "phase": "done", "changed": True, "path": get_models_root(chosen),
            "is_default": not chosen, "old_root": old_root, "left_bytes": left,
            "moved": outcome["moved"], "moved_bytes": outcome["bytes"],
            "skipped": outcome["skipped"], "reason": outcome["reason"],
        })
    except Exception as exc:
        log.exception("Storage change failed")
        bus.emit("storage", {
            "phase": "error",
            "message": (exc.strerror if isinstance(exc, OSError) and exc.strerror
                        else "The models folder could not be changed. "
                             "The Logs have the details."),
        })
    finally:
        with ctx.lock:
            ctx.storage_busy = False
        _publish(rt)
        _measure_storage(rt)


@method("models.storage.open")
def storage_open(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Show the folder in the platform file manager, creating it first on a
    fresh install so the user is not shown a path-not-found."""
    root = _storage_summary(rt)["path"]
    try:
        Path(root).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("Failed to create storage dir for open: %s", exc)
    try:
        if sys.platform == "win32":
            os.startfile(root)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", root])
        else:
            subprocess.Popen(["xdg-open", root])
    except Exception as exc:
        log.warning("Could not open the models folder: %s", exc)
        raise RpcError("open_failed", "Could not open the folder in the file manager.") from exc
    return {"opened": root}


# ---- Hugging Face token ------------------------------------------------------


def _hf_state(rt: Any) -> Dict[str, Any]:
    token = rt.config.get_setting("huggingface", "token")
    return {"set": bool(token and str(token).strip())}


@method("models.hf_token.get")
def hf_token_get(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Whether a token is stored. The value is never sent to the renderer:
    the Qt field showed it masked, but a masked field still holds it, and a
    credential has no business crossing a channel that is not needed."""
    return _hf_state(rt)


@method("models.hf_token.set")
def hf_token_set(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    from app import bootstrap

    token = need(params, "token", str).strip()
    if len(token) > 512 or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127
                               for ch in token):
        raise RpcError("bad_params", "That token has characters a token cannot "
                       "contain (spaces, line breaks or control characters).",
                       field="token")
    try:
        token.encode("ascii")
    except UnicodeEncodeError:
        raise RpcError("bad_params", "A token uses plain letters and digits only.",
                       field="token") from None
    rt.config.update_user_setting("huggingface", "token", token)
    bootstrap._apply_hf_token(token)
    return _hf_state(rt)


@method("models.hf_token.reset")
def hf_token_reset(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return hf_token_set(rt, {"token": ""})


# ---- startup and the watcher --------------------------------------------------


def apply_startup(rt: Any) -> None:
    """What ``_wire_models`` does after the window exists: push the active
    card's saved inference settings and the global VAD switch to the live
    backend, then start watching load results."""
    try:
        cached = _cached_map()
        active = _active_alias(rt, cached)
        if active and cached.get(active):
            push_inference(rt, _load_settings(rt, active))
        push_vad(rt, bool(rt.config.get_setting("audio", "vad_enabled")))
        start_watcher(rt)
    except Exception as exc:  # pragma: no cover - startup must not fail
        log.warning("Model management startup hook failed: %s", exc)


def start_watcher(rt: Any) -> None:
    ctx = _ctx(rt)
    if ctx.watcher is not None:
        return
    sub = bus.subscribe()

    def run() -> None:
        previous: Optional[str] = None
        try:
            while not ctx.stop.is_set():
                item = sub.get(0.5)
                if item is None or item[0] != "state":
                    continue
                try:
                    new = json.loads(item[1]).get("state")
                except ValueError:
                    continue
                if previous is not None and new != previous:
                    on_state_change(rt, previous, new)
                previous = new
        finally:
            sub.close()

    ctx.watcher = threading.Thread(target=run, daemon=True, name="models-watch")
    ctx.watcher.start()


def stop_watcher(rt: Any) -> None:
    _ctx(rt).stop.set()


#: What a failed load tells the user. The runtime's own exception text stays
#: in the log: it is a download or runtime message, not a sentence for them.
_LOAD_FAILED = (
    "The model could not be loaded. Check that this computer is online if "
    "it still has to be downloaded, then try again. The Logs have the details."
)


def on_state_change(rt: Any, previous: str, new: str) -> None:
    """React to a state transition: remember what is loading, report how a
    load ended, and re-check the disk when the app is idle again (the
    transition Qt refreshes every card on)."""
    ctx = _ctx(rt)
    if new == "model_loading" and previous != "model_loading":
        ctx.load_alias = _configured_alias(rt) or ""
    if previous == "model_loading" and new != "model_loading":
        status = ""
        try:
            status = rt.backend.status()
        except Exception:  # pragma: no cover - defensive
            pass
        outcome = {"ready": "ready", "error": "error"}.get(status, "cancelled")
        with ctx.lock:
            ctx.selecting = None
            if outcome == "ready":
                ctx.snapshot = None
            ctx.last_load = {"alias": ctx.load_alias, "outcome": outcome,
                             "at": time.time()}
            if outcome == "error":
                ctx.last_load["reason"] = _LOAD_FAILED
        event = {"alias": ctx.load_alias, "outcome": outcome}
        if outcome == "error":
            event["reason"] = _LOAD_FAILED
        bus.emit("model_load", event)
    if new == "idle" or previous == "model_loading":
        _publish(rt)
        if previous == "model_loading":
            _measure_storage(rt)
