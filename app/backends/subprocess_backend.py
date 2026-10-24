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
while it's held, every other thread in the process blocks on any Win32
syscall.  In a single-process design that stalls the hotkey listener,
the recorder and the runtime's own server for as long as the load takes.

By moving the model into a worker process, the loader-lock contention
stays inside *that* process; the runtime keeps serving at full rate.

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
- A send lock serialises ``_send_cmd`` calls so multiple threads
  hitting the backend can't interleave commands and responses.
- Only one outstanding command at a time in practice: transcribe and
  change_model don't overlap thanks to StateManager's queueing.
"""

from __future__ import annotations

from app import privacy_env  # noqa: F401  (ORT telemetry off, before any onnxruntime import)

import logging
import multiprocessing
import queue
import threading
import time
from typing import Any, Callable, Optional

import numpy as np

from app.backends.base import TranscriptionError

from app.backends.subprocess_worker import _worker_main


log = logging.getLogger(__name__)


# Per-command timeout caps.  Most commands return in milliseconds; the
# generous defaults are a safety net for genuinely long ops (model
# load + download from HuggingFace).
_FAST_TIMEOUT = 30.0       # status, current_model, set_progress_callback, …
_LOAD_TIMEOUT = 1800.0     # load(), change_model() — first-time download
_TRANSCRIBE_TIMEOUT = 600.0  # 10 min cap for very long audio files
# The silero VAD is a second model: the first use downloads it.  The
# download is a couple of megabytes, but a slow network makes it a
# long wait, and this command is answered by the worker only once the
# model is in memory.
_VAD_TIMEOUT = 600.0


#: How a worker death reaches every command still waiting for a reply.
_DEATH_REASON = "Subprocess pipe closed unexpectedly"
#: Automatic restarts of a dead worker: at most this many inside the window.
_MAX_AUTO_RESPAWNS = 3
_RESPAWN_WINDOW_S = 120.0
_RESPAWN_INIT_TIMEOUT = 60.0
#: Commands that bring a dead worker back before they are sent.
_RESPAWNING_OPS = frozenset({"load", "change_model"})
#: Commands that have nothing to do on a dead worker (replayed on respawn).
_SILENT_WHEN_DEAD_OPS = frozenset(
    {"cancel_load", "set_vad_enabled", "update_inference_settings"}
)


class _WorkerGone(TranscriptionError):
    """The worker process is gone; its replacement is being started."""

    def __init__(self, op: str) -> None:
        super().__init__(
            "the speech engine stopped unexpectedly and is being restarted"
        )
        self.op = op


def _worker_gone(op: str) -> "_WorkerGone":
    return _WorkerGone(op)



class SubprocessBackend:
    """Drop-in replacement for :class:`RegistryBackend` that runs the
    inference pipeline in a worker process.

    Constructor arguments are forwarded verbatim to the worker's
    ``RegistryBackend(**kwargs)`` so callers don't need to know
    they're crossing a process boundary.
    """

    def __init__(self, **kwargs: Any) -> None:
        from app.model_mapping import canonical_for

        # What a replacement worker is built from. ``model`` follows the
        # last ``change_model`` so a respawn comes back on the model the
        # user was using, not the one the app started with.
        self._init_kwargs: dict = dict(kwargs)
        self._generation = 0
        self._worker_dead = False
        self._respawn_lock = threading.Lock()
        self._respawn_times: "list[float]" = []
        self._recovering = False
        self._event_callback: Optional[Callable[[str], None]] = None
        self._last_inference_settings: Any = None
        self._vad_wanted = False
        self._status_before_death = "stopped"

        # State for the reader thread + command pipeline.
        self._send_lock = threading.Lock()
        # Per-request waiters, keyed by the sequence number the reply will
        # carry.  A single FIFO queue used to hold every response, which
        # only works while replies arrive in the order commands were sent
        # AND no command ever gives up waiting. It does not hold: a
        # command that times out leaves its reply behind, and the next
        # command — a different one, for a different caller — pops that
        # orphan and returns it as its own payload. Correlating by
        # sequence number makes a stale reply undeliverable instead, so
        # it is dropped rather than misfiled.
        self._waiters: "dict[int, queue.Queue]" = {}
        self._waiters_lock = threading.Lock()
        self._next_seq = 0
        self._progress_callback: Optional[
            Callable[[int, int, str], None]
        ] = None
        self._shutdown = False
        # Fast local cache for "which model is currently configured?".
        # The worker knows the same value, but answering it via IPC from the
        # serving thread (model-card clicks) can stall if the child is still
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

        # Spawn the worker and fire the init command - non-blocking; the
        # reader thread sets ``_init_event`` when the worker acks.
        self._start_worker()

    def _start_worker(self) -> None:
        """Spawn a worker process, its reader thread, and send ``init``.

        Used at construction and again by ``_respawn`` when the worker died.
        """
        # Use an explicit ``spawn`` context rather than the global
        # default.  Two reasons:
        #
        # 1. ``spawn`` is the only viable start method on Windows
        #    (fork unavailable) and the safest on macOS — Apple's
        #    CoreFoundation / Cocoa stack deprecated fork-safety,
        #    so a fork from a parent that has initialised those
        #    frameworks hangs deep inside CoreText / CoreServices.
        #
        # The headless runtime is a PyInstaller build on every platform;
        # its bootloader and ``multiprocessing.freeze_support()`` (called in
        # ``app.server.__main__``) start the child, so the spawn needs no
        # help of its own.

        ctx = multiprocessing.get_context("spawn")

        parent_conn, child_conn = ctx.Pipe(duplex=True)
        proc = ctx.Process(
            target=_worker_main,
            args=(child_conn,),
            name="onnx-worker",
            daemon=True,
        )
        proc.start()

        self._generation += 1
        generation = self._generation
        self._parent_conn = parent_conn
        self._proc = proc
        self._init_event = threading.Event()
        self._init_error = None

        self._reader_thread = threading.Thread(
            target=self._read_loop,
            args=(parent_conn, generation),
            name="onnx-worker-reader",
            daemon=True,
        )
        self._reader_thread.start()

        try:
            parent_conn.send(("init", dict(self._init_kwargs)))
        except (BrokenPipeError, OSError) as exc:  # pragma: no cover
            self._init_error = f"init send failed: {exc}"
            self._init_event.set()

    # ------------------------------------------------------------------ IPC

    def _fail_all_waiters(self, reason: str) -> None:
        """Hand *reason* to every command still waiting, then forget them.

        The old code put a single sentinel on the one shared queue, so a
        worker death unblocked exactly one waiter and left the rest to sit
        out their full timeout — up to the transcribe cap — before
        reporting "timed out" for a worker that had already died. And that
        one sentinel stayed on the queue as an entry the next command
        would then pop as its own result.

        Draining the registry instead means every blocked caller learns
        immediately that the worker is gone, and nothing stale is left
        behind to be misread.
        """
        with self._waiters_lock:
            waiters = list(self._waiters.values())
            self._waiters.clear()
        for q in waiters:
            try:
                q.put_nowait(("error", reason))
            except Exception:  # pragma: no cover — defensive
                pass

    def _read_loop(self, conn: Any = None, generation: Optional[int] = None) -> None:
        """Reader thread — splits the pipe stream into progress events
        (dispatched to the user callback), log records (re-emitted
        through the parent's logging), the init ack (consumed
        internally to flip ``_init_event``), and command responses
        (routed to the waiter that owns their sequence number)."""
        if conn is None:
            conn = self._parent_conn
        if generation is None:
            generation = self._generation
        while True:
            try:
                msg = conn.recv()
            except (EOFError, OSError):
                # Worker process exited or the pipe was closed -
                # signal every waiting _send_cmd, not just one.  Also
                # unblock any caller still waiting on init.
                if generation != self._generation:
                    return  # a replacement worker is already running
                died_after_init = self._init_event.is_set() and self._init_error is None
                if not self._init_event.is_set():
                    self._init_error = "Worker pipe closed before init"
                    self._init_event.set()
                self._fail_all_waiters(_DEATH_REASON)
                if died_after_init and not self._shutdown:
                    self._on_worker_death()
                return
            if generation != self._generation:
                return
            if not msg:
                self._fail_all_waiters("Subprocess sent empty message")
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
            elif not self._init_event.is_set():
                # The very first reply is the init ack: we sent
                # ``("init", …)`` untagged at construction, before any
                # ``_send_cmd`` can have allocated a sequence number.
                # Capture it here so callers never see it as the answer
                # to their first command.
                if msg[0] == "error":
                    self._init_error = str(msg[1])
                self._init_event.set()
            else:
                # A tagged command reply: ("resp", seq, kind, payload).
                # Route it to the waiter that owns ``seq``. A reply
                # whose waiter already gave up (its command timed out)
                # has nobody left to receive it, and delivering it to
                # the next caller would be the silent-wrong-answer bug.
                try:
                    _, seq, kind, payload = msg
                except Exception:  # pragma: no cover — defensive
                    log.warning("malformed command reply: %r", msg)
                    continue
                with self._waiters_lock:
                    waiter = self._waiters.pop(int(seq), None)
                if waiter is None:
                    log.debug(
                        "dropping reply for seq %s — no waiter (its "
                        "command already timed out)", seq,
                    )
                    continue
                waiter.put_nowait((kind, payload))

    # ------------------------------------------------- worker death / respawn

    def set_worker_event_callback(
        self, callback: Optional[Callable[[str], None]],
    ) -> None:
        """Be told when the worker dies (``"died"``) and when a replacement
        is up (``"restarted"``), so the interface can publish the new state."""
        self._event_callback = callback

    def _notify(self, what: str) -> None:
        cb = self._event_callback
        if cb is None:
            return
        try:
            cb(what)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("worker event callback raised: %s", exc)

    def worker_alive(self) -> bool:
        return not self._worker_dead

    def _on_worker_death(self) -> None:
        """The worker process is gone: say so, honestly, and start a new one."""
        with self._status_cache_lock:
            if self._worker_dead or self._shutdown:
                return
            self._worker_dead = True
            self._status_before_death = self._status_cache
            self._status_cache = "error"
        with self._provider_cache_lock:
            self._provider_cache = None
        log.error(
            "The speech engine stopped unexpectedly. Restarting it...",
            extra={"user_message": True},
        )
        self._fail_all_waiters(_DEATH_REASON)
        self._notify("died")
        self._start_recovery()

    def _start_recovery(self) -> None:
        with self._respawn_lock:
            if self._recovering or self._shutdown:
                return
            self._recovering = True
        threading.Thread(
            target=self._recover, name="onnx-worker-recover", daemon=True,
        ).start()

    def _recover(self) -> None:
        try:
            wanted = self._status_before_death in ("ready", "loading")
            if not self._respawn(automatic=True):
                return
            if wanted:
                try:
                    self._mark_loading_then_send(("load",))
                except Exception as exc:
                    log.warning("Reloading the model after a restart failed: %s", exc)
        finally:
            self._recovering = False

    def _respawn(self, *, automatic: bool) -> bool:
        """Replace a dead worker. ``False`` when it could not be done.

        Automatic restarts are bounded (a worker that dies as soon as it is
        started must not become a loop); a restart that a command asks for
        is always attempted once.
        """
        with self._respawn_lock:
            if self._shutdown:
                return False
            if not self._worker_dead:
                return True
            now = time.monotonic()
            self._respawn_times = [
                t for t in self._respawn_times if now - t < _RESPAWN_WINDOW_S
            ]
            if automatic and len(self._respawn_times) >= _MAX_AUTO_RESPAWNS:
                log.error(
                    "The speech engine keeps stopping, so it was not restarted "
                    "again. Select the model again, or restart the app.",
                    extra={"user_message": True},
                )
                return False
            self._respawn_times.append(now)
            old_proc, old_conn = self._proc, self._parent_conn
            try:
                if old_proc.is_alive():
                    old_proc.terminate()
                old_proc.join(timeout=2)
            except Exception:  # pragma: no cover - defensive
                pass
            try:
                old_conn.close()
            except Exception:  # pragma: no cover - defensive
                pass
            try:
                self._start_worker()
            except Exception as exc:
                log.error(
                    "The speech engine could not be restarted: %s", exc,
                    extra={"user_message": True},
                )
                return False
            if not self._init_event.wait(timeout=_RESPAWN_INIT_TIMEOUT) \
                    or self._init_error is not None:
                log.error(
                    "The speech engine could not be restarted.",
                    extra={"user_message": True},
                )
                return False
            with self._status_cache_lock:
                self._worker_dead = False
                self._status_cache = "stopped"
            self._replay_settings()
        log.info("The speech engine was restarted.", extra={"user_message": True})
        self._notify("restarted")
        return True

    def _replay_settings(self) -> None:
        """Put the worker-side switches back on a fresh worker."""
        for cmd in (
            ("update_inference_settings", self._last_inference_settings)
            if self._last_inference_settings is not None else None,
            ("set_vad_enabled", True) if self._vad_wanted else None,
        ):
            if cmd is None:
                continue
            try:
                self._send_cmd(cmd, timeout=_VAD_TIMEOUT)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Could not restore %s after a restart: %s", cmd[0], exc)

    def _ensure_worker(self, op: str) -> bool:
        """Before a command: a dead worker is replaced, or the caller is told.

        ``False`` means the command has nothing to do on a dead worker.
        """
        if not self._worker_dead:
            try:
                alive = self._proc.is_alive()
            except Exception:  # pragma: no cover - defensive
                alive = True
            if alive or self._shutdown or not self._init_event.is_set():
                return True
            self._on_worker_death()
        if self._shutdown or threading.current_thread().name == "onnx-worker-recover":
            return True
        if op in _RESPAWNING_OPS:
            # The caller is about to load a model: bring the worker back first.
            if not self._respawn(automatic=False):
                raise RuntimeError("The speech engine is not running.")
            return True
        if op in _SILENT_WHEN_DEAD_OPS:
            return False
        self._start_recovery()
        raise _worker_gone(op)

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
        serving thread should keep that in mind; the autoload path
        deliberately runs on a daemon thread to avoid stalling the UI.

        Raises :class:`RuntimeError` if the worker reports an error
        (or never inits, or the pipe times out).

        Two invariants worth stating, because the obvious version of this
        method gets both wrong:

        - **The wait happens outside ``_send_lock``.** Holding it across
          the blocking ``get`` meant one long command — a file
          transcription, up to its ten-minute cap — locked every other
          caller out of *sending* too, including a Cancel from another thread.
          The lock now covers only the pipe write, which is what actually
          needs serialising.
        - **A timed-out command is abandoned, not left queued.** Its
          sequence number is retired and its late reply is dropped by
          the reader, because there is no caller left to hand it to.
        """
        op = cmd[0]
        if not self._ensure_worker(op):
            return None
        if not self._init_event.is_set():
            if not self._init_event.wait(timeout=timeout):
                raise RuntimeError(
                    f"Subprocess worker failed to init within {timeout}s"
                )
        if self._init_error is not None:
            raise RuntimeError(f"Subprocess init failed: {self._init_error}")

        with self._waiters_lock:
            self._next_seq += 1
            seq = self._next_seq
            inbox: "queue.Queue[tuple]" = queue.Queue()
            self._waiters[seq] = inbox

        # Only the write is serialised. A Connection is not safe against
        # concurrent senders, but nothing about waiting for a reply is.
        with self._send_lock:
            try:
                self._parent_conn.send(("cmd", seq, *cmd))
            except (BrokenPipeError, OSError) as exc:
                with self._waiters_lock:
                    self._waiters.pop(seq, None)
                self._on_worker_death()
                raise _worker_gone(op)

        try:
            kind, payload = inbox.get(timeout=timeout)
        except queue.Empty:
            # Retire the sequence number. The worker may still finish and
            # reply; the reader will find no waiter and drop it.
            with self._waiters_lock:
                self._waiters.pop(seq, None)
            raise RuntimeError(
                f"Subprocess command {op!r} timed out after {timeout}s"
            )
        if kind == "error" and payload == _DEATH_REASON:
            raise _worker_gone(op)
        if kind == "error":
            # A TranscriptionError raised in the worker arrives as text.
            # Rebuild it, so the caller can tell "the model failed" from
            # "the worker broke" and the plumbing prefix never reaches
            # the user.
            marker = "TranscriptionError: "
            if isinstance(payload, str) and payload.startswith(marker):
                raise TranscriptionError(payload[len(marker):])
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
        self._mark_loading_then_send(("load",))

    def _mark_loading_then_send(self, cmd: tuple) -> None:
        """Send a command that starts a load, with ``loading`` already cached.

        ``status()`` is served from a cache filled by the worker's pushes,
        which arrive some tens of milliseconds after the command. A caller
        that polls right after ``change_model`` - the state manager's
        watcher does - read the *previous* model's cached ``ready``, decided
        the new model had loaded, cleared the loading flag, logged
        "Successfully switched" and left a multi-gigabyte download that
        Cancel could no longer reach. The cache is set before the command
        goes out, so the first read already says what is true; the
        worker's own pushes take over from there.
        """
        with self._status_cache_lock:
            previous = self._status_cache
            self._status_cache = "loading"
        try:
            self._send_cmd(cmd, timeout=_FAST_TIMEOUT)
        except Exception:
            with self._status_cache_lock:
                if self._status_cache == "loading":
                    self._status_cache = previous
            raise

    def change_model(
        self,
        model: str,
        compute_type: Optional[str] = None,
    ) -> None:
        # Same rationale as ``load`` — fast handshake only.
        from app.model_mapping import canonical_for

        with self._current_model_cache_lock:
            self._current_model_cache = canonical_for(model)
        self._init_kwargs["model"] = model
        if compute_type is not None:
            self._init_kwargs["compute_type"] = compute_type
        self._mark_loading_then_send(("change_model", model, compute_type))

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
        # The worker's own push says "stopped" some tens of milliseconds
        # later. Until it does the cache still reads "loading", and a
        # caller that asks for the restore of the previous model at once
        # is told a load is in progress and gives up (QA-RUNTIME-F1).
        with self._status_cache_lock:
            if self._status_cache == "loading":
                self._status_cache = "stopped"

    def set_vad_enabled(self, enabled: bool) -> None:
        """Turn the silero VAD on or off in the worker.

        The worker may have to download the VAD model the first time,
        so this gets a generous timeout of its own — the call runs on a
        background thread, never on the UI thread.
        """
        self._vad_wanted = bool(enabled)
        try:
            self._send_cmd(
                ("set_vad_enabled", bool(enabled)),
                timeout=_VAD_TIMEOUT,
            )
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("set_vad_enabled on subprocess raised: %s", exc)

    def update_inference_settings(self, settings: Any) -> None:
        self._last_inference_settings = settings
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
