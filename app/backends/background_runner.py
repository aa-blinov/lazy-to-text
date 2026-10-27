"""Files are transcribed next to the dictation, not in front of it.

The dictation worker handles one transcription at a time, so a long file in it
holds every later dictation until it ends, and its cores are the ones the
interface needs. :class:`BackgroundTranscriber` keeps a *second* worker for
files, started the first time one is dropped, running behind everything else
(``app.background``) and sent away again a little after the last file.

The cost is a second copy of the model while a file runs; the gain is that the
window stays movable, a dictation answers at once, and a file can be cancelled
by ending its process, which is the only way to stop work that sits inside
native inference code.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

#: How long the worker is kept after the last file, for the next one.
IDLE_SECONDS = 90.0
#: How long it may take to load the model before the run falls back.
LOAD_TIMEOUT = 600.0
#: A long recording at background priority is slow; only a dead worker ends it.
JOB_TIMEOUT = 6 * 3600.0


class FileCancelled(Exception):
    """The person cancelled the run."""


class BackgroundUnavailable(RuntimeError):
    """The second worker could not be started or loaded; the caller falls back."""


class BackgroundTranscriber:
    def __init__(
        self,
        main: Any,
        factory: Optional[Callable[..., Any]] = None,
        idle_seconds: float = IDLE_SECONDS,
    ) -> None:
        self._main = main
        self._factory = factory
        self._idle_seconds = idle_seconds
        self._lock = threading.Lock()
        self._worker: Any = None
        self._signature: Any = None
        self._active = 0
        self._epoch = 0
        self._idle_timer: Optional[threading.Timer] = None

    @staticmethod
    def supported(main: Any) -> bool:
        """Only a backend that already runs its model in a worker can be copied."""
        return all(hasattr(main, name) for name in
                   ("_init_kwargs", "_last_inference_settings", "_vad_wanted"))

    # ---- public ---------------------------------------------------------

    def transcribe_file(
        self, path: str, diarize: bool = False, speaker_label: str = "Speaker",
    ) -> Optional[str]:
        epoch = self._epoch
        worker = self._acquire(epoch)
        try:
            return worker.transcribe_file(
                path, diarize=diarize, speaker_label=speaker_label,
                timeout=JOB_TIMEOUT,
            )
        except Exception:
            if self._epoch != epoch:
                raise FileCancelled("cancelled") from None
            raise
        finally:
            self._release()

    def cancel(self) -> bool:
        """End every run in progress. Returns whether there was one."""
        with self._lock:
            busy = self._active > 0
            self._epoch += 1
            worker, self._worker = self._worker, None
            self._signature = None
        if worker is not None:
            worker.abort()
        return busy

    def shutdown(self) -> None:
        self.cancel()

    # ---- the worker's life ---------------------------------------------

    def _wanted_signature(self) -> tuple:
        kwargs = self._main._init_kwargs
        return (
            kwargs.get("model"), kwargs.get("compute_type"), kwargs.get("device"),
            kwargs.get("language"), kwargs.get("beam_size"),
            repr(self._main._last_inference_settings), bool(self._main._vad_wanted),
        )

    def _make(self) -> Any:
        factory = self._factory
        if factory is None:
            from app.backends.subprocess_backend import SubprocessBackend as factory
        return factory(background=True, **dict(self._main._init_kwargs))

    def _prepare(self, worker: Any) -> None:
        """Mirror the dictation worker's settings and start the load. Waits for
        the new process to come up, so it never runs under the lock."""
        settings = self._main._last_inference_settings
        if settings is not None:
            worker.update_inference_settings(settings)
        if self._main._vad_wanted:
            worker.set_vad_enabled(True)
        worker.load()

    def _acquire(self, epoch: int) -> Any:
        retired = None
        fresh = False
        with self._lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            wanted = self._wanted_signature()
            # A model, language or VAD change takes effect for the next file;
            # a run in progress keeps the settings it started with.
            if self._worker is not None and self._signature != wanted and self._active == 0:
                retired, self._worker = self._worker, None
            if self._worker is None:
                try:
                    self._worker = self._make()
                except Exception as exc:
                    self._worker = None
                    raise BackgroundUnavailable(f"{type(exc).__name__}: {exc}") from exc
                self._signature = wanted
                fresh = True
            worker = self._worker
            self._active += 1
        if retired is not None:
            retired.shutdown()
        try:
            if fresh:
                try:
                    self._prepare(worker)
                except Exception as exc:
                    self.cancel()
                    raise BackgroundUnavailable(f"{type(exc).__name__}: {exc}") from exc
            self._wait_ready(worker, epoch)
        except BaseException:
            self._release()
            raise
        return worker

    def _wait_ready(self, worker: Any, epoch: int) -> None:
        deadline = time.monotonic() + LOAD_TIMEOUT
        while True:
            if self._epoch != epoch:
                raise FileCancelled("cancelled")
            status = worker.status()
            if status == "ready":
                return
            if status == "error":
                raise BackgroundUnavailable("the model did not load in the background worker")
            if time.monotonic() > deadline:
                raise BackgroundUnavailable("the background worker took too long to load the model")
            time.sleep(0.1)

    def _release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            if self._active == 0 and self._worker is not None:
                timer = threading.Timer(self._idle_seconds, self._retire_if_idle)
                timer.daemon = True
                self._idle_timer = timer
                timer.start()

    def _retire_if_idle(self) -> None:
        with self._lock:
            if self._active > 0:
                return
            worker, self._worker = self._worker, None
            self._signature = None
            self._idle_timer = None
        if worker is not None:
            try:
                worker.shutdown()
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("Background worker shutdown raised: %s", exc)
