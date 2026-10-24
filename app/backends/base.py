"""Common interface for speech-to-text backends.

Every concrete backend (faster-whisper, GigaAM, future cloud APIs) implements
this Protocol so the rest of the app — StateManager, RecordingFactory, the
status poller — can swap between them with no special-casing.

The contract is intentionally narrow: load the model in the background, tell
callers what state we're in, and turn audio into text. Backends are expected
to be thread-safe — ``transcribe`` is invoked from the recording pipeline
thread and ``status`` from the UI poller thread.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

import numpy as np


# Possible values returned by ``status()``. ``loading`` covers both initial
# load and a model swap; the recording pipeline treats anything other than
# ``ready`` as "do not transcribe right now".
BACKEND_STATES = ("stopped", "loading", "ready", "error")


class TranscriptionError(RuntimeError):
    """Inference ran and failed, as distinct from hearing no speech.

    The two used to arrive as the same value. ``transcribe`` returned
    ``None`` both when the recogniser produced an empty transcript and
    when it raised — a mis-bound CoreML subgraph, a bad external-data
    path, an out-of-memory encoder, a token-vocabulary mismatch. Callers
    branch on falsiness, so all of those rendered as *"No speech
    detected"*, and the file path added *"the file may be corrupt"*, a
    diagnosis the user's audio never earned.

    Backends raise this instead of laundering a failure into ``None``.
    ``None`` now means only what it should: the model was ready and it
    heard nothing. The subprocess backend already had a working error
    channel — the worker catches, sends ``("error", …)``, the parent
    re-raises — so an exception crossing the process boundary is the
    same thing as one raised in-process.
    """


_PLUMBING_PREFIXES = ("Subprocess error: ", "TranscriptionError: ", "RuntimeError: ")


def user_reason(exc: BaseException, limit: int = 240) -> str:
    """One line a person can read about why a transcription failed.

    Strips the plumbing that wraps an error crossing the worker pipe
    (``Subprocess error: TranscriptionError: ...``), keeps the first line
    only and caps the length, so a multi-kilobyte ONNX message does not
    become the text of a notification. The full text stays in the log.
    """
    text = str(exc).strip()
    stripped = True
    while stripped:
        stripped = False
        for prefix in _PLUMBING_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):].lstrip()
                stripped = True
    text = (text.splitlines() or [""])[0].strip() or type(exc).__name__
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


@runtime_checkable
class TranscriptionBackend(Protocol):
    """Speech-to-text backend interface."""

    def status(self) -> str:
        """Return one of ``stopped`` | ``loading`` | ``ready`` | ``error``."""
        ...

    def health_check(self) -> bool:
        """``True`` if the backend is loaded and ready to transcribe."""
        ...

    def active_provider(self) -> Optional[str]:
        """Pretty-printed ONNX Runtime EP that the loaded model is
        actually using (e.g. ``"CUDA"``, ``"CoreML"``, ``"CPU"``,
        ``"TensorRT"``, ``"DirectML"``). Returns ``None`` while no
        model is loaded — including the loading and error states —
        so the UI can hide / dim the indicator until inference is
        actually possible.

        The value reflects the *real* EP after any retry-on-CPU
        fallback, not the one originally requested via
        ``device='auto'`` / ``device='cuda'``.
        """
        ...

    def load(self) -> None:
        """Begin loading the configured model (idempotent, non-blocking)."""
        ...

    def change_model(self, model: str) -> None:
        """Switch to a different model. Triggers a background reload."""
        ...

    def current_model(self) -> str:
        """Name / identifier of the model currently configured (not necessarily loaded)."""
        ...

    def current_language(self) -> Optional[str]:
        """Language code the backend will request from the model (or ``None``
        for auto-detect). Used by the recording pipeline when stamping
        history entries."""
        ...

    def transcribe(
        self, audio: np.ndarray, sample_rate: int = 16000
    ) -> Optional[str]:
        """Run inference on a mono ``float32`` numpy array.

        Returns the transcribed text, or ``None`` when the backend is not
        ready or the model genuinely produced an empty result.

        Raises :class:`TranscriptionError` if inference ran and failed.
        """
        ...

    def transcribe_file(self, path: str) -> Optional[str]:
        """Transcribe an audio file from disk.

        The backend handles its own audio decoding (WAV / FLAC / OGG /
        MP3 depending on what its loader supports).  Returns the
        transcribed text, or ``None`` when the backend is not ready or
        the model genuinely produced an empty result.

        Raises :class:`TranscriptionError` if inference ran and failed.
        """
        ...

    def shutdown(self) -> None:
        """Release resources, stop background threads. Idempotent."""
        ...
