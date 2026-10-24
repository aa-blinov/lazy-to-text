"""The History screen: browse, delete one (with undo), clear, export."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List

from app.server import safe_paths
from app.server.events import bus
from app.server.rpc import RpcError, method, need

log = logging.getLogger(__name__)

_NUMBER = (int, float)

#: Bounds a restored entry has to sit inside. A timestamp outside them cannot
#: be shown (``datetime`` refuses it) and one that is NaN can never be found
#: again by its id, so either would sit in the file as an entry nothing can
#: list or delete.
_MIN_TIMESTAMP = 0.0
_MAX_TIMESTAMP = 4102444800.0  # 2100-01-01
_MAX_TEXT = 200_000
_MAX_DURATION_S = 24 * 3600.0
_MAX_FIELD = 200


def _entry(e: Any) -> Dict[str, Any]:
    from app.model_mapping import alias_for

    return {
        "id": e.timestamp,
        "timestamp": e.timestamp,
        "text": e.text,
        "duration": e.duration,
        "model": e.model,
        "alias": alias_for(e.model),
        "language": e.language,
        "datetime": e.datetime_str,
    }


def _history(rt: Any) -> Any:
    history = getattr(rt, "history", None)
    if history is None:
        raise RpcError("history_disabled", "History is turned off.")
    return history


@method("history.list")
def list_entries(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Every stored entry, newest first.

    ``enabled`` is false when no history store exists (``history.enabled``
    off, or the recording stack failed to build); the screen then shows
    its empty state with no working Clear or Export, as the Qt one does.
    """
    history = getattr(rt, "history", None)
    hotkey = ""
    if rt.config is not None:
        hotkey = str(rt.config.get_setting("hotkey", "start_recording_hotkey") or "")
    if history is None:
        return {"enabled": False, "entries": [], "start_hotkey": hotkey,
                "max_entries": 0}
    entries: List[Dict[str, Any]] = []
    for stored in history.get_entries():
        try:
            entries.append(_entry(stored))
        except Exception as exc:
            # One entry that cannot be shown must not hide all the others.
            log.warning("Skipping a history entry that cannot be shown: %s", exc)
    return {
        "enabled": True,
        "entries": entries,
        "start_hotkey": hotkey,
        "max_entries": history.max_entries,
    }


@method("history.delete")
def delete(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Remove one entry now and return it, so the caller can offer undo.

    Deleted from disk at once rather than after an undo window: a delete
    that waits is a delete that a crash or a quit silently drops, and the
    user's own words would stay in a file they believe they cleaned.
    """
    history = _history(rt)
    ident = float(need(params, "id", _NUMBER))
    if not math.isfinite(ident):
        raise RpcError("bad_params", "id is not a timestamp", field="id")
    removed = history.remove_by_timestamp(ident)
    if removed is None:
        raise RpcError("not_found", "That entry is no longer in the history.")
    bus.emit("history", {})
    return {"deleted": _entry(removed), "total": len(history.get_entries())}


@method("history.restore")
def restore(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Undo a deletion by writing the returned entry back in its place."""
    from app.history_manager import TranscriptionEntry

    history = _history(rt)
    raw = need(params, "entry", dict)
    try:
        entry = TranscriptionEntry(
            timestamp=float(raw["timestamp"]),
            text=str(raw["text"]),
            duration=float(raw.get("duration", 0.0)),
            model=str(raw.get("model", "")),
            language=str(raw.get("language", "auto")),
        )
    except KeyError as exc:
        raise RpcError("bad_params", f"The history entry has no {exc.args[0]}.",
                       field="entry")
    except (TypeError, ValueError, OverflowError):
        # The interpreter's own wording ("could not convert string to float")
        # is not for a screen; the entry as a whole is what is wrong.
        raise RpcError("bad_params", "That is not a valid history entry.",
                       field="entry")
    if not (math.isfinite(entry.timestamp)
            and _MIN_TIMESTAMP < entry.timestamp < _MAX_TIMESTAMP):
        raise RpcError("bad_params", "The entry has no usable date.", field="entry")
    if not (math.isfinite(entry.duration) and 0.0 <= entry.duration <= _MAX_DURATION_S):
        raise RpcError("bad_params", "The entry has no usable duration.", field="entry")
    if not entry.text.strip() or len(entry.text) > _MAX_TEXT:
        raise RpcError("bad_params", "The entry has no text, or too much of it.",
                       field="entry")
    if len(entry.model) > _MAX_FIELD or len(entry.language) > _MAX_FIELD:
        raise RpcError("bad_params", "The entry's model or language is too long.",
                       field="entry")
    if not history.restore_entry(entry):
        raise RpcError("not_restored", "The entry could not be put back.")
    bus.emit("history", {})
    return {"restored": True, "total": len(history.get_entries())}


@method("history.clear")
def clear(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    history = _history(rt)
    count = len(history.get_entries())
    history.clear_history()
    bus.emit("history", {})
    return {"cleared": count}


@method("history.export")
def export(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Write every entry to *path* as readable text.

    The request thread does the write (the server runs one thread per
    request, so the channel is not held); the renderer shows its own busy
    state until this returns.
    """
    history = _history(rt)
    entries = history.get_entries()
    if not entries:
        raise RpcError("empty", "Your history is empty.")
    overwrite = params.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise RpcError("bad_params", "overwrite must be true or false", field="overwrite")
    target = safe_paths.check_output_path(rt, params.get("path"), overwrite=overwrite)

    def write(tmp: Any) -> None:
        if not history.export_to_text(str(tmp)):
            raise OSError("export failed")

    try:
        safe_paths.replace_atomically(target, write)
    except OSError:
        raise RpcError("write_failed",
                       "Could not write the history file. Check the "
                       "destination path and permissions.") from None
    return {"exported": len(entries), "path": str(params["path"]).strip()}
