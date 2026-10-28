"""The domain stack, assembled without a window.

Build the config, the inference backend, the ``StateManager`` and the hotkey
listener, then watch them and publish what changes on the event bus. Handlers receive the :class:`Runtime` and use
its attributes directly; nothing here knows about any screen.

Events published (sticky ones are replayed to a new subscriber):

``state``       sticky   ``{"state": "idle|recording|processing|model_loading"}``
``phase``       sticky   ``{"phase": "" | "postprocessing" | "delivering"}`` which part of processing runs
``engine``      sticky   ``{"provider": str|None, "model": str, "alias": str}``
``resources``   sticky   CPU / RAM numbers, every two seconds
``progress``    sticky   model download ``{"current", "total", "desc", "elapsed"}``
``level``                input level 0..1, 20 Hz while recording
``delivery``             ``{"outcome": "pasted|copied|failed", "detail", "text"}``
``history``              history changed
``log``                  one log record
"""

from __future__ import annotations

import collections
import logging
import os
import sys
import threading
import time
from typing import Any, Deque, Dict, Optional

from app import log_redaction, privacy_env  # noqa: F401
from app.server.events import bus

# Before the first record of the process: credentials in an address or a
# header never reach any log sink (file, stderr, Logs view, events).
log_redaction.install()

log = logging.getLogger(__name__)

_POLL_S = 0.2
_LEVEL_S = 0.05
_RESOURCE_S = 2.0
_LOG_RING = 2000
_WORKER_START_TIMEOUT = 10.0

bus.add_sticky("state", "phase", "engine", "resources", "progress")


class _RingHandler(logging.Handler):
    """Keeps recent log records and publishes each one as an event."""

    def __init__(self, ring: Deque[Dict[str, Any]]) -> None:
        super().__init__()
        self._ring = ring
        self._seq = 0
        self.setFormatter(logging.Formatter(datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.format(record)
            self._seq += 1
            item = {
                "id": self._seq,
                # The ring's formatter has no %(asctime)s, so the record never
                # carries one; the time of the event is read off the record.
                "time": time.strftime("%H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "user_message": bool(getattr(record, "user_message", False)),
            }
            self._ring.append(item)
            bus.emit("log", item)
        except Exception:  # pragma: no cover — logging must never raise
            self.handleError(record)


class Runtime:
    def __init__(self, config: Any = None) -> None:
        self.config = config
        self.backend: Any = None
        self.state_manager: Any = None
        self.hotkey_listener: Any = None
        self.history: Any = None
        self.sampler: Any = None
        # The background worker files run in; made by the first file.
        self.file_runner: Any = None
        self.log_ring: Deque[Dict[str, Any]] = collections.deque(maxlen=_LOG_RING)
        self.has_model_on_disk = False
        self.stack_error: Optional[str] = None
        self.instance_handle: Any = None
        self.log_path = ""
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_state: Optional[str] = None
        self._loading_started = 0.0
        self._progress: Dict[str, Any] = {}
        self._ring_handler: Optional[_RingHandler] = None

    # ---- lifecycle ------------------------------------------------------

    def start(self) -> None:
        """Build everything. Safe to call once; failures are recorded.

        A recording stack that cannot be built leaves the server up with
        ``stack_error`` set, so the interface can say what is wrong
        instead of the whole app failing to start.
        """
        from app import bootstrap
        from app.config_manager import ConfigManager

        if self.config is None:
            self.config = ConfigManager()
        root_logger = logging.getLogger()
        self._ring_handler = _RingHandler(self.log_ring)
        root_logger.addHandler(self._ring_handler)

        try:
            self.log_path = bootstrap._install_file_logging(self.config)
        except Exception as exc:
            # No log file is a loss, not a reason to refuse to start: the
            # runtime still logs to stderr and to the Logs view.
            self.log_path = ""
            log.warning("File logging is unavailable: %s", exc)
        storage_root = bootstrap._apply_storage_path(
            self.config.get_setting("storage", "models_dir")
        )
        bootstrap._apply_hf_token(self.config.get_setting("huggingface", "token"))
        log.info("Models root: %s", storage_root)

        try:
            self._build_stack()
        except Exception as exc:
            self.stack_error = str(exc)
            log.warning(
                "Recording stack failed to initialise. The interface runs "
                "without hotkeys and transcription: %s", exc,
                extra={"user_message": True},
            )

        if self.backend is not None:
            self.has_model_on_disk = bool(
                bootstrap._autoload_persisted_model(self.backend, self.config)
            )
            from app.server.handlers import models as _models

            _models.apply_startup(self)

        from app.resource_sampler import ResourceSampler

        self.sampler = ResourceSampler()

        self._spawn(self._poll_loop, "server-poll")
        self._spawn(self._level_loop, "server-level")
        self._spawn(self._resource_loop, "server-resources")

    def _build_stack(self) -> None:
        from app.backends.subprocess_backend import SubprocessBackend
        from app.recording_factory import build_recording_stack

        whisper_cfg = self.config.get_whisper_config()
        kwargs = dict(
            model=whisper_cfg.get("model") or "gigaam-v3-ctc",
            device=str(whisper_cfg.get("device", "auto")),
            compute_type=str(whisper_cfg.get("compute_type", "float16")),
            language=whisper_cfg.get("language") or None,
            beam_size=int(whisper_cfg.get("beam_size", 5)),
        )
        backend = SubprocessBackend(**kwargs)
        if sys.platform == "darwin" and getattr(sys, "frozen", False):
            if not backend.wait_for_worker(_WORKER_START_TIMEOUT):
                from app.backends.registry_backend import RegistryBackend

                log.error(
                    "Inference worker did not come up within %.0fs. Falling "
                    "back to the in-process backend.", _WORKER_START_TIMEOUT,
                )
                try:
                    backend.shutdown()
                except Exception:  # pragma: no cover — defensive
                    pass
                backend = RegistryBackend(**kwargs)

        self.state_manager, self.hotkey_listener, self.backend = (
            build_recording_stack(config_manager=self.config, backend=backend)
        )
        self.history = self.state_manager.history_manager
        self.state_manager.history_update_callback = (
            lambda: bus.emit("history", {})
        )
        self.state_manager.delivery_event_callback = self._on_delivery
        setter = getattr(self.backend, "set_progress_callback", None)
        if callable(setter):
            setter(self._on_progress)
        worker_events = getattr(self.backend, "set_worker_event_callback", None)
        if callable(worker_events):
            worker_events(self._on_worker_event)

    def shutdown(self) -> None:
        self._stop.set()
        if self.config is not None:
            try:
                self.config.flush_pending_writes()
            except Exception:  # pragma: no cover — defensive
                pass
        for target in (
            getattr(self.file_runner, "shutdown", None),
            getattr(self.hotkey_listener, "stop_listening", None),
            getattr(self.state_manager, "shutdown", None),
            getattr(self.backend, "shutdown", None),
            getattr(self.sampler, "stop", None),
        ):
            if callable(target):
                try:
                    target()
                except Exception as exc:  # pragma: no cover — defensive
                    log.warning("shutdown step raised: %s", exc)
        if self._ring_handler is not None:
            logging.getLogger().removeHandler(self._ring_handler)

    def stuck(self) -> bool:
        """A model load or a recording thread that would block interpreter exit."""
        probe = getattr(self.backend, "load_in_flight", None)
        try:
            if callable(probe) and probe():
                return True
        except Exception:  # pragma: no cover — defensive
            pass
        recorder = getattr(self.state_manager, "audio_recorder", None)
        probe = getattr(recorder, "has_stuck_recording_thread", None)
        try:
            return bool(callable(probe) and probe())
        except Exception:  # pragma: no cover — defensive
            return False

    # ---- derived views --------------------------------------------------

    def state(self) -> str:
        if self.state_manager is None:
            return "idle"
        try:
            return self.state_manager.get_current_state()
        except Exception:  # pragma: no cover — defensive
            return "idle"

    def phase(self) -> str:
        getter = getattr(self.state_manager, "get_current_phase", None)
        if not callable(getter):
            return ""
        try:
            return str(getter() or "")
        except Exception:  # pragma: no cover — defensive
            return ""

    def provider(self) -> Optional[str]:
        getter = getattr(self.backend, "active_provider", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:  # pragma: no cover — defensive
            return None

    def engine(self) -> Dict[str, Any]:
        from app.model_mapping import alias_for

        model = ""
        try:
            model = self.backend.current_model() if self.backend else ""
        except Exception:  # pragma: no cover — defensive
            pass
        configured = self.config.get_setting("whisper", "model") if self.config else ""
        alias = configured or (alias_for(model) if model else "")
        return {
            "provider": "Loading…" if self.state() == "model_loading" else self.provider(),
            "model": model,
            "alias": alias,
        }

    # ---- background loops ----------------------------------------------

    def _spawn(self, target, name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _poll_loop(self) -> None:
        last_engine: Optional[str] = None
        last_phase = ""
        while not self._stop.wait(_POLL_S):
            phase = self.phase()
            if phase != last_phase:
                last_phase = phase
                bus.emit("phase", {"phase": phase})
            state = self.state()
            if state != self._last_state:
                self._last_state = state
                if state == "model_loading":
                    self._loading_started = time.monotonic()
                else:
                    self._progress = {}
                    bus.emit("progress", {"current": 0, "total": 0,
                                          "desc": "", "elapsed": 0})
                bus.emit("state", {"state": state})
            if state == "model_loading":
                self._progress["elapsed"] = int(time.monotonic() - self._loading_started)
                bus.emit("progress", {"current": 0, "total": 0, "desc": "",
                                      **self._progress})
            engine = self.engine()
            marker = repr(engine)
            if marker != last_engine:
                last_engine = marker
                bus.emit("engine", engine)

    def _level_loop(self) -> None:
        while not self._stop.wait(_LEVEL_S):
            if self._last_state != "recording":
                continue
            recorder = getattr(self.state_manager, "audio_recorder", None)
            getter = getattr(recorder, "current_input_level", None)
            if not callable(getter):
                continue
            try:
                bus.emit("level", {"level": float(getter())})
            except Exception:  # pragma: no cover — defensive
                continue

    def _resource_loop(self) -> None:
        while True:
            try:
                bus.emit("resources", self.sampler.sample())
            except Exception:  # pragma: no cover — defensive
                pass
            if self._stop.wait(_RESOURCE_S):
                return

    # ---- callbacks from the domain stack (foreign threads) --------------

    def _on_delivery(self, outcome: str, detail: str, text: str, kind: str = "") -> None:
        payload = {"outcome": outcome, "detail": detail, "text": text}
        if kind:
            payload["kind"] = kind
        bus.emit("delivery", payload)

    def _on_worker_event(self, what: str) -> None:
        """The inference worker died or was replaced: publish what is true now."""
        try:
            bus.emit("engine", self.engine())
            from app.server.handlers import models as models_handlers

            models_handlers._publish(self)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("could not publish the engine state after %s: %s", what, exc)

    def _on_progress(self, current: int, total: int, desc: str) -> None:
        self._progress.update(current=int(current), total=int(total), desc=str(desc))
        bus.emit("progress", {"elapsed": int(time.monotonic() - self._loading_started)
                              if self._loading_started else 0,
                              **self._progress})


def pid() -> int:
    return os.getpid()
