"""Optional post-processing of dictated text by a language model.

The step sits between the recogniser and the clipboard: the model
hears something, a text model tidies or rewrites it, and only then does
it reach the window the user is typing in. Off by default, and with no
opinion about which provider you use — a local Ollama keeps the app's
"local-first" claim true, a cloud endpoint does not and says so.

Public API:

``LLMSettings``
    The ``llm`` config section as one value, with defaults for
    everything so a config written by an older build cannot raise.
``complete``
    One request, one reply, raising on any failure.
``MODES`` / ``mode_by_id`` / ``DEFAULT_MODE``
    The transformations on offer and the one a fresh install uses.
``LLMError`` / ``LLMUnavailable``
    Failure, split so "the daemon is not running" is not reported as a
    generic error to someone who has not started a daemon yet.
"""

from __future__ import annotations

from app.llm.client import (
    DEFAULT_OLLAMA_URL,
    DEFAULT_TIMEOUT_S,
    PROVIDER_DEFAULT_URL,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    LLMSettings,
    complete,
    default_url_for,
)
from app.llm.errors import LLMError, LLMUnavailable
from app.llm.modes import DEFAULT_MODE, MODES, Mode, mode_by_id

__all__ = [
    "DEFAULT_MODE",
    "DEFAULT_OLLAMA_URL",
    "DEFAULT_TIMEOUT_S",
    "LLMError",
    "LLMSettings",
    "LLMUnavailable",
    "MODES",
    "Mode",
    "PROVIDER_DEFAULT_URL",
    "PROVIDER_OLLAMA",
    "PROVIDER_OPENAI",
    "complete",
    "default_url_for",
    "mode_by_id",
]
