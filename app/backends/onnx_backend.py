"""Unified ONNX inference backend for every supported ASR model family.

Uses ``onnx-asr`` with ONNX-exported weights from HuggingFace.  One
backend class drives Whisper, GigaAM v3 and Parakeet TDT v3 by
switching a small ``family`` parameter; ONNX Runtime handles
everything below — no NeMo, PyTorch, Lightning, or CTranslate2 in
the dependency tree.

Supported families
------------------
- ``whisper``  — ``onnx-community/whisper-*``, configurable language
- ``gigaam``   — ``istupakov/gigaam-v3-onnx``, Russian only
- ``parakeet`` — ``istupakov/parakeet-tdt-0.6b-v3-onnx``, multilingual

Lifecycle
---------
    stopped ──load()──▶ loading ──ok──▶ ready
                               └──err──▶ error

    ready ──change_model()──▶ loading ──▶ ready / error
    *     ──shutdown()──▶ stopped  (terminal)

Provider selection
------------------
``device='auto'`` (default) is platform-aware: on macOS it stages
``CoreMLExecutionProvider`` (Neural Engine + GPU) ahead of CPU; on
Windows / Linux it leaves the choice to onnx-asr / ORT, which runs the
stock ``onnxruntime`` build (CPU, or whatever provider that build
carries).  ``device='cuda'`` and ``device='coreml'`` are explicit
overrides — both come with a CPU fallback baked into the providers
list, plus a runtime retry on CPU if the accelerator fails at
session-create time. ``device='cpu'`` pins to CPU.
"""

from __future__ import annotations

from app import privacy_env  # noqa: F401  (ORT telemetry off, before any onnxruntime import)

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from app.backends._progress import install_tqdm_progress, set_progress_callback
from app.backends.base import TranscriptionError
from app.inference_settings import InferenceSettings, ParakeetInferenceSettings
from app.utils import materialize_flat_model

log = logging.getLogger(__name__)

# Minimal valid ONNX model: float32[1] -> Identity -> float32[1].
# Generated once with raw protobuf wire encoding; verified with
# ``onnxruntime.InferenceSession(bytes, ...).run(...)``.
# Used as a dummy graph to probe whether an execution provider
# (CUDA, DirectML, etc.) is actually functional without loading
# a real model.
_WARMUP_ONNX_BYTES: bytes = (
    b'\x08\x08:4\n\x10\n\x01x\x12\x01y"\x08Identity'
    b'Z\x0f\n\x01x\x12\n\n\x08\x08\x01\x12\x04\n\x02\x08\x01'
    b'b\x0f\n\x01y\x12\n\n\x08\x08\x01\x12\x04\n\x02\x08\x01'
    b'B\x04\n\x00\x10\x0b'
)

# Cache for the Windows/Linux ``device='auto'`` provider probe so we
# only pay the dummy-session cost once per process.
_AUTO_PROVIDER_CACHE: Optional[list] = None

# 25 s @ 16 kHz.  Whisper / GigaAM / Parakeet ONNX models are trained on
# sequences up to ~30 s; 25 s gives a comfortable margin and keeps chunk
# results coherent for conversational-pace dictation.
_CHUNK_SAMPLES: int = 25 * 16_000

# Models whose graph accepts less than ``_CHUNK_SAMPLES``.  Matched as a
# substring of the model's canonical name, lowercase.  The Vosk Zipformer
# graphs have a fixed attention window and fail with an ONNX ``Reshape``
# error on any input longer than 20.05 s (measured against the real
# ``vosk-model-small-ru``); 15 s leaves room for the silence-seeking cut
# below and for the other Vosk card, which shares the architecture.
_MODEL_CHUNK_SECONDS: dict[str, int] = {"vosk": 15}
# The cut is moved to the quietest spot inside this much audio before
# the nominal end of a chunk, so it lands between words rather than in one.
_CUT_SEARCH_SAMPLES: int = 2 * 16_000
_CUT_FRAME_SAMPLES: int = 1_600
# A chunk that the model rejects is halved and tried again, down to this
# length: a graph limit nobody measured costs speed, not the user's words.
_MIN_RETRY_SAMPLES: int = 4 * 16_000
# Fewer samples than a model's front end can take is not a failed model:
# convolutional encoders reject a buffer shorter than their first window
# with a runtime error nobody should read. Shorter input is padded with
# silence up to this length, so it reaches the model as an ordinary, quiet
# recording.
_MIN_MODEL_SAMPLES: int = 8_000


def _chunk_samples_for(model_name: str) -> int:
    name = (model_name or "").lower()
    for needle, seconds in _MODEL_CHUNK_SECONDS.items():
        if needle in name:
            return min(_CHUNK_SAMPLES, seconds * 16_000)
    return _CHUNK_SAMPLES
# Buffer for the post-load inference probe. One second of silence: long
# enough for a convolutional encoder to run its first window, short
# enough that the probe is not felt as load time.
_PROBE_SAMPLES: int = 16_000

# Which family-specific tweaks apply.  See ``current_language`` and
# ``transcribe`` for how each is honoured.
_FAMILIES = ("whisper", "gigaam", "parakeet", "auto")


def _flat_has_precision(flat: Path, quantization: Optional[str]) -> bool:
    """Does this materialised directory hold the requested precision?

    onnx-asr names the variants ``<stem>.onnx``, ``<stem>.int8.onnx`` and
    ``<stem>.fp16.onnx``.  A repo that was downloaded at one precision has
    only that one on disk, so "some .onnx exists" is not enough to say
    the load will find what it wants.
    """
    if quantization:
        return any(flat.glob(f"*.{quantization}.onnx"))
    return any(
        p for p in flat.glob("*.onnx")
        if ".int8." not in p.name and ".fp16." not in p.name
    )


class OnnxAsrBackend:
    """ONNX Runtime inference for any onnx-asr supported model.

    Parameters
    ----------
    model
        HuggingFace repo id (or short name accepted by onnx-asr) of the
        ONNX-exported weights.
    family
        Which ASR family this is.  Controls language reporting and
        whether Whisper-only ``recognize(language=...)`` is used.
    language
        For Whisper: source language code (``"en"``, ``"ru"``, …) or
        ``"auto"`` / ``None`` for auto-detect.  Ignored for other families.
    device
        ``"auto"`` lets onnx-asr pick a provider; ``"cuda"`` requests
        CUDA with CPU fallback; ``"cpu"`` pins to CPU.
    quantization
        Passed verbatim to ``onnx_asr.load_model(quantization=…)``.
        ``"int8"`` / ``"fp16"`` / ``None`` (default).
    """

    def __init__(
        self,
        model: str,
        family: str = "auto",
        language: Optional[str] = None,
        device: str = "auto",
        quantization: Optional[str] = None,
        load_id: Optional[str] = None,
        prefer_cpu_provider: bool = False,
        auto_language: Optional[str] = None,
    ) -> None:
        if family not in _FAMILIES:
            raise ValueError(
                f"family must be one of {_FAMILIES}, got {family!r}"
            )

        self._lock = threading.Lock()
        self._model_name = model
        # ``load_id`` is what we pass to onnx_asr.load_model; it can
        # differ from ``model`` (the HF canonical we display + cache
        # against) when onnx-asr knows the model under a different
        # name.  Defaults to ``model`` for the common case.
        self._load_id = load_id or model
        self._family = family
        self._language = language
        self._device = device
        self._quantization = quantization
        # Skip the accelerator EP entirely for models known to break
        # ORT's CoreML / CUDA adapters at session-init time.  Set by
        # the registry from ``ModelInfo.prefer_cpu_provider`` — see
        # ``_resolve_providers`` for the full rationale.
        self._prefer_cpu_provider = bool(prefer_cpu_provider)
        # Card-declared source language, used only when the user left
        # the setting on "auto".  See ``_inference_language``.
        self._auto_language = auto_language

        self._model = None
        self._status = "stopped"
        self._load_thread: Optional[threading.Thread] = None
        self._shutdown = False
        # Set to True when the user clicks Cancel during a load.  The
        # worker keeps running (Python cannot safely interrupt a thread
        # blocked on a network read or ONNX init), but its result is
        # discarded at the publish step.  Reset on each fresh ``load()``.
        self._cancel_requested = False
        # A load asked for while a cancelled one is still unwinding; the
        # unwinding thread starts it when it exits.
        self._load_pending = False
        # Pretty-printed name of the ONNX Runtime EP actually used by
        # the loaded model's ``InferenceSession`` (``"CUDA"``,
        # ``"CoreML"``, ``"CPU"``, …) — populated from
        # ``_detect_active_provider`` after a successful ``load_model``
        # so the UI can display the real EP rather than the requested
        # one (which lies after a CPU retry).  ``None`` until first
        # successful load.
        self._active_provider: Optional[str] = None
        self._inference_settings = ParakeetInferenceSettings()
        # The silero VAD, when the user asked for it.  ``None`` means
        # "not loaded" *or* "not wanted" — the two are told apart by
        # ``_vad_enabled``, which is the user's switch.
        self._vad = None
        self._vad_enabled = False

    # ---- public API ---------------------------------------------------------

    def current_model(self) -> str:
        with self._lock:
            return self._model_name

    def current_language(self) -> Optional[str]:
        """What language code to stamp history rows with.

        - ``gigaam``  → always ``"ru"`` (Russian-only model)
        - ``parakeet`` → ``None`` (auto-detect across 25 langs)
        - ``whisper`` → user setting, or ``None`` if ``"auto"``/empty
        - ``auto``    → user setting if set, else None
        """
        if self._family == "gigaam":
            return "ru"
        if self._family == "parakeet":
            return None
        # whisper / auto
        lang = self._language
        if not lang or lang == "auto":
            return None
        return lang

    def _inference_language(self) -> Optional[str]:
        """What source language to stamp on the inference call.

        An explicit user choice always wins. Failing that, a card may
        declare ``auto_language`` — the language to assume when the
        user left the setting on "auto".

        This used to be gated on ``family == "whisper"`` alone, which
        meant an AED model never saw a language at all: Canary came
        back *translating* Russian into English (measured on the Golos
        test split: 125.1% WER, identical with and without an explicit
        ``ru``, because the kwarg was dropped before it reached
        onnx-asr). So the language now rides on the card rather than on
        the family label, and only cards that declare it receive it —
        parakeet-tdt-v3 and the rest keep auto-detect across 25
        languages untouched.
        """
        lang = self._language
        if lang and lang != "auto":
            return lang
        return self._auto_language

    def _language_kwargs(self) -> dict:
        """The ``language=`` kwarg for the loaded model, if any.

        Whisper has always taken one, from the user setting. Anything
        else only gets it when its card says so — see
        ``_inference_language``.
        """
        if self._family != "whisper" and self._auto_language is None:
            return {}
        lang = self._inference_language()
        return {"language": lang} if lang else {}

    def status(self) -> str:
        with self._lock:
            return self._status

    def health_check(self) -> bool:
        return self.status() == "ready"

    def active_provider(self) -> Optional[str]:
        """Pretty-printed name of the EP actually backing the loaded
        model — ``"CUDA"`` / ``"CoreML"`` / ``"CPU"`` / ``"TensorRT"`` /
        ``"DirectML"`` / etc., or ``None`` while the model is unloaded
        / loading / errored.  This is the *real* EP after any retry-
        on-CPU fallback, not the EP we initially requested."""
        with self._lock:
            return self._active_provider

    def load(self) -> None:
        """Begin loading the model in a background thread (idempotent)."""
        with self._lock:
            if self._shutdown:
                return
            if self._status in ("loading", "ready"):
                return
            # A previous load that was cancelled is still running: it is
            # parked inside native ONNX Runtime and cannot be stopped from
            # here. ``_status`` alone was standing in for "is a load
            # happening", and ``cancel_load`` had just reset that flag —
            # so a cancel-then-retry sequence started a second thread
            # beside the first. Both then ran ``load_model``, both
            # published into ``self._model``, and the load gate
            # (``if self._cancel_requested``) no longer separated them
            # because ``load`` clears the flag for the new attempt.
            #
            # The thread itself is the honest signal. Refuse the retry
            # instead of racing it.
            if self._load_thread is not None and self._load_thread.is_alive():
                #
                # The request is not dropped: it is remembered, and the
                # unwinding thread starts the load itself the moment it
                # exits (``_run_load_thread``). Dropping it left the
                # status on "loading" with nobody left to load anything -
                # a Cancel followed by the restore of the previous model
                # ended in "Loading..." for good.
                log.info(
                    "Load requested while a previous (cancelled) load is "
                    "still unwinding inside ONNX Runtime - queued until "
                    "it finishes"
                )
                self._status = "loading"
                self._load_pending = True
                return
            self._status = "loading"
            self._cancel_requested = False
            self._load_pending = False
            target_model = self._model_name

        thread = threading.Thread(
            target=self._run_load_thread,
            args=(target_model,),
            daemon=True,
            name="onnx-asr-load",
        )
        with self._lock:
            self._load_thread = thread
        thread.start()

    def _run_load_thread(self, model_name: str) -> None:
        """Thread body: one load, then the queued one if a request came in."""
        try:
            self._do_load(model_name)
        finally:
            with self._lock:
                follow_up = self._load_pending and not self._shutdown
                self._load_pending = False
                if not follow_up:
                    return
                self._cancel_requested = False
                self._status = "loading"
                target = self._model_name
                thread = threading.Thread(
                    target=self._run_load_thread,
                    args=(target,),
                    daemon=True,
                    name="onnx-asr-load",
                )
                self._load_thread = thread
            thread.start()

    def cancel_load(self) -> None:
        """Abandon an in-flight load, flipping status back to ``stopped``.

        The load thread is *not* joined and cannot be — it is inside
        native code that does not take our flag. ``load`` refuses to
        start another one until this one has actually exited, so
        "cancelled" means "its result will be discarded", not "it is gone".
        """
        with self._lock:
            if self._shutdown:
                return
            if self._status != "loading":
                return
            log.info("OnnxAsr load cancelled by user")
            self._cancel_requested = True
            self._load_pending = False
            self._model = None
            self._status = "stopped"
            self._active_provider = None

    def change_model(
        self,
        model: str,
        compute_type: Optional[str] = None,  # API parity, ignored
        load_id: Optional[str] = None,
        prefer_cpu_provider: Optional[bool] = None,
        auto_language: Optional[str] = None,
    ) -> None:
        """Switch to a different ONNX model. Triggers a background reload.

        ``load_id`` mirrors the constructor knob — pass an explicit
        loader identifier when the new model's onnx-asr id differs
        from its HF canonical (T-One, GigaAM e2e, NeMo short names).
        Defaults to ``model``.

        ``prefer_cpu_provider=None`` means "leave the existing flag
        as-is" — the in-family swap path in ``RegistryBackend`` keeps
        the same ``ModelInfo.prefer_cpu_provider`` for both old and
        new model anyway (Whisper-base → Whisper-turbo: both False;
        GigaAM CTC → GigaAM RNN-T: both True), so unspecified is
        safe.  Pass an explicit value when crossing the boundary.
        """
        del compute_type
        requested_load_id = load_id or model
        with self._lock:
            if self._shutdown:
                return
            if (
                model == self._model_name
                and requested_load_id == self._load_id
                and self._status == "ready"
            ):
                return
            self._model_name = model
            self._load_id = requested_load_id
            if prefer_cpu_provider is not None:
                self._prefer_cpu_provider = bool(prefer_cpu_provider)
            # The card being switched to owns the auto language, so
            # Whisper-base's "ru" does not outlive a switch to
            # Whisper-turbo (which stays on auto-detect on purpose).
            if auto_language is not None:
                self._auto_language = auto_language
            self._model = None
            self._status = "stopped"
            self._active_provider = None
        self.load()

    def set_vad_enabled(self, enabled: bool) -> None:
        """Turn the silero VAD on or off for the next transcription.

        The VAD is a second ONNX model, and on the first use it is
        downloaded (about 1-2 MB, into the app's own hub cache).  That
        happens here, not inside ``transcribe``, so the download is
        never part of a dictation: the caller pushes this on a
        background thread and the user keeps typing.

        A failure to load is not fatal. The feature stays off and the
        reason is in the log — a dictation that works without the VAD
        beats no dictation.
        """
        enabled = bool(enabled)
        with self._lock:
            self._vad_enabled = enabled
            if not enabled:
                self._vad = None
        if enabled:
            self._ensure_vad()

    def _ensure_vad(self) -> None:
        """Load the silero VAD, once.  Never raises."""
        with self._lock:
            if self._vad is not None or not self._vad_enabled:
                return
        try:
            import onnx_asr  # type: ignore[import]

            log.info("Loading the silero VAD (first use downloads it)")
            vad = onnx_asr.load_vad("silero")
        except Exception as exc:
            log.warning("Could not load the silero VAD: %s", exc, exc_info=True)
            return
        with self._lock:
            self._vad = vad
        log.info("silero VAD ready")

    def update_inference_settings(self, settings) -> None:
        """Apply a new settings bundle.  Effect is per-call: the next
        ``transcribe`` reads ``self._inference_settings``.  No reload.

        Accepts either ``InferenceSettings`` (Whisper card) or
        ``ParakeetInferenceSettings`` (Parakeet card).  When the
        bundle carries a ``language`` field (Whisper), update the
        live ``_language`` so the next ``transcribe`` honours the
        user's choice without an app restart — this is what wires the
        Whisper inference panel to the running model.
        """
        with self._lock:
            self._inference_settings = settings
            # Whisper's panel sends an InferenceSettings with a
            # ``language`` attribute.  Apply it live so the next
            # transcribe call passes the new value.  Other families
            # (gigaam / parakeet) ignore self._language anyway, so
            # writing it here is harmless even if the user pushed a
            # cross-shape settings object by accident.
            new_language = getattr(settings, "language", None)
            if isinstance(settings, InferenceSettings):
                # ``InferenceSettings.language`` may be ``None`` (auto)
                # or an explicit string — either way it is the new
                # source of truth.  Don't read ``getattr`` here so a
                # future field with the same name on an unrelated
                # object can't silently overwrite our state.
                self._language = new_language

    def transcribe(
        self, audio: np.ndarray, sample_rate: int = 16_000
    ) -> Optional[str]:
        """Transcribe mono/stereo ``float32`` audio.

        Audio longer than ``_CHUNK_SAMPLES`` is split into 25 s chunks
        and the results are joined with a space.  Empty chunks (model
        returned None / empty) are skipped.
        """
        with self._lock:
            if self._shutdown:
                return None
            if self._status != "ready" or self._model is None:
                log.warning(
                    "transcribe() called but backend status is %r",
                    self._status,
                )
                return None
            model = self._model
            settings = self._inference_settings

        try:
            buf = np.asarray(audio, dtype=np.float32)
            if buf.ndim > 1:
                buf = buf.mean(axis=-1)
            if sample_rate != 16_000:
                buf = _resample(buf, sample_rate, 16_000)

            recognise_model = model
            vad = self._vad if self._vad_enabled else None
            if vad is not None:
                # ``with_vad`` returns an adapter that recognises the
                # speech segments and skips the rest.  Its result shape
                # is different — a stream of segments, not one text —
                # and ``_transcribe_chunk`` reads both.
                wrap = getattr(model, "with_vad", None)
                if callable(wrap):
                    recognise_model = wrap(vad)
                else:
                    log.warning(
                        "This model has no VAD adapter — recording without it"
                    )
                    vad = None
            if getattr(settings, "timestamps", False):
                # ``with_timestamps`` returns a wrapper that yields
                # word-level offsets.  No-op if the model doesn't have
                # the method (defensive for fakes / older onnx-asr).
                wrap = getattr(model, "with_timestamps", None)
                if callable(wrap):
                    recognise_model = wrap()

            kwargs: dict = self._language_kwargs()

            return _transcribe_chunked(
                recognise_model, buf, kwargs,
                _chunk_samples_for(self._model_name),
            )
        except TranscriptionError:
            raise
        except Exception as exc:
            log.error(
                "OnnxAsr transcription failed: %s", exc, exc_info=True
            )
            raise TranscriptionError(
                "The speech model failed while transcribing this recording"
            ) from exc

    def transcribe_file(
        self, path: str, diarize: bool = False, speaker_label: str = "Speaker",
    ) -> Optional[str]:
        """Transcribe an audio file from disk.

        With ``diarize`` the recording is first split by speaker and each
        speaker turn is transcribed on its own, giving ``"<label> 1: ..."``
        lines; a recording with a single speaker comes back as plain text.
        See :func:`_transcribe_by_speaker`.

        Decodes the file via :func:`_decode_audio_file` (soundfile for
        WAV / FLAC / OGG / OPUS / AIFF — fast in-process; ffmpeg
        subprocess for everything else: MP3 / M4A / AAC / WMA / WebM
        / MOV …) and feeds the resulting numpy array to
        ``model.recognize``.

        For Whisper family the user-selected language is forwarded
        (same as the ``transcribe`` array path).  Timestamps are
        intentionally not applied here — the file path produces a
        paste-ready transcript and a side panel for word offsets
        doesn't exist yet.

        Returns ``None`` only when the backend is not ready or the model
        genuinely heard nothing.  Inference failures raise
        :class:`~app.backends.base.TranscriptionError` instead of
        flattening into ``None``, so a broken run cannot be reported to
        the user as silence.

        The decoded audio goes through the same 25 s chunking the
        streaming path uses — see :func:`_transcribe_chunked`.
        """
        with self._lock:
            if self._shutdown:
                return None
            if self._status != "ready" or self._model is None:
                log.warning(
                    "transcribe_file() called but backend status is %r",
                    self._status,
                )
                return None
            model = self._model

        audio = _decode_audio_file(path)
        if audio is None:
            raise TranscriptionError(
                f"Could not read audio from {os.path.basename(path)} — "
                f"neither libsndfile nor ffmpeg could decode it"
            )

        kwargs = self._language_kwargs()
        chunk = _chunk_samples_for(self._model_name)

        try:
            if diarize:
                text = _transcribe_by_speaker(
                    model, audio, kwargs, chunk, speaker_label,
                )
                if text is not None:
                    return text
            return _transcribe_chunked(model, audio, kwargs, chunk)
        except TranscriptionError:
            raise
        except Exception as exc:
            log.error(
                "OnnxAsr transcribe_file failed for %s: %s",
                path, exc, exc_info=True,
            )
            raise TranscriptionError(
                f"The speech model failed while transcribing {os.path.basename(path)}"
            ) from exc

    def shutdown(self) -> None:
        """Release resources; move to ``stopped`` (terminal). Idempotent."""
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._model = None
            self._status = "stopped"
            self._active_provider = None

    def load_in_flight(self) -> bool:
        """True while a load thread started earlier is still running.

        ``shutdown`` deliberately does not join it — Python cannot
        interrupt a thread parked inside ONNX Runtime, so joining would
        turn a fast exit into an unbounded wait. But the consequence
        needs to be *visible*: a daemon thread inside native ORT keeps
        the GIL, so the interpreter cannot finalize and the process
        cannot die until that call returns.

        Measured on this machine: the app logged its shutdown, then a
        model thread raised from ORT over a minute later — proof the
        process outlived its own quit. With ``LSUIElement`` that window
        has no window, no Dock icon and (before the logging pipeline
        moved above the single-instance gate) no log line, so every
        relaunch in that window is silently refused by the
        single-instance lock and reads as "the app won't start".

        The exit path reads this to decide whether it has to stop
        waiting for the interpreter.
        """
        with self._lock:
            thread = self._load_thread
        return bool(thread is not None and thread.is_alive())

    @staticmethod
    def set_progress_callback(
        callback: Optional[Callable[[int, int, str], None]],
    ) -> None:
        """Register the UI's HF download progress callback."""
        set_progress_callback(callback)

    # ---- internal -----------------------------------------------------------

    def _build_load_kwargs(self, providers: Optional[list[str]]) -> dict:
        kwargs: dict = {}
        if self._quantization is not None:
            kwargs["quantization"] = self._quantization
        if providers is not None:
            kwargs["providers"] = providers
        # The background worker keeps to its share of the cores; the normal
        # one passes nothing and the library chooses, as it always did.
        from app import background

        options = background.session_options()
        if options is not None:
            kwargs["sess_options"] = options
        # Hand onnx-asr a real directory when we can build one. It
        # resolves a model's external weights by the plain relative name
        # baked into the .onnx file, and huggingface_hub's hub cache
        # stores each of those as a *separate symlink* into blobs/ — so
        # the name resolves against blobs/, where no such file exists.
        # ORT 1.30 refuses that outright ("External data path escapes
        # model directory") and the model fails to load at all.
        # ``materialize_flat_model`` exposes the same bytes as real
        # sibling files, at no extra disk cost.
        #
        # TRAP: passing ``path`` *seals* the search — onnx-asr looks only
        # inside that directory and will not fetch anything else into
        # it. The hub cache holds whichever precision was downloaded
        # (``...int8.onnx`` or the full-precision ``....onnx``), so
        # handing over a directory that lacks the requested one turns a
        # precision switch in the card into "File not found in path".
        # Hence the match check: no matching file means no ``path``, and
        # onnx-asr downloads it the way it always did.
        flat = materialize_flat_model(self._model_name)
        if flat is not None and _flat_has_precision(flat, self._quantization):
            kwargs["path"] = flat
        return kwargs

    def _resolve_providers(self) -> Optional[list]:
        """Map ``self._device`` to an ONNX Runtime providers list.

        Returns a list that ``onnx_asr.load_model`` accepts directly
        (``Sequence[str | tuple[str, dict]]``).  CPU is appended as a
        fallback after every accelerator entry so ORT can still build
        the session if the primary provider's session-create fails
        (driver missing, unsupported op for this model, etc.).
        Returning ``None`` lets onnx-asr / ORT pick from whatever is
        registered in the installed ``onnxruntime`` wheel.

        ``prefer_cpu_provider`` short-circuits the accelerator branches
        for models we know will fail mid-compilation:  GigaAM v3 CTC
        and RNN-T burn ~75 s in ``MLModel.compileModelAtURL`` before
        ORT raises ``HandleNegativeAxis … axis 2 is not in valid
        range`` and the retry-on-CPU path kicks in.  The wait is the
        same on Windows + CUDA for the same models (CUDA EP also
        rejects the CTC op).  Skipping straight to CPU saves the user
        a 75-second freeze on every model load — same eventual
        outcome, no wasted compilation.  Honoured for ``auto``,
        ``cuda`` and ``coreml`` selections;  an explicit ``cpu`` is
        already CPU.
        """
        if self._prefer_cpu_provider and self._device != "cpu":
            return ["CPUExecutionProvider"]
        if self._device == "cuda":
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if self._device == "coreml":
            return [_coreml_provider_entry(), "CPUExecutionProvider"]
        if self._device == "cpu":
            return ["CPUExecutionProvider"]
        # ``auto``: prefer CoreML on Apple Silicon (it is the only
        # accelerator path that actually exercises the Neural Engine
        # / GPU on macOS); on Windows / Linux let ORT pick — it will
        # use CUDA if ``onnxruntime-gpu`` is installed and a working
        # NVIDIA driver is present, otherwise CPU.
        if sys.platform == "darwin":
            return [_coreml_provider_entry(), "CPUExecutionProvider"]
        return _resolve_auto_providers_non_darwin()


    def _probe_inference(self, model, model_name: str) -> Optional[str]:
        """Run one short buffer through ``model`` so a broken graph fails
        here rather than during the user's first dictation.

        Returns ``None`` when the model ran (an empty transcript is a
        pass — the buffer is silence, silence recognising as silence is
        the correct answer), or a one-line reason when it raised.

        Deliberately silent audio and deliberately short: the point is to
        reach the first ``run()``, not to measure anything. Any exception
        is caught and returned rather than raised, because the caller's
        response to failure is a reload on CPU, not a crash.
        """
        try:
            buf = np.zeros(_PROBE_SAMPLES, dtype=np.float32)
            kwargs = self._language_kwargs()
            result = model.recognize(buf, **kwargs)
            # Reading the text is part of the exercise: a lazy property
            # that materialises on access would otherwise defer the
            # failure past this check.
            if result is not None and not isinstance(result, str):
                getattr(result, "text", None)
            return None
        except Exception as exc:
            log.info(
                "Inference probe for %s failed: %s", model_name, exc,
                exc_info=True,
            )
            return f"{type(exc).__name__}: {exc}"

    def _do_load(self, model_name: str) -> None:
        install_tqdm_progress()

        log.info("Importing onnx_asr…")
        try:
            import onnx_asr  # type: ignore[import]
        except ImportError as exc:
            extras = (
                "[gpu,hub]" if sys.platform == "win32" else "[cpu,hub]"
            )
            log.error(
                "onnx-asr is not installed: %s\n"
                "Install it with:  pip install \"onnx-asr%s\"",
                exc, extras,
            )
            with self._lock:
                if not self._shutdown and self._model_name == model_name:
                    self._status = "error"
            return

        # Snapshot everything this thread needs, under the lock, before
        # entering the long native call. ``load()`` hands us
        # ``model_name`` already snapshotted; ``_resolve_providers``,
        # ``_load_id`` and ``_build_load_kwargs`` all read ``self`` live,
        # so a settings change landing mid-load made this thread load a
        # *different* set of knobs than the one it was started for — and
        # then throw the result away at the name check.
        with self._lock:
            providers = self._resolve_providers()
            load_id = self._load_id
            quantization = self._quantization
            family = self._family
            load_kwargs = self._build_load_kwargs(providers)
            # The CPU retry further down needs its own kwargs, built from
            # the same snapshot rather than from whatever ``self`` holds
            # by the time the accelerator attempt has already failed.
            cpu_kwargs = self._build_load_kwargs(["CPUExecutionProvider"])
        log.info(
            "Loading ONNX model %s (load_id=%s, family=%s, providers=%s, quantization=%s)…",
            model_name, load_id, family, providers, quantization,
        )
        forced_provider: Optional[str] = None
        if providers == ["CPUExecutionProvider"]:
            forced_provider = "CPU"
        # Computed before the try, because the inference probe below reads
        # it on the success path too — where the except branch that used
        # to define it never runs.
        wants_accelerator = self._device in ("cuda", "coreml", "auto")

        try:
            model = onnx_asr.load_model(load_id, **load_kwargs)
        except Exception as exc:
            # A load the user already abandoned still fails eventually —
            # it was blocked inside ORT session-init and Python cannot
            # interrupt that. Reporting it as a load failure is a lie
            # about the model: nobody is waiting on it any more, and a red
            # ERROR line reads as "this model is broken". ``cancel_load``
            # already moved the status to ``stopped``; leave it there.
            #
            # Gating the CPU retry on the same flag is what turned a
            # deliberate Cancel into a dead model: the retry below is
            # skipped precisely when the accelerator attempt fails, so
            # cancelling is what guaranteed the user ended up with no
            # working backend. Measured — a cancelled FastConformer load
            # ends in ERROR with no retry, while the same load without a
            # cancel reaches ``ready`` on CPU.
            with self._lock:
                abandoned = self._cancel_requested or self._shutdown
            if abandoned:
                log.info(
                    "Load of %s abandoned — the in-flight attempt failed "
                    "after it was cancelled or during shutdown: %s",
                    model_name, exc,
                )
                return

            # Fallback path: an accelerator provider (CUDA / CoreML)
            # was requested or auto-selected but failed at
            # session-create time — retry with CPU only so the user
            # ends up with a working backend instead of an error pill.
            #
            # We don't try to classify the exception any further:
            # ONNX Runtime surfaces accelerator-specific failures in
            # at least three different shapes — "CUDAExecutionProvider
            # not available …", CoreML's "model_builder.cc … Unable
            # to get shape for output …" (unsupported op), TensorRT
            # build errors, etc. — and a string-keyword match
            # inevitably misses one. Retrying on CPU when an
            # accelerator was the request is always safe: CPU is the
            # universal EP, so the second attempt either succeeds
            # (best outcome — model is at least usable, just slower)
            # or fails for a model-level reason that the first
            # attempt would have hit anyway.
            wants_accelerator = self._device in ("cuda", "coreml", "auto")
            if wants_accelerator:
                log.warning(
                    "Accelerator provider failed for this model (%s) — "
                    "retrying on CPU",
                    exc,
                )
                try:
                    model = onnx_asr.load_model(
                        load_id, **cpu_kwargs,
                    )
                    # Mark the active provider as CPU explicitly — the
                    # detection probe below would also resolve to CPU,
                    # but stamping it here keeps the source of truth
                    # close to the retry that produced it.
                    forced_provider = "CPU"
                except Exception as cpu_exc:
                    log.error(
                        "CPU fallback also failed for %s: %s",
                        model_name, cpu_exc, exc_info=True,
                    )
                    with self._lock:
                        if (
                            not self._shutdown
                            and not self._cancel_requested
                            and self._model_name == model_name
                        ):
                            self._model = None
                            self._status = "error"
                    return
            else:
                log.error(
                    "Failed to load ONNX model %s: %s", model_name, exc,
                    exc_info=True,
                )
                with self._lock:
                    if (
                        not self._shutdown
                        and not self._cancel_requested
                        and self._model_name == model_name
                    ):
                        self._model = None
                        self._status = "error"
                return

        # Probe the loaded model for the EP its InferenceSession actually
        # bound to.  The retry-on-CPU branch already pre-stamps
        # ``forced_provider``; otherwise we sniff the model object
        # (encoder / model attribute → ``session.get_providers()[0]``)
        # so the UI shows the real EP rather than the requested one.
        detected_provider = forced_provider or _detect_active_provider(model)

        # Actually run the model before believing it.
        #
        # ``load_model`` returning means a session was *built*, not that
        # the graph can run. An execution provider that binds at
        # session-create and then throws on the first ``run()`` produced a
        # permanently broken install that looked healthy: ``health_check``
        # answered True, the Engine pill showed the accelerator, and every
        # dictation then reported "no speech detected". This module's own
        # notes record Parakeet TDT v3 as unstable on CoreML specifically
        # at inference time, so the class is not hypothetical.
        #
        # A failed probe on an accelerator is treated as an accelerator
        # failure, not a verdict on the model: we reload on CPU, which is
        # the universal EP. If the probe fails there too, the model is
        # genuinely unusable and saying so beats waiting for the user's
        # first dictation to find out.
        probe_error = self._probe_inference(model, model_name)
        if probe_error is not None:
            log.warning(
                "Model %s loaded but failed its first inference on %s: %s",
                model_name, detected_provider or "unknown", probe_error,
                exc_info=True,
            )
            if detected_provider == "CPU" or not wants_accelerator:
                with self._lock:
                    if (
                        not self._shutdown
                        and not self._cancel_requested
                        and self._model_name == model_name
                    ):
                        self._model = None
                        self._status = "error"
                return
            try:
                model = onnx_asr.load_model(load_id, **cpu_kwargs)
                forced_provider = "CPU"
                detected_provider = "CPU"
                second_error = self._probe_inference(model, model_name)
            except Exception as cpu_exc:
                second_error = f"{type(cpu_exc).__name__}: {cpu_exc}"
            if second_error is not None:
                log.error(
                    "Model %s fails inference on CPU as well (%s) — it is "
                    "unusable here", model_name, second_error,
                    exc_info=True,
                )
                with self._lock:
                    if (
                        not self._shutdown
                        and not self._cancel_requested
                        and self._model_name == model_name
                    ):
                        self._model = None
                        self._status = "error"
                return

        with self._lock:
            if self._shutdown:
                return
            if self._cancel_requested:
                log.info(
                    "Discarding loaded ONNX model %s — cancelled by user",
                    model_name,
                )
                return
            if self._model_name != model_name:
                log.info(
                    "Discarding loaded ONNX model %s — name changed to %s",
                    model_name, self._model_name,
                )
                return
            self._model = model
            self._status = "ready"
            self._active_provider = detected_provider
            log.info(
                "OnnxAsr model %s ready (provider=%s)",
                model_name, detected_provider or "CPU (fallback/unknown)",
            )


def _resolve_auto_providers_non_darwin() -> list:
    """Return a provider list for ``device='auto'`` on Windows / Linux.

    Probes CUDA with a dummy session; if it works we return
    ``["CUDAExecutionProvider", "CPUExecutionProvider"]`` so the model
    loads on the GPU. If CUDA is unavailable (missing driver / DLL) we
    return ``["CPUExecutionProvider"]`` and skip the noisy TensorRT/CUDA
    fallback dance entirely.

    TensorRT is ignored for ``auto`` because it requires a separate SDK
    install and almost never works out-of-the-box.
    """
    global _AUTO_PROVIDER_CACHE
    if _AUTO_PROVIDER_CACHE is not None:
        return _AUTO_PROVIDER_CACHE

    try:
        import onnxruntime as ort
    except Exception:
        _AUTO_PROVIDER_CACHE = ["CPUExecutionProvider"]
        return _AUTO_PROVIDER_CACHE

    # Quiet ORT's default C++ logger so missing-CUDA-DLL messages don't
    # spam stderr *during the probe*.
    #
    # ``set_default_logger_severity`` is process-global and permanent —
    # there is no getter and no scoped form. Leaving it at 4 meant that
    # from the first capability probe onward, every ORT diagnostic in the
    # process was silenced, including the session-init errors the CPU
    # fallback below exists to diagnose; those reached the user as a
    # one-line warning naming an exception type and nothing else. Restore
    # it as soon as the probe is done.
    previous_severity = 2
    try:
        previous_severity = ort.get_default_logger_severity()
    except Exception:
        # Older ORT builds may not expose the getter; 2 (WARNING) is
        # ORT's own default and a safe thing to restore.
        pass
    ort.set_default_logger_severity(4)
    try:
        return _probe_available_providers(ort)
    finally:
        try:
            ort.set_default_logger_severity(previous_severity)
        except Exception:  # pragma: no cover — defensive
            log.debug("Could not restore ORT logger severity")


def _probe_available_providers(ort) -> list:
    """The body of :func:`_resolve_auto_providers_non_darwin`, minus the
    process-global logger mutation it runs under."""
    global _AUTO_PROVIDER_CACHE
    import numpy as np

    available = ort.get_available_providers()

    # Never auto-pick TensorRT — it needs a separate SDK and spams
    # the console with missing-cublas errors when the DLLs aren't
    # present.
    if "CUDAExecutionProvider" not in available:
        _AUTO_PROVIDER_CACHE = ["CPUExecutionProvider"]
        return _AUTO_PROVIDER_CACHE

    opts = ort.SessionOptions()
    opts.log_severity_level = 4  # silence ORT console spam
    x = np.array([0.0], dtype=np.float32)

    try:
        sess = ort.InferenceSession(
            _WARMUP_ONNX_BYTES,
            sess_options=opts,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        sess.run(None, {"x": x})
        # ORT silently falls back to CPU when the CUDA DLLs are
        # missing; session creation succeeds but get_providers()
        # reveals the real EP.  Only cache CUDA when the session
        # actually bound to it.
        if sess.get_providers() and sess.get_providers()[0] == "CUDAExecutionProvider":
            _AUTO_PROVIDER_CACHE = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            return _AUTO_PROVIDER_CACHE
        # GPU driver says CUDA is available, but the runtime DLLs
        # (cublasLt64_12.dll, cudnn64_9.dll, …) are not on PATH.
        # Log a one-time pointer so the user knows how to enable GPU.
        _warn_missing_cuda_redist()
        _AUTO_PROVIDER_CACHE = ["CPUExecutionProvider"]
        return _AUTO_PROVIDER_CACHE
    except Exception:
        _warn_missing_cuda_redist()
        _AUTO_PROVIDER_CACHE = ["CPUExecutionProvider"]
        return _AUTO_PROVIDER_CACHE


_CUDA_REDIST_WARNED: bool = False


def _warn_missing_cuda_redist() -> None:
    """Log a one-time hint when a GPU is present but CUDA runtime DLLs
    are missing so the model falls back to CPU."""
    global _CUDA_REDIST_WARNED
    if _CUDA_REDIST_WARNED:
        return
    _CUDA_REDIST_WARNED = True
    log.warning(
        "NVIDIA GPU detected, but CUDA runtime libraries are missing "
        "(cublasLt64_12.dll, cudnn64_9.dll, …).  "
        "The model will run on CPU.  "
        "To enable GPU acceleration, install the pip CUDA packages:\n"
        "    uv pip install --extra cuda\n"
        "or on non-uv workflows:\n"
        "    pip install \"lazy-to-text[cuda]\""
    )


# ---- module-level helpers (testable without a backend instance) ------------


def _transcribe_chunk(model, audio: np.ndarray, kwargs: dict) -> Optional[str]:
    """Run ``model.recognize(audio, **kwargs)`` and extract text.

    Handles both shapes onnx-asr returns:
    - bare ``"string"``
    - object with ``.text`` attribute (an ``OnnxAsrResult``)

    Any other shape raises. It used to fall back to ``str(result)``,
    which turns e.g. a ``SegmentResultsAsrAdapter`` generator into the
    literal text ``<generator object SegmentResultsAsrAdapter at
    0x7f…>`` — a non-empty string that would be pasted into whatever
    document the user was dictating into. A shape we cannot read is not
    a transcript, and reporting it as silence is the same lie in the
    other direction, so it has to be an error.
    """
    result = model.recognize(audio, **kwargs)
    if result is None:
        return None
    if isinstance(result, str):
        text = result
    else:
        text_attr = getattr(result, "text", None)
        if isinstance(text_attr, str):
            # The plain shape: one result object with the text on it.
            text = text_attr
        elif hasattr(result, "__iter__"):
            # The VAD adapter returns the speech segments it found, not
            # one text: a stream of objects with start / end / text. The
            # text is the parts, joined — the segments are the same
            # utterance split around the silences the VAD removed.
            parts = []
            for segment in result:
                segment_text = getattr(segment, "text", None)
                if not isinstance(segment_text, str):
                    raise TranscriptionError(
                        f"Recogniser returned an unreadable result of type "
                        f"{type(result).__name__} — no text to deliver"
                    )
                if segment_text.strip():
                    parts.append(segment_text.strip())
            text = " ".join(parts)
        else:
            raise TranscriptionError(
                f"Recogniser returned an unreadable result of type "
                f"{type(result).__name__} — no text to deliver"
            )
    return text.strip() or None


def _cut_point(buf: np.ndarray, start: int, limit: int) -> int:
    """End of the chunk that begins at ``start``: at most ``limit`` samples
    on, moved back to the quietest frame in the last ``_CUT_SEARCH_SAMPLES``.

    Ties go to the latest frame, so flat audio is cut exactly at ``limit``.
    """
    end = start + limit
    if end >= len(buf):
        return len(buf)
    lo = max(start + limit // 2, end - _CUT_SEARCH_SAMPLES)
    frames = (end - lo) // _CUT_FRAME_SAMPLES
    if frames < 2:
        return end
    seg = buf[lo : lo + frames * _CUT_FRAME_SAMPLES].reshape(frames, -1)
    energy = np.abs(seg).mean(axis=1)
    best = int(len(energy) - 1 - np.argmin(energy[::-1]))
    return lo + (best + 1) * _CUT_FRAME_SAMPLES


def _transcribe_adaptive(model, chunk: np.ndarray, kwargs: dict) -> Optional[str]:
    """One chunk through the model; if the model rejects it, halve and retry."""
    try:
        return _transcribe_chunk(model, chunk, kwargs)
    except TranscriptionError:
        raise
    except Exception:
        if len(chunk) <= _MIN_RETRY_SAMPLES:
            raise
        log.warning(
            "The model rejected a %.1f s chunk; retrying it in halves",
            len(chunk) / 16_000,
        )
        mid = len(chunk) // 2
        parts = [
            t
            for t in (
                _transcribe_adaptive(model, chunk[:mid], kwargs),
                _transcribe_adaptive(model, chunk[mid:], kwargs),
            )
            if t
        ]
        return " ".join(parts) or None


def _transcribe_chunked(
    model, buf: np.ndarray, kwargs: dict, chunk_samples: int = _CHUNK_SAMPLES
) -> Optional[str]:
    """Feed ``buf`` through the model in slices of at most ``chunk_samples``
    and join what came back with a space.

    Shared by ``transcribe`` and ``transcribe_file`` so the cap is
    enforced once. onnx-asr does no windowing of its own: its encoder
    runs once over the whole feature tensor, and some graphs (Vosk) fail
    outright past a fixed length, so the cap is per model
    (:func:`_chunk_samples_for`). Cuts are moved to the quietest nearby
    frame, and a chunk the model still rejects is halved
    (:func:`_transcribe_adaptive`).

    A chunk that comes back empty is skipped rather than treated as
    failure; the joined result is ``None`` only when every chunk was
    empty, which is the honest "heard nothing" answer.
    """
    if len(buf) < _MIN_MODEL_SAMPLES:
        buf = np.pad(buf, (0, _MIN_MODEL_SAMPLES - len(buf)))
    if len(buf) <= chunk_samples:
        return _transcribe_adaptive(model, buf, kwargs)

    parts: list[str] = []
    start = 0
    while start < len(buf):
        end = _cut_point(buf, start, chunk_samples)
        text = _transcribe_adaptive(model, buf[start:end], kwargs)
        if text:
            parts.append(text)
        start = end
    return " ".join(parts) or None


def _diarize(audio: np.ndarray) -> list:
    """Speaker turns of a 16 kHz mono recording.

    Built per call on purpose: the models are small, the call is one per file,
    and a diarizer kept alive would hold the weights open when the user deletes
    them. Raises :class:`TranscriptionError` when the model is not on disk.
    """
    from app import diarization_models
    from app.diarization import Diarizer

    located = diarization_models.paths()
    if located is None:
        raise TranscriptionError(
            "The diarization model is not downloaded. Download it in Models."
        )
    from app import background

    return Diarizer(*located, threads=background.thread_budget(4)).diarize(audio)


def _transcribe_by_speaker(
    model, audio: np.ndarray, kwargs: dict, chunk_samples: int, label: str,
) -> Optional[str]:
    """``"<label> N: text"`` paragraphs, one per speaker turn, or ``None``
    when the recording has fewer than two speakers (the caller then returns
    the ordinary transcript, which is what one voice should read as).

    Each turn is cut from the recording and recognised on its own, so the
    result does not depend on word timestamps and works for every model.
    Speakers are numbered from 1 in order of first appearance.
    """
    turns = _diarize(audio)
    if len({t.speaker for t in turns}) < 2:
        return None
    numbers: dict[int, int] = {}
    blocks: list[str] = []
    for turn in turns:
        first = max(0, int(turn.start * 16_000))
        last = min(len(audio), int(turn.end * 16_000))
        if last <= first:
            continue
        text = _transcribe_chunked(model, audio[first:last], kwargs, chunk_samples)
        if not text:
            continue
        number = numbers.setdefault(turn.speaker, len(numbers) + 1)
        blocks.append(f"{label} {number}: {text}")
    return "\n\n".join(blocks) or None


def _decode_audio_file(path: str) -> Optional[np.ndarray]:
    """Decode an audio file to a 16 kHz mono ``float32`` array.

    Two-tier decoder:

    1. **soundfile** (libsndfile) — handles WAV / FLAC / OGG / OPUS /
       AIFF in-process.  Fast, no subprocess fork.  Used as the fast
       path for the formats it understands.
    2. **ffmpeg** — bundled via ``imageio-ffmpeg`` (a static binary,
       ~70 MB on Windows).  Used as a fallback for everything else:
       MP3 / M4A / AAC / WMA / WebM / MOV / FLV / 3GP / Matroska /
       any other container ffmpeg can demultiplex.

    Returns ``None`` only when the file decoded to zero samples.

    A decode failure raises :class:`TranscriptionError`. It used to
    return ``None``, which is also what an empty transcript returns, so
    a file the app could not read reached the UI as *"the file may be
    corrupt or the model didn't hear any speech"* — a guess about the
    user's audio offered by the one code path that knows for certain it
    never got as far as listening to it.
    """
    sf_audio = _try_decode_with_soundfile(path)
    if sf_audio is not None:
        return sf_audio
    return _try_decode_with_ffmpeg(path)


def _try_decode_with_soundfile(path: str) -> Optional[np.ndarray]:
    try:
        import soundfile as sf  # type: ignore[import]
    except ImportError:
        return None
    try:
        buf, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    except Exception as exc:
        log.debug("soundfile cannot decode %s: %s — trying ffmpeg", path, exc)
        return None
    buf = np.asarray(buf, dtype=np.float32)
    if buf.ndim > 1:
        buf = buf.mean(axis=-1)
    if sample_rate != 16_000:
        buf = _resample(buf, int(sample_rate), 16_000)
    return buf


def _try_decode_with_ffmpeg(path: str) -> Optional[np.ndarray]:
    try:
        import imageio_ffmpeg  # type: ignore[import]
    except ImportError as exc:
        log.error(
            "Cannot decode %s — soundfile rejected the format and "
            "imageio-ffmpeg is not installed (would handle MP3 / M4A / "
            "WMA / WebM etc.).  Install with: pip install imageio-ffmpeg.  "
            "Or convert the file to .wav / .flac / .ogg manually.  "
            "Original ImportError: %s",
            path, exc,
        )
        return None

    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        log.error(
            "imageio-ffmpeg failed to locate its bundled binary: %s", exc,
        )
        return None

    cmd = [
        ffmpeg_exe,
        "-nostdin",                 # don't try to read keyboard input
        "-i", path,
        "-f", "f32le",              # raw 32-bit-float little-endian
        "-acodec", "pcm_f32le",
        "-ar", "16000",             # resample to 16 kHz
        "-ac", "1",                 # downmix to mono
        "-loglevel", "error",       # silence the banner / progress noise
        "pipe:1",
    ]
    # Hide the ffmpeg console window on Windows — without this, every
    # decode flashes a black cmd window in the user's face for a few
    # seconds.  No-op on POSIX (the flag doesn't exist there).
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=600,            # 10 min cap for very long files
            check=False,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        log.error("ffmpeg timed out decoding %s (>10 min)", path)
        return None
    except Exception as exc:
        log.error("ffmpeg subprocess failed for %s: %s", path, exc)
        return None

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        log.error(
            "ffmpeg returned %d decoding %s: %s",
            proc.returncode, path, stderr[:500],
        )
        return None

    if not proc.stdout:
        log.error("ffmpeg produced no audio output for %s", path)
        return None

    # ``np.frombuffer`` gives a read-only view onto the bytes buffer;
    # copy so downstream chunking can index/slice freely.
    audio = np.frombuffer(proc.stdout, dtype=np.float32).copy()
    if len(audio) == 0:
        return None
    return audio


def _resample(
    audio: np.ndarray, src_rate: int, dst_rate: int
) -> np.ndarray:
    """Resample ``audio`` from ``src_rate`` to ``dst_rate``.

    Uses the shared bounded-memory NumPy polyphase filter.

    The former linear-interpolation fallback had no anti-alias filter and
    measurably changed transcripts at real microphone rates. The shared
    NumPy polyphase filter keeps that filtering without loading SciPy's
    native BLAS DLL in the runtime; see ``CLAUDE.md`` for the measurements.

    Kept identical to ``AudioRecorder._resample_to`` on purpose — the
    two are separate copies of one algorithm for the microphone path
    and the file path, and
    ``tests/test_audio_recorder_resample.py`` holds them together.
    """
    from app.audio_resampling import resample_audio

    return resample_audio(audio, src_rate, dst_rate)


def _coreml_provider_entry() -> tuple[str, dict]:
    """CoreML provider entry tuned for Apple Silicon.

    Provider options
    ~~~~~~~~~~~~~~~~
    - ``ModelFormat='MLProgram'`` — the modern Core ML 5 container
      (macOS 12+).  ORT 1.18+ defaults to it but we pin explicitly
      so a future ORT release that flips the default back to the
      legacy ``NeuralNetwork`` format doesn't change our behaviour
      silently.
    - ``MLComputeUnits='ALL'`` — let CoreML's dispatcher route ops
      between Neural Engine, GPU and CPU per-op.  Apple's
      recommendation for mixed-workload models like ASR.
    - ``RequireStaticInputShapes='0'`` / ``EnableOnSubgraphs='0'``
      — current ORT defaults, pinned defensively so a future
      version change doesn't break dynamic-shape models that today
      load fine.

    Known model compatibility (empirical + ORT issue tracker as
    of ORT 1.25)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    - Whisper Large v3 / Turbo, Canary 1B v2 (Transformer ED) —
      load successfully on CoreML.
    - GigaAM v3 CTC / RNN-T (Conformer with static shapes) —
      expected to work; not exhaustively tested on every Mac.
    - Parakeet TDT v3 — unstable on CoreML, see ORT issue #26355
      ("CoreML execution provider fails during inference with the
      Parakeet CTC ASR model").
    - T-One (Russian Conformer-CTC) — fails at session-create with
      ``axis 2 is not in valid range [-2,1]`` (unsupported op).
    - Vosk-RU / Vosk Small (Zipformer streaming) — fails at
      session-create with ``Unable to get shape for output:
      tmp_9`` (CoreML EP can't handle streaming chunk dynamic
      shapes).

    The retry-on-CPU branch in :meth:`OnnxAsrBackend._do_load`
    catches every accelerator failure and silently re-loads the
    model on CPU, so the failure modes above surface to the user
    only as a one-line "Accelerator provider failed … retrying on
    CPU" warning in the Logs view; the Engine pill ends up
    reflecting the real EP (CPU).
    """
    return (
        "CoreMLExecutionProvider",
        {
            "ModelFormat": "MLProgram",
            "MLComputeUnits": "ALL",
            "RequireStaticInputShapes": "0",
            "EnableOnSubgraphs": "0",
        },
    )


# Maps ORT's verbose provider names to short labels for the UI pill.
_PROVIDER_PRETTY = {
    "CUDAExecutionProvider": "CUDA",
    "CoreMLExecutionProvider": "CoreML",
    "CPUExecutionProvider": "CPU",
    "TensorrtExecutionProvider": "TensorRT",
    "DmlExecutionProvider": "DirectML",
    "AzureExecutionProvider": "Azure",
    "ROCMExecutionProvider": "ROCm",
}


def _pretty_provider(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _PROVIDER_PRETTY.get(raw, raw.replace("ExecutionProvider", ""))


def _detect_active_provider(model) -> Optional[str]:
    """Return the EP name actually backing ``model``'s InferenceSession."""
    if model is None:
        return None

    # Log internal structure to find the session in wrapped adapters
    log.info("Probing model of type %s. dir() contents: %s", type(model), dir(model))

    # Handle onnx-asr adapters (e.g. TextResultsAsrAdapter) that wrap the real model.
    # These often have a .model attribute containing the actual ASR object.
    if hasattr(model, "model") and not hasattr(model, "get_providers"):
        log.info("Unwrapping model adapter: %s", type(model))
        model = model.model

    # Probe order: common attribute names used by onnx-asr
    probe_attrs = (
        "encoder", "_encoder",
        "model", "_model",
        "decoder", "_decoder",
        "session", "_session",
        "inference_session"
    )

    # 1. Check if the model itself is the session
    if hasattr(model, "get_providers"):
        try:
            providers = model.get_providers()
            if providers:
                res = _pretty_provider(providers[0])
                log.info("Found provider on model root: %s", res)
                return res
        except Exception:
            pass

    # 2. Check attributes
    for attr in probe_attrs:
        sess = getattr(model, attr, None)
        if sess is None:
            continue

        log.info("Probing attribute '%s' for session...", attr)

        # Some onnx-asr models wrap the session in another object
        # that has a 'session' attribute.
        if not hasattr(sess, "get_providers") and hasattr(sess, "session"):
            log.info("Attribute '%s' is a wrapper, using .session", attr)
            sess = sess.session

        get_providers = getattr(sess, "get_providers", None)
        if not callable(get_providers):
            continue
        try:
            providers = get_providers()
            if providers:
                res = _pretty_provider(providers[0])
                log.info("Found provider on attribute '%s': %s", attr, res)
                return res
        except Exception as e:
            log.info("Failed to get providers from '%s': %s", attr, e)
            continue

    log.info("No session/provider found in model %s", type(model))
    return None
