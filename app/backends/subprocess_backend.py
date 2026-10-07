"""Out-of-process inference backend.

:class:`SubprocessBackend` implements the :class:`TranscriptionBackend`
Protocol but runs the actual :class:`RegistryBackend` in a worker
process spawned via ``multiprocessing.Process``.  Each public method
sends a command tuple over a duplex ``Pipe`` and blocks waiting for
the response.

Why
~~~
On Windows ``onnx_asr.load_model`` calls ``LoadLibrary`` for ORT op
kernels (Conv / MatMul / cuDNN / cuBLAS / …).  ``LoadLibrary`` for a
not-yet-resident DLL takes the **process-wide DLL loader-lock**;
while it's held, every other thread in the process — *including* the
Qt main-thread message pump — blocks on any Win32 syscall.  In a
single-process design that means the title bar can't be dragged, the
mouse wheel doesn't scroll, and Windows eventually marks the window
"(Not responding)".

By moving the model into a worker process, the loader-lock contention
stays inside *that* process; our Qt process keeps painting and
processing OS messages at full rate.

Pipe protocol
~~~~~~~~~~~~~
Every parent → worker message is a tuple ``(op, *args)``.  The worker
replies with one of:

- ``("ok", payload)`` — command succeeded; payload is the return value
- ``("error", str)`` — command raised; this client re-raises as
  RuntimeError on the calling thread

The worker also sends out-of-band ``("progress", current, total, desc)``
messages from tqdm during a HF download.  The parent's reader thread
peels those off the stream and dispatches them to the user-supplied
progress callback before queuing command responses.

Threading model
~~~~~~~~~~~~~~~
- A reader thread (``onnx-worker-reader``) loops on
  ``parent_conn.recv()`` and routes incoming messages.
- A send lock serialises ``_send_cmd`` calls so multiple Qt threads
  hitting the backend can't interleave commands and responses.
- Only one outstanding command at a time — Qt UI is single-writer for
  the backend in practice (transcribe / change_model don't overlap
  thanks to StateManager's queueing).
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing
import os
import queue
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from app.backends.subprocess_worker import _worker_main


log = logging.getLogger(__name__)


@contextlib.contextmanager
def _child_spawn_env() -> "Iterator[None]":
    """Make a spawned child start cleanly inside a py2app bundle.

    Two separate things are wrong in a frozen bundle, and both have to be
    fixed for the child to survive — measured against a shipped release
    zip, not reasoned about:

    1. ``__main__`` is the bundle's ``__boot__.py``. On POSIX,
       ``multiprocessing`` puts ``init_main_from_path`` in the child's
       preparation data whenever ``__main__.__file__`` is set, and the
       child then ``runpy``'s that path — re-running the whole
       application. Symptom: ``Worker pipe closed before init``. Clearing
       ``__main__.__file__`` (and ``__spec__``) for the duration of the
       spawn makes CPython omit the key entirely, so the child only runs
       ``spawn_main``.

    2. A self-contained bundle ships the stdlib zipped as
       ``Resources/lib/python312.zip`` with packages under
       ``Resources/lib/python3.12/``. The app itself is launched by
       ``__boot__.py``, which arranges ``sys.path`` itself; a spawn child
       is not, so it needs ``PYTHONHOME`` / ``PYTHONPATH``. An alias
       build symlinks the venv instead and must NOT be given these —
       measured: pointing them at ``Resources`` there breaks the child's
       stdlib and the worker dies.

    Both are scoped to ``Process.start()``, because ``os.environ`` is
    snapshotted at that moment; leaving them applied would change the
    parent's own import resolution.
    """
    saved_env: dict[str, Optional[str]] = {}
    saved_main: dict[str, Any] = {}
    saved_frozen: Any = "<missing>"
    frozen = sys.platform == "darwin" and getattr(sys, "frozen", False)

    if frozen:
        # 1. ``multiprocessing`` switches to the *frozen executable*
        #    protocol as soon as ``sys.frozen`` is set:
        #
        #        [sys.executable, '--multiprocessing-fork', 'pipe_handle=...']
        #
        #    That flag is an option of a frozen app's own bootloader
        #    (PyInstaller and friends), not of CPython — which answers
        #    "unknown option --multiprocessing-fork" and exits 2. We
        #    point ``ctx.set_executable`` at a real interpreter, so the
        #    child has to be started the ordinary way instead:
        #
        #        [python, '-c', 'from multiprocessing.spawn import spawn_main; …']
        #
        #    Clearing the flag for the duration of ``start()`` selects
        #    that form. Measured: with it left set, every spawn failed
        #    with "unknown option --multiprocessing-fork".
        saved_frozen = getattr(sys, "frozen", "<missing>")
        sys.frozen = False

        # 2. With the flag cleared, ``get_preparation_data`` starts
        #    including ``init_main_from_path`` again — and in a bundle
        #    ``__main__`` is ``__boot__.py``, so the child would
        #    ``runpy`` it and re-run the whole application. Clearing
        #    ``__main__.__file__`` / ``__spec__`` keeps that key out.
        main_module = sys.modules.get("__main__")
        if main_module is not None:
            for attr in ("__file__", "__spec__"):
                saved_main[attr] = getattr(main_module, attr, "<missing>")
                try:
                    setattr(main_module, attr, None)
                except Exception:  # pragma: no cover — defensive
                    saved_main.pop(attr, None)

        # 3. A self-contained bundle ships the stdlib zipped as
        #    ``Resources/lib/python312.zip`` with packages under
        #    ``Resources/lib/python3.12/``. The app itself is launched by
        #    ``__boot__.py``, which arranges ``sys.path`` itself; a spawn
        #    child is not, so it needs ``PYTHONHOME`` / ``PYTHONPATH``.
        #    An alias build symlinks the venv instead and must NOT be
        #    given these — measured: pointing them at ``Resources``
        #    there breaks the child's stdlib and the worker dies.
        exe_dir = Path(sys.executable).resolve().parent
        resources = exe_dir.parent / "Resources"
        lib_dir = resources / "lib"
        stdlib_zip = next(iter(sorted(lib_dir.glob("python3*.zip"))), None)
        if stdlib_zip is not None:
            entries = [
                str(stdlib_zip),
                str(lib_dir / "python3.12"),
                str(lib_dir / "python3.12" / "lib-dynload"),
            ]
            for key, value in (
                ("PYTHONHOME", str(resources)),
                ("PYTHONPATH", os.pathsep.join(entries)),
            ):
                saved_env[key] = os.environ.get(key)
                os.environ[key] = value
            log.info(
                "SubprocessBackend: bundle python env prepared "
                "(PYTHONHOME=%s)",
                resources,
            )
    try:
        yield
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for attr, value in saved_main.items():
            setattr(sys.modules["__main__"], attr, value)
        if saved_frozen != "<missing>":
            sys.frozen = saved_frozen


# Per-command timeout caps.  Most commands return in milliseconds; the
# generous defaults are a safety net for genuinely long ops (model
# load + download from HuggingFace).
_FAST_TIMEOUT = 30.0       # status, current_model, set_progress_callback, …
_LOAD_TIMEOUT = 1800.0     # load(), change_model() — first-time download
_TRANSCRIBE_TIMEOUT = 600.0  # 10 min cap for very long audio files


class SubprocessBackend:
    """Drop-in replacement for :class:`RegistryBackend` that runs the
    inference pipeline in a worker process.

    Constructor arguments are forwarded verbatim to the worker's
    ``RegistryBackend(**kwargs)`` so callers don't need to know
    they're crossing a process boundary.
    """

    def __init__(self, **kwargs: Any) -> None:
        from app.model_mapping import canonical_for

        # Use an explicit ``spawn`` context rather than the global
        # default.  Two reasons:
        #
        # 1. ``spawn`` is the only viable start method on Windows
        #    (fork unavailable) and the safest on macOS — Apple's
        #    CoreFoundation / Cocoa stack deprecated fork-safety,
        #    so a fork from a Qt-initialised parent hangs deep
        #    inside CoreText / CoreServices.
        # 2. py2app .app bundles need a real Python interpreter
        #    for the spawn child.  ``sys.executable`` inside the
        #    bundle is the py2app launcher binary
        #    (``Contents/MacOS/Lazy to Text``), not a Python
        #    interpreter — feeding it multiprocessing's bootstrap
        #    argv produces the cryptic ``Worker pipe closed
        #    before init`` failure.  py2app symlinks the venv's
        #    Python at ``Contents/MacOS/python`` in alias mode;
        #    pointing the spawn context at that path keeps the
        #    rest of multiprocessing intact.  Setting it on the
        #    ``ctx`` instead of the global keeps the override
        #    local to our worker — anything else in-process that
        #    spawns a child stays on the default executable.
        import sys as _sys

        ctx = multiprocessing.get_context("spawn")
        if _sys.platform == "darwin" and getattr(_sys, "frozen", False):
            from pathlib import Path as _Path

            bundle_python = _Path(_sys.executable).parent / "python"
            if bundle_python.exists():
                ctx.set_executable(str(bundle_python))
                log.info(
                    "SubprocessBackend: spawn executable redirected "
                    "to %s (bundle alias mode)", bundle_python,
                )
            else:
                log.warning(
                    "SubprocessBackend: bundle python symlink missing "
                    "at %s — spawn will use sys.executable=%s and "
                    "almost certainly fail",
                    bundle_python, _sys.executable,
                )

        self._parent_conn, child_conn = ctx.Pipe(duplex=True)
        self._proc = ctx.Process(
            target=_worker_main,
            args=(child_conn,),
            name="onnx-worker",
            daemon=True,
        )
        with _child_spawn_env():
            self._proc.start()

        # State for the reader thread + command pipeline.
        self._send_lock = threading.Lock()
        self._response_queue: "queue.Queue[tuple]" = queue.Queue()
        self._progress_callback: Optional[
            Callable[[int, int, str], None]
        ] = None
        self._shutdown = False
        # Fast local cache for "which model is currently configured?".
        # The worker knows the same value, but answering it via IPC from the
        # Qt thread (model-card clicks) can stall if the child is still
        # initialising. Keep the configured canonical in-process instead.
        self._current_model_cache = canonical_for(str(kwargs.get("model", "")))
        self._current_model_cache_lock = threading.Lock()

        # Status cache populated by ``status_change`` push messages
        # from the worker.  Removes the need for the parent to
        # ``_send_cmd(("status",))`` every 200 ms (RecordingController
        # poll) — that IPC round-trip would contend with the worker's
        # tqdm-progress + log forwarding stream and stutter the UI
        # during model loads.
        self._status_cache: str = "stopped"
        self._status_cache_lock = threading.Lock()

        # Active-EP cache populated by ``provider_change`` push
        # messages from the worker — see ``active_provider``. ``None``
        # means either no model is loaded yet or the underlying
        # backend doesn't surface the field.
        self._provider_cache: Optional[str] = None
        self._provider_cache_lock = threading.Lock()

        # Async init: don't block the caller waiting for the worker
        # to come up.  ``__init__`` returns immediately; the reader
        # thread captures the init ack into ``_init_event`` and any
        # subsequent ``_send_cmd`` blocks on that event before
        # sending its own command.  Why: Windows ``spawn`` re-execs
        # Python and re-imports onnx_asr (~3-7 s); doing that
        # synchronously here used to delay ``window.show()`` and the
        # user saw a blank screen for 5-10 s on app startup.
        self._init_event = threading.Event()
        self._init_error: Optional[str] = None

        self._reader_thread = threading.Thread(
            target=self._read_loop,
            name="onnx-worker-reader",
            daemon=True,
        )
        self._reader_thread.start()

        # Fire the init command — non-blocking; the reader thread
        # will set ``_init_event`` when the worker acks.
        try:
            self._parent_conn.send(("init", kwargs))
        except (BrokenPipeError, OSError) as exc:  # pragma: no cover
            self._init_error = f"init send failed: {exc}"
            self._init_event.set()

    # ------------------------------------------------------------------ IPC

    def _read_loop(self) -> None:
        """Reader thread — splits the pipe stream into progress events
        (dispatched to the user callback), log records (re-emitted
        through the parent's logging), the init ack (consumed
        internally to flip ``_init_event``), and command responses
        (queued for ``_send_cmd``)."""
        while True:
            try:
                msg = self._parent_conn.recv()
            except (EOFError, OSError):
                # Worker process exited or the pipe was closed —
                # signal any waiting _send_cmd by enqueuing a sentinel
                # error so it doesn't block forever.  Also unblock
                # any caller still waiting on init.
                if not self._init_event.is_set():
                    self._init_error = "Worker pipe closed before init"
                    self._init_event.set()
                self._response_queue.put(
                    ("error", "Subprocess pipe closed unexpectedly")
                )
                return
            if not msg:
                self._response_queue.put(
                    ("error", "Subprocess sent empty message")
                )
                return

            if msg[0] == "progress":
                cb = self._progress_callback
                if cb is not None:
                    try:
                        cb(int(msg[1]), int(msg[2]), str(msg[3]))
                    except Exception as exc:  # pragma: no cover
                        log.warning("progress callback raised: %s", exc)
            elif msg[0] == "status_change":
                # Worker pushes this on every transition of its inner
                # backend.status() so the parent can answer
                # ``backend.status()`` from cache instead of doing an
                # IPC round-trip.
                try:
                    new_status = str(msg[1])
                except Exception:  # pragma: no cover — defensive
                    continue
                with self._status_cache_lock:
                    self._status_cache = new_status
            elif msg[0] == "provider_change":
                # Worker pushes the EP that ``onnx_asr.load_model`` is
                # actually using as soon as it knows (after the
                # session is built, including any retry-on-CPU
                # fallback). ``None`` is a valid value — model was
                # unloaded or never bound to a session.
                try:
                    new_provider = msg[1]
                except Exception:  # pragma: no cover — defensive
                    continue
                if new_provider is not None:
                    new_provider = str(new_provider)
                with self._provider_cache_lock:
                    self._provider_cache = new_provider
            elif msg[0] == "log":
                # Re-emit worker log records through the parent's
                # logging system so they land in app.log + Logs view.
                # Format: ("log", levelno, logger_name, message)
                try:
                    _, levelno, name, message = msg
                    logging.getLogger(name).log(int(levelno), "%s", message)
                except Exception as exc:  # pragma: no cover
                    log.warning("worker log forward failed: %s", exc)
            else:
                # First command response is the init ack (we sent
                # ``("init", …)`` immediately at construction).  Capture
                # it here so callers don't see it as the response to
                # their first ``_send_cmd``.
                if not self._init_event.is_set():
                    if msg[0] == "error":
                        self._init_error = str(msg[1])
                    self._init_event.set()
                else:
                    self._response_queue.put(msg)

    def wait_for_worker(self, timeout: float = 10.0) -> bool:
        """Block until the worker acks init; ``False`` if it did not.

        Exists so a caller can *choose* between backends before the UI is
        up. Construction is deliberately async — waiting here used to
        delay ``window.show()`` by the cost of a Python + onnx_asr
        import — but a caller that must not ship a half-working backend
        needs a bounded answer, and the ack itself arrives long before
        any model load.

        ``True`` means a live worker, not merely "the event fired": the
        reader thread sets ``_init_event`` on EOF as well as on a clean
        ack, so a worker that died before saying anything would otherwise
        read as success and leave the app with no engine at all.
        """
        if not self._init_event.wait(timeout=timeout):
            return False
        return self._init_error is None

    def _send_cmd(self, cmd: tuple, *, timeout: float = _FAST_TIMEOUT) -> Any:
        """Send a command and block until the worker replies.

        Blocks first on ``_init_event`` if the worker hasn't finished
        initialising yet — Windows ``spawn`` + heavy onnx_asr import
        can take 3-7 s after construction.  Callers running on the
        Qt main thread should keep that in mind; the autoload path
        deliberately runs on a daemon thread to avoid stalling the UI.

        Raises :class:`RuntimeError` if the worker reports an error
        (or never inits, or the pipe times out).  Thread-safe via
        ``_send_lock``.
        """
        if not self._init_event.is_set():
            if not self._init_event.wait(timeout=timeout):
                raise RuntimeError(
                    f"Subprocess worker failed to init within {timeout}s"
                )
        if self._init_error is not None:
            raise RuntimeError(f"Subprocess init failed: {self._init_error}")

        with self._send_lock:
            try:
                self._parent_conn.send(cmd)
            except (BrokenPipeError, OSError) as exc:
                raise RuntimeError(f"Subprocess pipe broken: {exc}")
            try:
                kind, payload = self._response_queue.get(timeout=timeout)
            except queue.Empty:
                raise RuntimeError(
                    f"Subprocess command {cmd[0]!r} timed out after {timeout}s"
                )
            if kind == "error":
                raise RuntimeError(f"Subprocess error: {payload}")
            return payload

    # ------------------------------------------------------------------ TranscriptionBackend Protocol

    def status(self) -> str:
        # Served from the local cache populated by ``status_change``
        # push messages from the worker.  No IPC — RecordingController
        # polls this every 200 ms; an IPC round-trip per poll would
        # serialise against the worker's tqdm + log forwarding and
        # stutter the UI during a model load.
        with self._status_cache_lock:
            return self._status_cache

    def health_check(self) -> bool:
        # Same fast-path as ``status()`` — no IPC.
        return self.status() == "ready"

    def active_provider(self) -> Optional[str]:
        # Served from the local cache populated by ``provider_change``
        # push messages from the worker; no IPC.  ``None`` means
        # either no model is loaded yet (worker hasn't sent the first
        # ``provider_change`` since startup) or the inner backend
        # doesn't expose the field (legacy / fake doubles in tests).
        with self._provider_cache_lock:
            return self._provider_cache

    def current_model(self) -> str:
        with self._current_model_cache_lock:
            return self._current_model_cache

    def current_language(self) -> Optional[str]:
        return self._send_cmd(
            ("current_language",), timeout=_FAST_TIMEOUT,
        )

    def load(self) -> None:
        # ``load`` itself just spawns a daemon thread inside the
        # worker and returns immediately — the timeout only covers
        # the spawn handshake, not the actual model load.
        self._send_cmd(("load",), timeout=_FAST_TIMEOUT)

    def change_model(
        self,
        model: str,
        compute_type: Optional[str] = None,
    ) -> None:
        # Same rationale as ``load`` — fast handshake only.
        from app.model_mapping import canonical_for

        with self._current_model_cache_lock:
            self._current_model_cache = canonical_for(model)
        self._send_cmd(
            ("change_model", model, compute_type),
            timeout=_FAST_TIMEOUT,
        )

    def transcribe(
        self, audio: np.ndarray, sample_rate: int = 16000,
    ) -> Optional[str]:
        return self._send_cmd(
            ("transcribe", audio, sample_rate),
            timeout=_TRANSCRIBE_TIMEOUT,
        )

    def transcribe_file(self, path: str) -> Optional[str]:
        return self._send_cmd(
            ("transcribe_file", path),
            timeout=_TRANSCRIBE_TIMEOUT,
        )

    def cancel_load(self) -> None:
        try:
            self._send_cmd(("cancel_load",), timeout=_FAST_TIMEOUT)
        except Exception as exc:  # pragma: no cover — best-effort
            log.warning("cancel_load on subprocess raised: %s", exc)

    def update_inference_settings(self, settings: Any) -> None:
        try:
            self._send_cmd(
                ("update_inference_settings", settings),
                timeout=_FAST_TIMEOUT,
            )
        except Exception as exc:  # pragma: no cover — defensive
            log.warning(
                "update_inference_settings on subprocess raised: %s", exc,
            )

    def set_progress_callback(
        self,
        callback: Optional[Callable[[int, int, str], None]],
    ) -> None:
        # Worker always forwards via the pipe — we just remember the
        # local callback for the reader thread to invoke.
        self._progress_callback = callback

    def shutdown(self) -> None:
        """Tear down the worker process. Idempotent."""
        if self._shutdown:
            return
        self._shutdown = True
        # Politely ask the worker to drop the inner backend and exit
        # its receive loop, then wait briefly.  Don't block on an IPC
        # response here: app shutdown has nothing useful to do with the
        # ack, and waiting for it can stall the caller for the full
        # command timeout if the child is already half-dead.
        try:
            with self._send_lock:
                self._parent_conn.send(("shutdown_worker",))
        except Exception as exc:  # pragma: no cover — pipe may be dead
            log.debug("shutdown_worker send failed: %s", exc)
        try:
            self._proc.join(timeout=5)
            if self._proc.is_alive():
                log.info("Worker still alive after 5s — terminating")
                self._proc.terminate()
                self._proc.join(timeout=2)
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("Worker process join/terminate raised: %s", exc)
        try:
            self._parent_conn.close()
        except Exception:
            pass
