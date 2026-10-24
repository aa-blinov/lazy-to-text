"""The Transcribe screen: file runs, saving the text, the per-run preset."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict

from app.audio_formats import AUDIO_EXTS, looks_like_audio
from app.server.events import bus
from app.server.rpc import RpcError, method, need

log = logging.getLogger(__name__)

_PROGRESS_S = 1.0


@method("files.formats")
def formats(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """The extensions a drop is allowed to carry, lower case with a dot."""
    return {"extensions": list(AUDIO_EXTS)}


def _ready_backend(rt: Any) -> Any:
    """The backend, or the reason a run cannot start, in the Qt wording."""
    if rt.state_manager is None:
        raise RpcError(
            "no_stack",
            rt.stack_error
            or "Recording stack isn't initialised — try restarting the app.",
        )
    backend = getattr(rt.state_manager, "backend", None)
    if backend is None:
        raise RpcError("no_backend", "Backend unavailable.")
    if not getattr(backend, "health_check", lambda: False)():
        raise RpcError(
            "not_ready",
            "Model isn't ready yet — wait for it to finish loading.",
        )
    if getattr(backend, "transcribe_file", None) is None:
        raise RpcError(
            "unsupported",
            "This backend doesn't support file transcription.",
        )
    return backend


@method("files.transcribe")
def transcribe(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Start a run on a worker thread and answer at once.

    The outcome arrives as ``file.done`` or ``file.failed``, each carrying
    the path, so a result for a file the user has since replaced can be
    told apart and dropped. ``strict`` applies the extension guard that a
    drop has in the Qt view; Browse and an operating-system open name any
    existing file and a non-audio one ends in the decode error instead.
    """
    path = need(params, "path", str)
    if params.get("strict") and not looks_like_audio(path):
        raise RpcError("bad_extension", "That file type is not supported.")
    if not os.path.isfile(path):
        raise RpcError("not_found", "That file is no longer there.")
    backend = _ready_backend(rt)

    done = threading.Event()
    started = time.monotonic()

    def tick() -> None:
        while not done.wait(_PROGRESS_S):
            bus.emit("file.progress", {
                "path": path, "elapsed": time.monotonic() - started,
            })

    def run() -> None:
        try:
            text = backend.transcribe_file(path)
        except Exception as exc:
            # The backend raises instead of flattening a failure into an
            # empty transcript, so the message is what actually went wrong.
            log.warning("transcribe_file failed for %s: %s", path, exc)
            done.set()
            bus.emit("file.failed", {"path": path, "message": str(exc)})
            return
        done.set()
        bus.emit("file.done", {
            "path": path,
            "text": text or "",
            "elapsed": time.monotonic() - started,
        })

    threading.Thread(target=tick, daemon=True, name="transcribe-file-tick").start()
    threading.Thread(target=run, daemon=True, name="transcribe-file").start()
    bus.emit("file.progress", {"path": path, "elapsed": 0.0})
    try:
        size = os.path.getsize(path)
    except OSError:
        size = None
    return {"started": True, "path": path, "size": size}


@method("files.save_text")
def save_text(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    path = need(params, "path", str)
    text = need(params, "text", str)
    if not path.strip():
        raise RpcError("bad_params", "missing parameter: path")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as exc:
        raise RpcError("write_failed", str(exc))
    return {"saved": path}
