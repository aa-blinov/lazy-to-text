"""The History screen: browse, delete one (with undo), clear, export."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.server.events import bus
from app.server.rpc import RpcError, method, need

log = logging.getLogger(__name__)

_NUMBER = (int, float)


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
    return {
        "enabled": True,
        "entries": [_entry(e) for e in history.get_entries()],
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
    removed = history.remove_by_timestamp(float(need(params, "id", _NUMBER)))
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
    except (KeyError, TypeError, ValueError) as exc:
        raise RpcError("bad_params", f"not a history entry: {exc}")
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
    path = need(params, "path", str)
    entries = history.get_entries()
    if not entries:
        raise RpcError("empty", "Your history is empty.")
    if not path.strip():
        raise RpcError("bad_params", "missing parameter: path")
    if not history.export_to_text(path):
        raise RpcError("write_failed",
                       "Could not write the history file. Check the "
                       "destination path and permissions.")
    return {"exported": len(entries), "path": path}
