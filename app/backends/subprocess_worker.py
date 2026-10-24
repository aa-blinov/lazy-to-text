"""Inference worker subprocess entry point.

This module is launched as a child process from
:class:`app.backends.subprocess_backend.SubprocessBackend`.  It hosts a
real :class:`app.backends.registry_backend.RegistryBackend` and
dispatches commands sent over a ``multiprocessing.Pipe`` from the parent
process.

Why run the model in a separate process
---------------------------------------
On Windows ``onnx_asr.load_model`` calls ``LoadLibrary`` for ORT op
kernels (Conv / MatMul / cuDNN / cuBLAS / …).  Each ``LoadLibrary`` for
a not-yet-resident DLL acquires the **process-wide DLL loader-lock**.
While that lock is held, every other thread in the process blocks on any Win32 syscall.  The
visible symptoms in a single-process app are: hotkeys and the runtime's
server stop answering for as long as the load takes.

Pushing the inference pipeline into a worker process means the loader-
lock contention happens in *that* process; the runtime process keeps
serving requests and hotkeys at its normal pace.

Pipe protocol
-------------
Every parent → worker message is a tuple whose first element is the
command name (``"status"``, ``"transcribe"``, …).  The worker replies
with one of:

- ``("ok", payload)``  — command succeeded, payload is the return value
- ``("error", message_string)`` — command raised; the parent re-raises
  as RuntimeError (`SubprocessBackend._send_cmd`)

Out-of-band messages (not in response to a command):

- ``("progress", current_bytes, total_bytes, desc)`` — fired from tqdm
  during a HuggingFace download.  The parent's reader thread routes
  these straight to the user's progress callback.
"""

from __future__ import annotations

from app import privacy_env  # noqa: F401  (ORT telemetry off, before any onnxruntime import)

import logging
import queue
import threading
import time
from typing import Optional, TYPE_CHECKING

# Late-bound at module level so tests can monkey-patch them with
# fakes without touching the real implementations.  ``RegistryBackend``
# imports ``onnx_asr`` indirectly which is heavy; we want the test
# suite to run the dispatch logic without that cost.
try:
    from app.backends.registry_backend import RegistryBackend as _RegistryBackend
except Exception:  # pragma: no cover — defensive: tests still want to import
    _RegistryBackend = None  # type: ignore[assignment]

try:
    from app.backends._progress import set_progress_callback as _set_progress_callback
except Exception:  # pragma: no cover
    def _set_progress_callback(_cb):
        return None


if TYPE_CHECKING:  # pragma: no cover
    from multiprocessing.connection import Connection


def _worker_main(child_conn: "Connection") -> None:
    """Worker process main loop.

    Receives commands from the parent over ``child_conn`` and
    dispatches them to a single :class:`RegistryBackend` instance
    that lives for the lifetime of this worker.

    Returns when the parent closes the pipe (EOFError) or sends
    ``("shutdown_worker",)`` — both are normal exits.

    Two threads write to ``child_conn``:
    1. This main loop (command responses, log records, progress events)
    2. A background ``status-broadcaster`` thread that pushes a
       ``("status_change", new_status)`` message every time the
       inner backend's status changes (``stopped`` → ``loading`` →
       ``ready`` / ``error``).  Push-based status removes the need
       for the parent to ``send("status")`` every 200 ms — a major
       source of IPC contention while a model is loading.

    Both writers go through ``_send_lock`` so multiprocessing
    ``Connection.send`` doesn't get its bytes interleaved.
    """
    log = logging.getLogger("subprocess_worker")
    log.info("Worker process started")

    # Serialise pipe writes between the main command loop and the
    # status-broadcaster thread.  ``Connection.send`` is NOT
    # thread-safe; concurrent sends would corrupt the framing and
    # break pickle reads on the parent side.
    send_lock = threading.Lock()

    def safe_send(msg: tuple) -> None:
        try:
            with send_lock:
                child_conn.send(msg)
        except Exception:  # pragma: no cover — pipe broken
            pass

    # Forward all logging records from this worker process back to the
    # parent over the pipe so users see them in the Logs view.  pythonw
    # has no stdout/stderr — without this, every "Loading ONNX model
    # …" / progress / error message produced inside the worker
    # disappears into the void.
    class _PipeLogHandler(logging.Handler):
        # Tracebacks are rendered here, in the worker, and ride along as
        # extra lines of the same record. They used to be dropped: only
        # ``getMessage()`` was forwarded, so ``log.error(...,
        # exc_info=True)`` and ``log.exception`` reached the Logs view as
        # a single line naming an exception type and nothing else. The
        # Logs view is the only diagnostic surface a user has for a
        # worker that died in a subprocess they cannot attach to, so it
        # was structurally incapable of showing why.
        _traceback_formatter = logging.Formatter(
            "%(levelname)s %(name)s\n%(message)s"
        )

        def emit(self, record: logging.LogRecord) -> None:
            message = record.getMessage()
            if record.exc_info:
                message = (
                    f"{message}\n"
                    + self._traceback_formatter.formatException(record.exc_info)
                )
            safe_send((
                "log",
                record.levelno,
                record.name,
                message,
            ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Drop any default handlers (basicConfig may have attached one
    # writing to stderr on import) so we don't double-log.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(_PipeLogHandler())

    # Forward backend progress events back to the parent over the pipe.
    # tqdm fires this from any thread inside ``onnx_asr.load_model``;
    # the parent's reader thread will dispatch to the user's progress
    # callback.
    def _forward_progress(current: int, total: int, desc: str) -> None:
        safe_send(("progress", int(current), int(total), str(desc)))

    _set_progress_callback(_forward_progress)

    # ``backend`` is shared between the main command loop and the
    # status-broadcaster thread; the GIL guarantees atomic
    # reference-reads, but we still capture it via ``backend_holder``
    # so the broadcaster sees the up-to-date value after ``init``.
    backend_holder: list = [None]
    stop_broadcaster = threading.Event()

    # What the parent was last told. Both writers below read the status and
    # record what they sent under one lock, and the broadcaster compares
    # against *that*, not against its own previous poll. Compared against
    # its own poll, a retry after a failure was invisible: the first
    # attempt left the broadcaster remembering ``error``, the retry's
    # ``loading`` was pushed by the command (which the broadcaster did not
    # count), the retry failed inside one poll interval, and the broadcaster
    # saw ``error`` again, "unchanged" - so the parent, which had been told
    # ``loading`` and nothing after, waited on a load that had ended.
    status_lock = threading.Lock()
    last_pushed: list = [None]

    def _push_status(b) -> None:
        """Send the current status ahead of the reply to a command that
        changes it.

        The broadcaster below only reports *transitions it sees* at a
        100 ms poll. A load that finishes between two polls goes
        ``ready`` -> ``loading`` -> ``ready`` unseen, so the parent, which
        marks itself ``loading`` when it sends the command, would wait for
        a push that never comes. Pushed before the reply, the parent has
        the truth by the time its call returns.
        """
        try:
            with status_lock:
                cur = b.status()
                safe_send(("status_change", cur))
                last_pushed[0] = cur
        except Exception:  # pragma: no cover - defensive
            pass

    def _status_broadcaster() -> None:
        """Push status / provider changes to the parent so it doesn't have to poll.

        Polls the inner backend's ``status()`` and ``active_provider()``
        every 100 ms, sends ``("status_change", new_status)`` /
        ``("provider_change", provider_name | None)`` messages on
        transition only. 100 ms is invisible to the user (typical
        state transitions last 1-10 s) but fast enough that the UI's
        loading pill / engine pill repaint almost immediately when
        the model goes ready.
        """
        last_provider: Optional[str] = None
        provider_seen_once = False
        while not stop_broadcaster.is_set():
            b = backend_holder[0]
            if b is not None:
                with status_lock:
                    try:
                        cur = b.status()
                    except Exception:  # pragma: no cover — defensive
                        cur = None
                    if cur is not None and cur != last_pushed[0]:
                        safe_send(("status_change", cur))
                        last_pushed[0] = cur

                provider_getter = getattr(b, "active_provider", None)
                if callable(provider_getter):
                    try:
                        cur_provider = provider_getter()
                    except Exception as e:  # pragma: no cover — defensive
                        log.warning("active_provider() raised: %s", e)
                        cur_provider = None
                    # Push on every transition (including ready→stopped
                    # which clears the pill back to None) and once at
                    # the start so the parent always has a definitive
                    # answer instead of the default ``None`` cache.
                    if (
                        not provider_seen_once
                        or cur_provider != last_provider
                    ):
                        log.info("Worker pushing provider_change: %s", cur_provider)
                        safe_send(("provider_change", cur_provider))
                        last_provider = cur_provider
                        provider_seen_once = True
            stop_broadcaster.wait(0.1)

    threading.Thread(
        target=_status_broadcaster,
        name="status-broadcaster",
        daemon=True,
    ).start()

    backend = None

    # Transcriptions run on their own thread, one at a time, so the command
    # loop stays free to answer a cancel, a status or a model switch while a
    # long file is being recognised. Run inline, a Cancel of a model load sat
    # behind a twelve-second transcription and the screen stayed on
    # "cancelling" until it finished (QA-JOURNEYS-F5). One thread keeps them
    # serial, as they were.
    jobs: "queue.Queue" = queue.Queue()

    def _job_loop() -> None:
        while True:
            job = jobs.get()
            if job is None:
                return
            job_reply, job_op, job_fn = job
            try:
                job_reply("ok", job_fn())
            except Exception as job_exc:
                log.exception("Worker command %r failed", job_op)
                job_reply("error", f"{type(job_exc).__name__}: {job_exc}")

    threading.Thread(target=_job_loop, name="transcribe-jobs", daemon=True).start()

    while True:
        try:
            cmd = child_conn.recv()
        except (EOFError, OSError):
            log.info("Pipe closed by parent — exiting")
            break
        if not cmd:
            break

        # Commands arrive as ``("cmd", seq, op, *args)`` and go back as
        # ``("resp", seq, kind, payload)``. The sequence number is what
        # lets the parent tell a late reply from a current one — without
        # it, a command that gave up waiting leaves its answer on a
        # shared queue where the next, unrelated command collects it.
        #
        # ``init`` is the one exception: it is sent untagged at
        # construction, before any command can be issued.
        seq = None
        if cmd[0] == "cmd":
            seq = cmd[1]
            cmd = cmd[2:]
            if not cmd:
                safe_send(("resp", seq, "error", "Malformed command"))
                continue

        op = cmd[0]
        args = cmd[1:] if len(cmd) > 1 else ()

        def reply(kind, payload, _seq=seq):
            if _seq is None:
                safe_send((kind, payload))
            else:
                safe_send(("resp", _seq, kind, payload))

        try:
            if op == "init":
                # ``args[0]`` is the kwargs dict for RegistryBackend.
                kwargs = args[0]
                if _RegistryBackend is None:
                    raise RuntimeError(
                        "RegistryBackend unavailable in worker process"
                    )
                backend = _RegistryBackend(**kwargs)
                # Make the new backend visible to the broadcaster
                # thread so it can start pushing status changes.
                backend_holder[0] = backend
                reply("ok", None)
                continue

            if op == "shutdown_worker":
                # No reply. The parent sends this untagged and joins the
                # process instead of waiting for an ack — it has nothing
                # useful to do with one, and blocking on it can stall the
                # caller for the whole command timeout when the child is
                # already half-dead. Answering it would put an untagged
                # 2-tuple on the wire, which the parent's reader would
                # have to recognise and discard.
                stop_broadcaster.set()
                jobs.put(None)
                # Tear down the inner backend cleanly, then exit the loop.
                if backend is not None:
                    try:
                        backend.shutdown()
                    except Exception as exc:  # pragma: no cover
                        log.warning("Inner shutdown raised: %s", exc)
                log.info("Shutdown requested — exiting")
                break

            if backend is None:
                reply("error", "Backend not initialised — send 'init' first")
                continue

            if op == "status":
                reply("ok", backend.status())
            elif op == "health_check":
                reply("ok", backend.health_check())
            elif op == "current_model":
                reply("ok", backend.current_model())
            elif op == "current_language":
                reply("ok", backend.current_language())
            elif op == "load":
                backend.load()
                _push_status(backend)
                reply("ok", None)
            elif op == "transcribe":
                audio, sample_rate = args
                jobs.put((reply, op, lambda b=backend, a=audio, r=sample_rate:
                          b.transcribe(a, sample_rate=r)))
            elif op == "transcribe_file":
                path = args[0]
                jobs.put((reply, op, lambda b=backend, p=path: b.transcribe_file(p)))
            elif op == "change_model":
                model, compute_type = args
                backend.change_model(model, compute_type=compute_type)
                _push_status(backend)
                reply("ok", None)
            elif op == "cancel_load":
                backend.cancel_load()
                _push_status(backend)
                reply("ok", None)
            elif op == "set_vad_enabled":
                backend.set_vad_enabled(bool(args[0]))
                reply("ok", None)
            elif op == "update_inference_settings":
                settings = args[0]
                backend.update_inference_settings(settings)
                reply("ok", None)
            elif op == "shutdown":
                # Non-terminal shutdown: stop the inner backend but keep
                # the worker alive (legacy compatibility — main process
                # always uses ``shutdown_worker`` to actually terminate).
                backend.shutdown()
                reply("ok", None)
            else:
                reply("error", f"Unknown command: {op!r}")
        except Exception as exc:
            log.exception("Worker command %r failed", op)
            reply("error", f"{type(exc).__name__}: {exc}")


# multiprocessing.spawn re-imports this module on Windows when starting
# the worker — avoid running anything at module import time.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(
        "subprocess_worker is not meant to be run directly — "
        "spawn it via SubprocessBackend"
    )
