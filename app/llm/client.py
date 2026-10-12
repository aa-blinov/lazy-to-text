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

#: What a config gets when it names no endpoint. Ollama's own default
#: port, bound to loopback: a local model reachable from the network is
#: not a thing anyone asked for.
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI = "openai"


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

    @classmethod
    def from_config(cls, section: dict[str, Any] | None) -> "LLMSettings":
        """Build settings from a raw config section, tolerating junk.

        A value of the wrong type falls back to the default rather than
        raising. This is a dictation tool: a mistyped ``timeout_s``
        must not stop someone's speech from reaching the window.
        """
        section = section or {}
        return cls(
            enabled=bool(section.get("enabled", False)),
            provider=str(section.get("provider") or PROVIDER_OLLAMA),
            model=str(section.get("model") or ""),
            base_url=str(section.get("base_url") or DEFAULT_OLLAMA_URL),
            api_key=str(section.get("api_key") or ""),
            mode=str(section.get("mode") or "clean"),
            timeout_s=_positive_int(section.get("timeout_s"), DEFAULT_TIMEOUT_S),
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


def _endpoint(settings: LLMSettings) -> tuple[str, dict[str, str], dict[str, Any]]:
    """URL, headers and body for the configured provider.

    Split out from :func:`complete` so a test can assert on the request
    without standing up a socket.
    """
    messages = [
        {"role": "system", "content": mode_by_id(settings.mode).prompt},
        {"role": "user", "content": ""},  # filled in by complete()
    ]
    base = settings.base_url.rstrip("/")

    if settings.provider == PROVIDER_OPENAI:
        headers = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        return (
            f"{base}/chat/completions",
            headers,
            {"model": settings.model, "messages": messages, "temperature": 0},
        )

    # Ollama and anything that speaks its dialect. No auth: the daemon
    # is on loopback and has no notion of a key.
    return (
        f"{base}/api/chat",
        {"Content-Type": "application/json"},
        {
            "model": settings.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0},
        },
    )


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
        if settings.provider == PROVIDER_OPENAI:
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
