"""Startup steps that need no Qt: environment, logging, model autoload.

Shared by the Qt entry point (``app.gui.app``) and the headless server the
Electron interface talks to (``app.server``). They were in ``app.gui.app``
and moved here unchanged, so the server does not import PySide6 to read an
environment variable.
"""

from __future__ import annotations

from app import privacy_env  # noqa: F401  (ORT telemetry off, before any onnxruntime import)

import logging
import os
from typing import Optional

from app.utils import is_cached_for_info, is_model_cached


def _apply_hf_token(configured: Optional[str]) -> bool:
    """Mirror the user's HF token into the live process environment.

    huggingface_hub and pyannote both read ``HF_TOKEN`` (alongside
    ``HUGGING_FACE_HUB_TOKEN`` as a legacy alias). Setting just one
    is enough — huggingface_hub treats them as equivalent.

    Returns True iff a non-empty token was applied.
    """
    if configured and str(configured).strip():
        token = str(configured).strip()
        if not token.isascii() or not token.isprintable() or " " in token:
            # A token is ASCII without spaces. Anything else is a typo or a
            # paste accident, and handing it to the environment (a NUL byte
            # raises there) or to a request header would fail somewhere
            # far from the cause. Treated as "no token", and said so.
            logging.getLogger(__name__).warning(
                "The Hugging Face token has characters a token never has "
                "(spaces, line breaks or non-Latin text); it is not used. "
                "Paste it again.",
                extra={"user_message": True},
            )
            os.environ.pop("HF_TOKEN", None)
            os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)
            return False
        os.environ["HF_TOKEN"] = token
        os.environ["HUGGING_FACE_HUB_TOKEN"] = token
        return True
    os.environ.pop("HF_TOKEN", None)
    os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)
    return False


def _apply_storage_path(configured: Optional[str]) -> str:
    """Resolve and apply the user's chosen models directory to env vars.

    Sets ``HF_HOME`` so ``huggingface_hub`` (used by ``onnx-asr``)
    downloads weights into our managed root instead of the system-
    wide ``~/.cache/huggingface``.  Returns the resolved hub root
    for logging.

    Must run before any ``huggingface_hub`` import: HF reads
    ``HF_HOME`` once at module load.
    """
    from app.utils import get_models_root

    root = get_models_root(configured)
    os.environ["HF_HOME"] = root
    # Suppress the per-download warning about symlinks not being
    # available on Windows.  Symlinks require either admin rights or
    # Developer Mode to be enabled; neither is realistic for a
    # consumer dictation app.  The HF cache works fine without them
    # (just uses more disk for duplicated files), so the warning is
    # noise that clutters our Logs view.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return root


from app.backends.onnx_backend import _WARMUP_ONNX_BYTES


def _do_onnx_asr_preimport() -> None:
    """Import onnx_asr and warm up OnnxRuntime provider DLLs.

    Split out from ``_preload_onnx_asr_async`` so tests can monkeypatch
    just this call without faking ``threading.Thread``.  Allowed to
    raise — the surrounding wrapper in ``_preload_onnx_asr_async``
    catches everything and logs at DEBUG level.

    Why the warmup session matters
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``import onnx_asr`` loads the Python module but does *not* create
    any ONNX InferenceSession.  The first ``InferenceSession(...)`` call
    triggers OnnxRuntime to ``LoadLibrary`` its execution-provider DLLs
    (``DirectML.dll``, ``onnxruntime_providers_shared.dll``, CUDA libs,
    …).  Windows serialises all ``LoadLibrary`` calls through the
    process-wide DLL loader-lock.  While a worker thread holds that
    lock, the Qt main thread — which uses Win32 APIs for window
    management and rendering — cannot move the window, paint, or process
    any system messages.  The user sees "(Not responding)" and a frozen
    title bar for the entire duration of that first session creation.

    Creating a trivial 62-byte dummy session here, on a daemon thread
    *before* ``window.show()``, absorbs the lock contention in the
    background.  All subsequent ``InferenceSession`` calls (real model
    loads) re-use already-loaded DLLs; ``LoadLibrary`` for a resident
    DLL increments a ref-count in <1 ms and never parks the caller on
    the loader-lock.
    """
    import onnx_asr  # noqa: F401 — pulls in onnxruntime

    # Create throwaway InferenceSession(s) to force ORT provider DLLs
    # to load now.  We iterate over every available provider so that
    # CUDA (cublas/cuDNN), DirectML, TensorRT, etc. are each
    # initialised on this daemon thread — not on the Qt main thread
    # where they would hold the Win32 DLL loader-lock and freeze the
    # window.
    try:
        import onnxruntime as _ort
        import numpy as _np

        # Keep missing-CUDA-DLL noise off stderr during warmup.
        _ort.set_default_logger_severity(4)

        _opts = _ort.SessionOptions()
        _opts.log_severity_level = 4  # silence ORT — errors only
        _x = _np.array([0.0], dtype=_np.float32)

        for _provider in _ort.get_available_providers():
            # Always include CPU as the fallback so the session has a
            # usable provider even if the primary one is unavailable.
            # Avoid duplicating CPUExecutionProvider (ORT warns on that).
            _providers = (
                [_provider]
                if _provider == "CPUExecutionProvider"
                else [_provider, "CPUExecutionProvider"]
            )
            try:
                _sess = _ort.InferenceSession(
                    _WARMUP_ONNX_BYTES,
                    sess_options=_opts,
                    providers=_providers,
                )
                _sess.run(None, {"x": _x})
                del _sess
            except Exception:
                pass  # provider DLL missing / not supported — skip
    except Exception:
        pass  # warmup is best-effort; real error path is inside _do_load


def _preload_onnx_asr_async() -> "threading.Thread":
    """Kick off ``import onnx_asr`` + ORT provider warmup on a daemon thread.

    Why this exists: on Windows, the first OnnxRuntime ``InferenceSession``
    creation acquires the Win32 DLL loader-lock while loading provider
    DLLs (DirectML, CUDA, CPU).  That lock is process-wide and serialises
    ALL Win32 DLL operations — including the ones Qt uses internally for
    window management and rendering.  Result: the window cannot be moved
    and is marked "(Not responding)" for the duration of the DLL load.

    Starting this warmup on a daemon thread *before* ``window.show()``
    absorbs the contention in the background.  Real model loads after that
    re-use already-resident DLLs and skip the heavy lock.

    Returns the started ``Thread`` so callers can ``join()`` it when
    needed — ``main()`` joins it just before ``window.show()`` (the join
    is nearly instantaneous because the thread finishes during
    ``build_recording_stack``).
    """
    import logging
    import threading

    log = logging.getLogger(__name__)

    def _worker() -> None:
        # Swallow EVERYTHING — the preimport is a latency optimisation,
        # not part of the model-load contract.  If onnx_asr is missing
        # or broken, the user will discover it when they click a model
        # and the proper error path takes over; we must never crash a
        # background thread to the point that pytest / the user's
        # logs scream.
        try:
            _do_onnx_asr_preimport()
        except Exception as exc:  # noqa: BLE001 — intentionally broad
            log.debug("onnx_asr preimport failed (deferred to load): %s", exc)

    t = threading.Thread(
        target=_worker,
        name="onnx-asr-preimport",
        daemon=True,
    )
    t.start()
    return t


def _autoload_persisted_model(backend, config=None) -> None:
    """Kick off a model load on startup, picking the best
    candidate available on disk.

    Called once at startup, after the recording stack is built
    but before the main window is shown.  Returns immediately —
    the backend's ``load()`` spawns a daemon thread internally
    and the UI paints the loading state from the model card /
    topbar polling machinery.

    Selection order:

    1. If the persisted model from ``config.yaml`` is cached →
       load that.  Honours the user's last explicit pick.
    2. Otherwise pick the first cached model in registry display
       order.  Avoids the "fresh restart, recording does
       nothing" pothole when ``config.yaml`` points at a model
       the user removed (or never downloaded — e.g. the default
       ``parakeet-tdt-v3`` on a Mac that's been working with
       ``gigaam-v3-ctc``).  We log the swap so the Logs view
       explains why a different model came up than what
       Settings currently reads.
    3. Nothing on disk at all → log "skipping auto-load" so
       Settings shows an empty state instead of pretending to
       load something that isn't there.

    Returns whether a model was found on disk. That single fact is
    what the first-run screen is decided on: a user who already has
    weights — including every existing install upgrading to a version
    that has this function at all — must not be shown a setup screen
    for something they finished long ago.
    """
    import logging

    log = logging.getLogger(__name__)
    if backend is None:
        return False

    from app.model_mapping import MODELS, alias_for, get_model

    persisted_name = None
    if config is not None:
        raw = getattr(config, "get_setting", None)
        if callable(raw):
            try:
                candidate = raw("whisper", "model")
            except Exception:  # pragma: no cover — defensive
                candidate = None
            if isinstance(candidate, str) and candidate.strip():
                persisted_name = candidate.strip()

    requested = persisted_name or backend.current_model()
    try:
        alias = requested if persisted_name is not None else alias_for(requested)
        info = get_model(alias)
    except KeyError:
        info = None
        cached = is_model_cached(requested)
    else:
        cached = is_cached_for_info(info)

    if cached:
        display = info.display_name if info is not None else requested
        log.info(
            "Persisted model %s is cached — kicking off background load.",
            display,
        )
        backend.load()
        return True

    # Persisted model isn't cached — look for any cached fallback
    # in registry order so the app still comes up with a working
    # backend instead of an idle "click Download" placeholder.
    for candidate in MODELS:
        if not is_cached_for_info(candidate):
            continue
        log.info(
            "Persisted model %s is not cached — falling back to "
            "cached %s (%s).  Pick a different model in Settings to "
            "override.",
            requested, candidate.display_name, candidate.alias,
        )
        change = getattr(backend, "change_model", None)
        if callable(change):
            try:
                change(candidate.alias)
            except Exception as exc:  # pragma: no cover — defensive
                log.warning("change_model fallback raised: %s", exc)
                return False
        # Persist the fallback into config.yaml too — otherwise
        # ``_get_active_alias`` in the controller still reads the
        # uncached pick from disk and the Models tab paints the
        # wrong card as Active. ``config`` is optional so ad-hoc
        # callers (tests, future scripts) don't have to wire it.
        if config is not None:
            try:
                config.update_user_setting(
                    "whisper", "model", candidate.alias,
                )
                if candidate.compute_type:
                    config.update_user_setting(
                        "whisper", "compute_type",
                        candidate.compute_type,
                    )
            except Exception as exc:  # pragma: no cover — defensive
                log.warning(
                    "Failed to persist fallback model into config: %s",
                    exc,
                )
        backend.load()
        return True

    log.info(
        "Persisted model %s is not cached and no other model is "
        "downloaded — skipping auto-load. Waiting for the user to "
        "pick a model.",
        requested,
    )
    return False


def _should_show_first_run(config, has_model_on_disk: bool) -> bool:
    """The whole first-run decision, in one testable place.

    Two conditions, and both are load-bearing:

    * **A model on disk wins, always.** Otherwise every existing
      install — which has weights, and whose config predates the
      ``onboarding`` section entirely, so it reads ``complete: False``
      out of the defaults — would be shown a setup screen for something
      it finished long ago. That is the "returns a year later" case, and
      it is the one this app would have shipped on its very first
      release of the screen.
    * **Otherwise, the flag.** Someone who hit "Set up later" and never
      downloaded anything is asked again, which is not nagging: there is
      genuinely nothing to dictate with, and the screen is the only
      place that fixes it.
    """
    if has_model_on_disk:
        return False
    if config is None:
        return False
    try:
        return not bool(config.get_setting("onboarding", "complete"))
    except Exception:  # pragma: no cover — defensive
        # A config that cannot be read is not a reason to block the
        # app behind a setup screen the user cannot finish.
        return False


class _NoSensitiveToFile(logging.Filter):
    """Drop records carrying the user's own words from ``app.log``.

    ``state_manager`` tags the "Transcribed: …" line ``sensitive=True``
    because it is the only place the app writes dictated text to a log.
    The Logs view is supposed to show it — seeing what was just
    recognised is the feedback that makes a dictation app trustworthy —
    but a log file is a different kind of store: unbounded, on disk
    until the user goes looking for it, and not cleared by "Clear
    history" the way the history file is.

    The two channels are separate handlers, so the record keeps its
    ``user_message`` flag and still reaches the UI.  Only this handler
    carries the filter.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "sensitive", False)


def _owner_only_handler(base):
    """A file handler class whose log file is created readable by its owner only.

    ``app.log`` carries what was recognised and what failed; the default
    mode of a new file is whatever the umask leaves, usually readable by
    every local user. Rotation renames files and keeps their mode, and the
    fresh ``app.log`` after a rotation goes through ``_open`` again.
    """
    class _OwnerOnly(base):
        def _open(self):
            from app.utils import restrict_to_owner

            stream = super()._open()
            restrict_to_owner(self.baseFilename)
            return stream

    _OwnerOnly.__name__ = f"OwnerOnly{base.__name__}"
    return _OwnerOnly


def _install_file_logging(config=None) -> str:
    """Attach the INFO file handler to the root logger; return its path.

    Called *before* the single-instance gate, deliberately. The gate is the
    earliest point where the app can refuse to start, and a refusal that
    writes nothing anywhere is indistinguishable from the app never having
    been launched: there is no window, ``LSUIElement`` means no Dock icon
    to click a second time, and a Finder double-click gives a non-tty
    process nowhere to print. Measured on this machine — a second instance
    launched while the first held the lock exited 0 and left zero lines in
    ``app.log``.

    The ``logging`` section of ``config.yaml`` drives the level, the file
    name, whether the handler exists at all, and the rotation caps. It
    was declared in ``DEFAULT_CONFIG`` and never read by anything, which
    is why ``app.log`` grew without bound for the life of an install.

    Idempotent: re-running it would otherwise attach a second handler and
    double every subsequent line, so an existing handler for the same path
    is left alone.
    """
    import logging as _logging
    from logging.handlers import RotatingFileHandler

    from app import log_redaction
    from app.utils import get_project_logs_path

    # First, so the very first record of the process is already covered,
    # and for every sink at once: file, stderr, the Logs view, events.
    log_redaction.install()

    section = config.get_section("logging") if config is not None else {}
    if not isinstance(section, dict):
        section = {}

    level_name = str(section.get("level", "INFO") or "INFO").upper()
    level = getattr(_logging, level_name, _logging.INFO)

    _logging.getLogger().setLevel(level)

    file_cfg = section.get("file") or {}
    if not file_cfg.get("enabled", True):
        return ""

    log_path = os.path.join(get_project_logs_path(),
                            str(file_cfg.get("filename", "app.log")))
    root = _logging.getLogger()
    for existing in root.handlers:
        if getattr(existing, "baseFilename", None) == os.path.abspath(log_path):
            return log_path

    rotation = file_cfg.get("rotation") or {}
    if rotation.get("enabled", True):
        handler = _owner_only_handler(RotatingFileHandler)(
            log_path,
            maxBytes=int(rotation.get("max_bytes", 1048576)),
            backupCount=int(rotation.get("backup_count", 5)),
            encoding=str(rotation.get("encoding", "utf-8")),
        )
    else:
        handler = _owner_only_handler(_logging.FileHandler)(
            log_path, encoding=str(rotation.get("encoding", "utf-8"))
        )
    handler.setLevel(level)
    handler.addFilter(_NoSensitiveToFile())
    handler.setFormatter(
        _logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(handler)

    # Bridge ``warnings.warn(...)`` into the logging pipeline so
    # NeMo / PyTorch / pyannote deprecation noise (and our own
    # ``DeprecationWarning`` etc.) lands in the same place as
    # everything else — both ``app.log`` and the Logs view.
    # Without this, those warnings only print to stderr and
    # disappear in a windowed build with no console.
    _logging.captureWarnings(True)
    return log_path
