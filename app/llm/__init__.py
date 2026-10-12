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
``SHARED_NOTE``
    The line under the picker saying what every mode does regardless —
    numerals, and the fact that no mode translates.
``PROVIDERS`` / ``provider_by_id`` / ``default_url_for``
    The services the picker offers, the address each one defaults to,
    and the wire format it speaks.
``Profile`` / ``profiles_from_config`` / ``resolve_profile``
    Named bundles of the five settings above plus a prompt of their own,
    and which one a given dictation runs.
``is_local_url``
    Whether an endpoint stays on this machine — what decides if the
    card offers an API key and warns that the words are leaving.
``LLMError`` / ``LLMUnavailable``
    Failure, split so "the daemon is not running" is not reported as a
    generic error to someone who has not started a daemon yet.
"""

from __future__ import annotations

from app.llm.client import (
    DEFAULT_TIMEOUT_S,
    LLMSettings,
    complete,
)
from app.llm.errors import LLMError, LLMUnavailable
from app.llm.modes import (
    DEFAULT_MODE,
    MODES,
    SHARED_NOTE,
    Mode,
    mode_by_id,
)
from app.llm.profiles import (
    DEFAULT_PROFILE_ID,
    DEFAULT_PROFILE_NAME,
    Profile,
    active_profile_id,
    next_profile_id,
    profile_from_mapping,
    profiles_from_config,
    profiles_to_config,
    resolve_profile,
    with_profile,
)
from app.llm.providers import (
    DEFAULT_OLLAMA_URL,
    DIALECT_OPENAI,
    DIALECT_OLLAMA,
    PROVIDERS,
    PROVIDER_CUSTOM,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    Provider,
    default_url_for,
    dialect_for,
    is_local_url,
    known_default_urls,
    provider_by_id,
)

__all__ = [
    "DEFAULT_MODE",
    "DEFAULT_OLLAMA_URL",
    "DEFAULT_PROFILE_ID",
    "DEFAULT_PROFILE_NAME",
    "DEFAULT_TIMEOUT_S",
    "DIALECT_OPENAI",
    "DIALECT_OLLAMA",
    "LLMError",
    "LLMSettings",
    "LLMUnavailable",
    "MODES",
    "Mode",
    "PROVIDERS",
    "PROVIDER_CUSTOM",
    "PROVIDER_OLLAMA",
    "PROVIDER_OPENAI",
    "Profile",
    "Provider",
    "SHARED_NOTE",
    "active_profile_id",
    "complete",
    "default_url_for",
    "dialect_for",
    "is_local_url",
    "known_default_urls",
    "mode_by_id",
    "next_profile_id",
    "profile_from_mapping",
    "profiles_from_config",
    "profiles_to_config",
    "provider_by_id",
    "resolve_profile",
    "with_profile",
]
