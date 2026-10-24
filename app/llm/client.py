"""Talking to a text model, over stdlib HTTP.

Two providers, one shape. Both are a JSON POST with a system message
and a user message; they differ in the URL, the auth header and where
the reply hides.

Deliberately ``urllib.request`` and not ``httpx``. ``httpx`` *is*
installed — it arrives with ``huggingface_hub`` via ``onnx-asr[hub]`` —
but it is not declared as a direct dependency, and this repo has
already had the opposite argument once: ``requests`` sat in
``pyproject.toml`` declared-but-imported-by-nothing, shipped into the
release bundle, and invited contributors to assume it was part of the
app. Depending on a transitive copy is the same mistake pointed the
other way. Two POSTs do not justify a dependency.

The step is a *network* call inside an app whose entire pitch is
"local-first", so two things here are not negotiable:

- an empty or unusable reply is a failure, never a silent pass-through
  of empty text (see :func:`_extract_text`);
- no exception message this module raises may contain the API key.
"""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.llm.errors import LLMError, LLMUnavailable
from app.llm.modes import mode_by_id
from app.llm.providers import (
    DEFAULT_OLLAMA_URL,
    DIALECT_OPENAI,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    default_url_for,
    dialect_for,
)

logger = logging.getLogger(__name__)

#: Refusing a larger reply than this is not a security control. It stops
#: a runaway or substituted server from making the app buffer an
#: unbounded body into a dictation that is supposed to arrive
#: immediately.
_MAX_REPLY_BYTES = 2 * 1024 * 1024

#: Short enough that a dictation does not sit in the clipboard waiting
#: on a socket. A local model on a cold start can take several seconds
#: to load its weights before it answers at all, so this is generous
#: for the case it is actually protecting — a black-holed request.
DEFAULT_TIMEOUT_S = 20

#: Bounds the Settings field enforces. A zero or negative timeout is
#: never valid, and a ceiling keeps a typo from parking a dictation in
#: the clipboard queue for an hour.
MIN_TIMEOUT_S = 1
MAX_TIMEOUT_S = 600

#: Ceiling for the output-token cap. ``0`` means "send nothing and let
#: the provider decide", which is the default.
MAX_OUTPUT_TOKENS = 32768

#: How hard a reasoning model thinks before it answers. Empty means the
#: provider's own default and nothing is sent. Ordered fastest first,
#: which is how the picker lists them.
REASONING_EFFORTS: tuple[str, ...] = ("none", "minimal", "low", "medium", "high")


@dataclass(frozen=True)
class LLMSettings:
    """The ``llm`` section of ``config.yaml``, as one value.

    Read through this rather than as a dict at each call site so that a
    missing key is impossible: every field has a default here, and a
    config file written by an older build cannot produce a
    ``KeyError`` three layers down in an HTTP call.
    """

    enabled: bool = False
    provider: str = PROVIDER_OLLAMA
    model: str = ""
    base_url: str = DEFAULT_OLLAMA_URL
    api_key: str = ""
    mode: str = "clean"
    timeout_s: int = DEFAULT_TIMEOUT_S
    # Speed controls. Both are *omitted from the request* at their
    # defaults, because a field an older or smaller server does not know
    # is a 400 that turns every dictation into raw text.
    #
    # ``reasoning_effort`` is one of :data:`REASONING_EFFORTS` or empty.
    # ``max_tokens`` caps the reply; 0 leaves it to the provider.
    reasoning_effort: str = ""
    max_tokens: int = 0
    # Resolved wording, when something upstream has already decided it.
    # A profile with its own prompt passes the finished system prompt
    # here; everything else leaves it empty and gets ``mode``'s.
    #
    # Kept as a string rather than a callable so this stays a plain
    # value that can be compared, logged and written to a test without
    # dragging the prompt registry into every comparison.
    system_prompt: str = ""

    @classmethod
    def from_config(cls, section: dict[str, Any] | None) -> "LLMSettings":
        """Build settings from a raw config section, tolerating junk.

        A value of the wrong type falls back to the default rather than
        raising. This is a dictation tool: a mistyped ``timeout_s``
        must not stop someone's speech from reaching the window.

        ``base_url`` resolves against the *chosen* provider, so a
        config that names a cloud provider and omits the endpoint does
        not inherit loopback — which sends the dictation to the user's
        own machine with an ``Authorization`` header attached.
        """
        section = section or {}
        provider = str(section.get("provider") or PROVIDER_OLLAMA)
        return cls(
            enabled=bool(section.get("enabled", False)),
            provider=provider,
            model=str(section.get("model") or ""),
            base_url=str(section.get("base_url") or default_url_for(provider)),
            api_key=str(section.get("api_key") or ""),
            mode=str(section.get("mode") or "clean"),
            timeout_s=clamp_timeout(section.get("timeout_s")),
            reasoning_effort=normalise_effort(section.get("reasoning_effort")),
            max_tokens=normalise_max_tokens(section.get("max_tokens")),
            system_prompt=str(section.get("system_prompt") or ""),
        )

    @property
    def configured(self) -> bool:
        """True when the step has everything it needs to even try.

        ``enabled`` with no model named is the state a user reaches by
        ticking the box before filling anything in, and calling a
        server with an empty model name produces a 404 that reads like
        the server is broken.
        """
        return bool(self.enabled and self.model.strip())


def _positive_int(value: Any, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def clamp_timeout(value: Any) -> int:
    """A usable timeout in seconds; junk falls back to the default."""
    number = _positive_int(value, DEFAULT_TIMEOUT_S)
    return max(MIN_TIMEOUT_S, min(MAX_TIMEOUT_S, number))


def normalise_effort(value: Any) -> str:
    """One of :data:`REASONING_EFFORTS`, or ``""`` for "provider default"."""
    text = str(value or "").strip().lower()
    return text if text in REASONING_EFFORTS else ""


def normalise_max_tokens(value: Any) -> int:
    """A cap in tokens, or 0 for "provider default"; junk and negatives are 0."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(MAX_OUTPUT_TOKENS, number))


def _endpoint(settings: LLMSettings) -> tuple[str, dict[str, str], dict[str, Any]]:
    """URL, headers and body for the configured provider.

    Split out from :func:`complete` so a test can assert on the request
    without standing up a socket.
    """
    messages = [
        {
            "role": "system",
            # An explicit prompt wins; otherwise the named mode's own.
            # Not "or": a profile whose custom prompt happens to be an
            # empty string after stripping must fall back too, which is
            # why the check is on the stripped value.
            "content": settings.system_prompt.strip() or mode_by_id(settings.mode).prompt,
        },
        {"role": "user", "content": ""},  # filled in by complete()
    ]
    base = settings.base_url.rstrip("/")

    if dialect_for(settings.provider) == DIALECT_OPENAI:
        headers = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        # No temperature. Reasoning-family models such as the gpt-5 line
        # (the Model field's own example) are reported to answer HTTP 400
        # to any value but their default. That 400 is caught as a failure
        # and the raw text delivered, so the example would silently never
        # post-process. The provider's default is used instead.
        body: dict[str, Any] = {"model": settings.model, "messages": messages}
        if settings.reasoning_effort:
            body["reasoning_effort"] = settings.reasoning_effort
        if settings.max_tokens:
            # OpenAI's own endpoint rejects ``max_tokens`` on its
            # reasoning models and wants ``max_completion_tokens``;
            # the compatible servers still only know ``max_tokens``.
            key = (
                "max_completion_tokens"
                if settings.provider == PROVIDER_OPENAI
                else "max_tokens"
            )
            body[key] = settings.max_tokens
        return (f"{base}/chat/completions", headers, body)

    # Ollama and anything that speaks its dialect. No auth: the daemon
    # is on loopback and has no notion of a key.
    options: dict[str, Any] = {"temperature": 0}
    if settings.max_tokens:
        options["num_predict"] = settings.max_tokens
    body = {
        "model": settings.model,
        "messages": messages,
        "stream": False,
        "options": options,
    }
    think = _ollama_think(settings.reasoning_effort)
    if think is not None:
        body["think"] = think
    return (f"{base}/api/chat", {"Content-Type": "application/json"}, body)


def _ollama_think(effort: str) -> bool | str | None:
    """Ollama's ``think`` field for an effort, ``None`` to omit it.

    Ollama takes a bool for most thinking models and a level for the
    gpt-oss family, so levels are sent as levels and "none" as off.
    """
    if not effort:
        return None
    if effort == "none":
        return False
    return "low" if effort == "minimal" else effort


def _extract_text(payload: Any, settings: LLMSettings) -> str:
    """Pull the reply out of a provider's envelope.

    Every failure here raises rather than returning what it found,
    including the one that matters most: **a reply with nothing in
    it**. An empty ``content`` is not a short dictation, it is a model
    that declined to answer, and treating it as text would deliver an
    empty paste over the words the user just spoke. The caller falls
    back to the original text; this function's job is to make sure it
    knows to.
    """
    try:
        if dialect_for(settings.provider) == DIALECT_OPENAI:
            content = payload["choices"][0]["message"]["content"]
        else:
            content = payload["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            f"the reply had no text in the shape {settings.provider} uses "
            f"({type(exc).__name__})"
        ) from None

    if not isinstance(content, str):
        raise LLMError(
            f"the reply's text was {type(content).__name__}, not a string"
        )

    stripped = content.strip()
    if not stripped:
        raise LLMError("the model returned no text")
    return stripped


def _safe_url(url: str) -> str:
    """*url* with any ``user:password@`` prefix removed.

    Some providers take credentials in the URL. The endpoint is quoted
    in every connection failure — it is the one piece of the request
    that helps anybody diagnose anything — so it has to be the endpoint
    and not the password that rides along in it.
    """
    scheme, _, rest = url.partition("://")
    if "@" not in rest:
        return url
    return f"{scheme}://{rest.rsplit('@', 1)[-1]}"


def complete(text: str, settings: LLMSettings) -> str:
    """Send *text* through the configured model and return the reply.

    Raises :class:`LLMError` (or :class:`LLMUnavailable`) on any
    failure. Never returns ``text`` itself as a fallback — see the
    module docstring.
    """
    if not settings.configured:
        raise LLMUnavailable(
            "post-processing is off, or no model has been named"
        )

    url, headers, body = _endpoint(settings)
    body["messages"][-1]["content"] = text

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, timeout=settings.timeout_s
        ) as response:
            raw = response.read(_MAX_REPLY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # The URL can carry nothing secret, but it can carry the user's
        # LAN address, and the body is the user's own dictation being
        # echoed back by some proxy. Neither belongs in app.log.
        raise LLMError(
            f"the server answered HTTP {exc.code}"
        ) from None
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        # The *type* of the underlying failure, never its message: a
        # ``URLError``'s reason carries whatever the server or the
        # resolver put in it, and this message goes to a log file.
        # ``ConnectionRefusedError`` tells the user to start the daemon;
        # its text tells them nothing they do not already have.
        reason = getattr(exc, "reason", None)
        kind = type(reason if reason is not None else exc).__name__
        raise LLMUnavailable(
            f"could not reach {_safe_url(url)} ({kind})"
        ) from None

    if len(raw) > _MAX_REPLY_BYTES:
        raise LLMError("the reply was too large to be text")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Also catches a base_url pointed at something that is not an
        # LLM server at all — a login page, say — which otherwise shows
        # up as a baffling "'str' object is not subscriptable".
        raise LLMError("the reply was not JSON") from None

    return _extract_text(payload, settings)
