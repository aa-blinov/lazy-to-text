"""The Transcribe screen: file runs, saving the text, the per-run preset."""

from __future__ import annotations

import collections
import logging
import os
import re
import threading
import time
from typing import Any, Dict, Optional

from app.audio_formats import AUDIO_EXTS, looks_like_audio
from app.server.events import bus
from app.server import safe_paths
from app.server.rpc import RpcError, method, need

log = logging.getLogger(__name__)

_PROGRESS_S = 1.0

#: How many file runs the handler remembers. A run that finishes while no
#: window is listening (a reload, a reconnect after sleep) is read back from
#: here with ``files.results``; the oldest run is forgotten first.
_MAX_RESULTS = 12

_results: "collections.OrderedDict[str, Dict[str, Any]]" = collections.OrderedDict()
_results_lock = threading.Lock()
_run_counter = 0

_PLUMBING = re.compile(r"^(?:Subprocess error:\s*)?(?:[A-Za-z_.]*Error:\s*)?")
_ABS_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/](?:[^\s:'\"\\/]+[\\/])+([^\s:'\"\\/]+)")


def explain_failure(exc: BaseException, path: str) -> Dict[str, str]:
    """What went wrong with a file, in words for the person who dropped it.

    The backend's own message carries its plumbing (``Subprocess error:``,
    exception class names, graph node names and build paths from the
    inference runtime). The full text stays in the log; the screen gets a
    sentence and a stable ``code``.
    """
    raw = str(exc) or exc.__class__.__name__
    name = os.path.basename(path) or "the file"
    lowered = raw.lower()
    if "could not read audio" in lowered or "libsndfile" in lowered:
        return {
            "code": "unreadable",
            "message": f"Could not read audio from {name}. The file may be "
                       "damaged, cut short, or not an audio or video file.",
        }
    if "onnxruntime" in lowered or "onnx" in lowered or "reshape" in lowered:
        return {
            "code": "model_failed",
            "message": "The model could not process this audio. A shorter "
                       "file, or another model, may work; the Logs have the "
                       "details.",
        }
    cleaned = _PLUMBING.sub("", raw).strip()
    cleaned = _ABS_PATH.sub(r"\1", cleaned)
    if len(cleaned) > 300:
        cleaned = cleaned[:297] + "..."
    return {"code": "failed", "message": cleaned or "The file could not be transcribed."}


def _remember(path: str, run: int, **fields: Any) -> None:
    with _results_lock:
        current = _results.get(path)
        if current is not None and current["run"] > run:
            return
        entry = {"path": path, "run": run, **fields}
        _results[path] = entry
        _results.move_to_end(path)
        while len(_results) > _MAX_RESULTS:
            _results.popitem(last=False)


def _public(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in entry.items() if k != "run"}


@method("files.results")
def results(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """The remembered runs, newest first: ``{results: [Run]}``.

    ``Run`` is ``{path, status: "running"|"done"|"failed", started_at,
    finished_at?, elapsed, text?, message?, code?}``. A window that was not
    listening when ``file.done`` / ``file.failed`` went out asks here.
    """
    with _results_lock:
        items = [_public(e) for e in reversed(_results.values())]
    return {"results": items}


@method("files.result")
def result(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """The remembered run of one path, or ``{result: null}``."""
    path = need(params, "path", str)
    with _results_lock:
        entry = _results.get(path)
        return {"result": _public(entry) if entry else None}


@method("files.dismiss")
def dismiss(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Forget a run once the screen has shown it."""
    path = need(params, "path", str)
    with _results_lock:
        return {"dismissed": _results.pop(path, None) is not None}


@method("files.formats")
def formats(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """The extensions a drop is allowed to carry, lower case with a dot."""
    return {"extensions": list(AUDIO_EXTS)}


def _runner(rt: Any, backend: Any) -> Any:
    """The second, background worker the files run in, or ``None`` when the
    backend cannot be copied (the in-process fallback) and the run happens on
    the backend itself, as it always did."""
    from app.backends.background_runner import BackgroundTranscriber

    runner = getattr(rt, "file_runner", None)
    if runner is None and BackgroundTranscriber.supported(backend):
        runner = BackgroundTranscriber(backend)
        rt.file_runner = runner
    return runner


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
        from app.server.handlers.core import not_ready_message

        raise RpcError("not_ready", not_ready_message(rt))
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
    told apart and dropped; it is also kept for ``files.results``. ``strict``
    applies the extension guard that a drop has in the Qt view; Browse and
    an operating-system open name any existing file and a non-audio one ends
    in the decode error instead. The path has to be a full path to an
    ordinary readable file.
    """
    global _run_counter
    path = need(params, "path", str)
    if params.get("strict") and not looks_like_audio(path):
        raise RpcError("bad_extension", "That file type is not supported.")
    safe_paths.check_input_path(path)
    diarize = params.get("diarize", False)
    if not isinstance(diarize, bool):
        raise RpcError("bad_params", "diarize must be true or false", field="diarize")
    label = params.get("speaker_label", "Speaker")
    if not isinstance(label, str) or not label.strip() or len(label) > 40:
        raise RpcError("bad_params", "speaker_label must be a short, non-empty string",
                       field="speaker_label")
    if diarize:
        from app import diarization_models

        if not diarization_models.is_cached():
            raise RpcError(
                "diarization_missing",
                "The diarization model is not downloaded. Download it in Models.",
            )
    backend = _ready_backend(rt)

    with _results_lock:
        _run_counter += 1
        run = _run_counter
    done = threading.Event()
    started = time.monotonic()
    started_at = time.time()
    _remember(path, run, status="running", started_at=started_at, elapsed=0.0)

    def tick() -> None:
        while not done.wait(_PROGRESS_S):
            bus.emit("file.progress", {
                "path": path, "elapsed": time.monotonic() - started,
            })

    runner = _runner(rt, backend)

    def work() -> Any:
        if runner is not None:
            from app.backends.background_runner import BackgroundUnavailable

            try:
                return runner.transcribe_file(
                    path, diarize=diarize, speaker_label=label.strip(),
                )
            except BackgroundUnavailable as exc:
                # The second worker could not be had: the file still gets
                # transcribed, in front of the dictation as before.
                log.warning(
                    "The background worker is unavailable (%s); transcribing "
                    "%s in the main one.", exc, os.path.basename(path),
                )
        if diarize:
            return backend.transcribe_file(
                path, diarize=True, speaker_label=label.strip(),
            )
        return backend.transcribe_file(path)

    def run_it() -> None:
        from app.backends.background_runner import FileCancelled

        try:
            text = work()
        except FileCancelled:
            done.set()
            elapsed = time.monotonic() - started
            _remember(path, run, status="cancelled", started_at=started_at,
                      finished_at=time.time(), elapsed=elapsed)
            bus.emit("file.cancelled", {"path": path, "elapsed": elapsed})
            return
        except Exception as exc:
            # The backend raises instead of flattening a failure into an
            # empty transcript, so the message is what actually went wrong.
            log.warning("transcribe_file failed for %s: %s", path, exc)
            done.set()
            why = explain_failure(exc, path)
            elapsed = time.monotonic() - started
            _remember(path, run, status="failed", started_at=started_at,
                      finished_at=time.time(), elapsed=elapsed, **why)
            bus.emit("file.failed", {"path": path, "elapsed": elapsed, **why})
            return
        done.set()
        elapsed = time.monotonic() - started
        _remember(path, run, status="done", started_at=started_at,
                  finished_at=time.time(), elapsed=elapsed, text=text or "")
        bus.emit("file.done", {
            "path": path,
            "text": text or "",
            "elapsed": elapsed,
        })

    threading.Thread(target=tick, daemon=True, name="transcribe-file-tick").start()
    threading.Thread(target=run_it, daemon=True, name="transcribe-file").start()
    bus.emit("file.progress", {"path": path, "elapsed": 0.0})
    try:
        size: Optional[int] = os.path.getsize(path)
    except OSError:
        size = None
    return {"started": True, "path": path, "size": size}


@method("files.cancel")
def cancel(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Stop the run in progress. Only a run in the background worker can be
    stopped: its process is ended, which is the one way to stop inference."""
    runner = getattr(rt, "file_runner", None)
    return {"cancelled": bool(runner.cancel()) if runner is not None else False}


@method("files.save_text")
def save_text(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Write *text* to a path the save dialog returned.

    The path is checked first (``safe_paths.check_output_path``: a full path,
    a text extension, not a link, folder or device, not inside the app's own
    folders or the installation), and an existing file is replaced only with
    ``overwrite: true``. The file is written next to its final name and
    renamed into place, so a failure leaves the previous file as it was.
    """
    overwrite = params.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise RpcError("bad_params", "overwrite must be true or false", field="overwrite")
    target = safe_paths.check_output_path(rt, params.get("path"), overwrite=overwrite)
    text = need(params, "text", str)
    try:
        safe_paths.replace_atomically(
            target,
            lambda tmp: tmp.write_text(text, encoding="utf-8"),
        )
    except OSError as exc:
        raise RpcError("write_failed", safe_paths.os_reason(exc)) from exc
    return {"saved": str(params["path"]).strip()}
