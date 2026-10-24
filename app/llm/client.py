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

import http.client
import ipaddress
import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.parse
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
            # Surrounding whitespace is what a copy-paste adds; a key never
            # has any, and a trailing newline is an invalid header value.
            api_key=str(section.get("api_key") or "").strip(),
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
        return bool(
            self.enabled and self.model.strip() and not self.problem
        )

    @property
    def problem(self) -> str:
        """Why this configuration cannot be sent anywhere, or ``""``.

        A mistyped address or a key with a line break is a state a user
        can reach by typing, and it must neither raise out of the
        dictation pipeline nor leak the value into a log: the text names
        the field, never its content.
        """
        return endpoint_problem(self.base_url) or key_problem(self.api_key)


def _has_control(text: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in text)


def endpoint_problem(url: str) -> str:
    """A sentence about what is wrong with a server address, or ``""``.

    Only ``http`` and ``https`` are ever contacted: a ``file://`` or
    ``ftp://`` address is a mistake or an attempt to make the app read
    something, and credentials in the address are refused because
    ``urllib`` does not use them for authentication - the key has its own
    field. The message never contains the address.
    """
    text = url or ""
    if not text.strip():
        return "the server address is empty"
    if _has_control(text) or any(ch.isspace() for ch in text):
        return "the server address contains a space or a line break"
    try:
        parts = urllib.parse.urlsplit(text)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError:
        return "the server address is not a valid URL"
    if parts.scheme.lower() not in ("http", "https"):
        return "the server address must start with http:// or https://"
    if not host:
        return "the server address has no host name"
    if parts.username is not None or parts.password is not None:
        return (
            "the server address contains a user name or password; "
            "put the key in the API key field"
        )
    return ""


def key_problem(key: str) -> str:
    """A sentence about what is wrong with an API key, or ``""``."""
    if not key:
        return ""
    if _has_control(key):
        return "the API key contains a line break or another control character"
    try:
        key.encode("latin-1")
    except UnicodeEncodeError:
        return "the API key contains characters that cannot be sent in a header"
    return ""


def _ascii_url(url: str) -> str:
    """*url* with a non-ASCII host or path made safe to put on the wire."""
    try:
        url.encode("ascii")
        return url
    except UnicodeEncodeError:
        pass
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    netloc = host.encode("idna").decode("ascii")
    if ":" in netloc:
        netloc = f"[{netloc}]"
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urllib.parse.urlunsplit((
        parts.scheme,
        netloc,
        urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=~-._"),
        urllib.parse.quote(parts.query, safe="=&%+/?:@!$'()*,;~-._"),
        "",
    ))


def _bypasses_proxy(url: str) -> bool:
    """True for an address that must be contacted directly, never via a proxy.

    The proxy policy, stated once. A proxy sees the whole request, the
    dictation and the key included, so it is used only for hosts that are
    not on this computer or its own network, and only when the user's
    environment (or the operating system) names one. Loopback, private and
    link-local addresses and ``.local`` / ``.localhost`` names never go
    through a proxy: the privacy line promises the text stays on this
    computer, and a debugging or corporate proxy on the machine would
    otherwise receive it.
    """
    host = (urllib.parse.urlsplit(url).hostname or "").strip().lower().rstrip(".")
    if not host:
        return True
    if host == "localhost" or host.endswith((".localhost", ".local")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_loopback or address.is_private or address.is_link_local
        or address.is_unspecified
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect.

    ``urllib`` re-sends the request headers to the new location, so a
    gateway that answers ``302`` to another host would be handed the API
    key. A model endpoint has no business redirecting; the 3xx surfaces
    as an error and the dictation falls back to the raw text.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_opener(url: str) -> urllib.request.OpenerDirector:
    """An opener for http(s) only, with the proxy policy and no redirects."""
    opener = urllib.request.OpenerDirector()
    proxies = {} if _bypasses_proxy(url) else None  # None: environment / OS
    for handler in (
        urllib.request.ProxyHandler(proxies),
        urllib.request.UnknownHandler(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
        _NoRedirect(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def _open(request, timeout):
    """Open *request* with the policy opener. The seam tests replace."""
    return _build_opener(request.full_url).open(request, timeout=timeout)


def _exchange(request, deadline: float, timeout_s: int) -> bytes:
    """Send *request* and read the reply, giving up at *deadline*.

    ``timeout`` on a socket bounds one read, so a server that sends a byte
    a second would hold the dictation for as long as it likes. The reply
    is therefore read in pieces against a wall-clock deadline.
    """
    with _open(request, timeout=timeout_s) as response:
        chunks: list[bytes] = []
        size = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout("deadline")
            try:
                sock = response.fp.raw._sock  # type: ignore[union-attr]
                sock.settimeout(max(0.05, remaining))
            except Exception:
                pass
            piece = response.read1(65536)
            if not piece:
                break
            chunks.append(piece)
            size += len(piece)
            if size > _MAX_REPLY_BYTES:
                break
        return b"".join(chunks)


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
    scheme, sep, rest = url.partition("://")
    if not sep:
        scheme, rest = "", url
    # The credential ends at the last "@" before the first "/" of the path.
    authority, slash, path = rest.partition("/")
    if "@" not in authority:
        return url
    kept = authority.rsplit("@", 1)[-1] + slash + path
    return f"{scheme}://{kept}" if sep else kept


strip_credentials = _safe_url


def _where(url: str) -> str:
    """``host:port`` of *url*, without any credential, for a sentence."""
    try:
        parts = urllib.parse.urlsplit(_safe_url(url))
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
    except ValueError:
        return "the configured address"
    if not host:
        return "the configured address"
    return f"{host}:{port}" if port else host


def complete(text: str, settings: LLMSettings) -> str:
    """Send *text* through the configured model and return the reply.

    Raises :class:`LLMError` (or :class:`LLMUnavailable`) on any
    failure, whatever its origin: a malformed address, a header the
    server cannot accept, a reply that is not HTTP at all. The step is
    optional, so the caller's only question is "did it work", and an
    exception of any other type would escape it and take the dictation
    down with it. Never returns ``text`` itself as a fallback - see the
    module docstring.

    The whole exchange has one wall-clock budget, ``timeout_s``: the
    socket timeout alone bounds each read, not the request.
    """
    problem = settings.problem
    if problem:
        raise LLMError(problem)
    if not settings.configured:
        raise LLMUnavailable(
            "post-processing is off, or no model has been named"
        )

    try:
        url, headers, body = _endpoint(settings)
        body["messages"][-1]["content"] = text
        url = _ascii_url(url)
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, headers=headers, method="POST",
        )
    except Exception as exc:
        raise LLMError(
            f"the request could not be built ({type(exc).__name__})"
        ) from None

    deadline = time.monotonic() + settings.timeout_s
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["raw"] = _exchange(request, deadline, settings.timeout_s)
        except BaseException as exc:  # noqa: BLE001 - reported to the caller
            outcome["error"] = exc

    worker = threading.Thread(target=run, name="llm-request", daemon=True)
    worker.start()
    worker.join(timeout=settings.timeout_s + 0.25)
    if worker.is_alive():
        # Name resolution and the TLS handshake cannot be interrupted; the
        # daemon thread ends on its own socket timeout, and nobody waits.
        raise LLMUnavailable(
            f"The server at {_where(url)} did not answer in time."
        )

    exc = outcome.get("error")
    if exc is not None:
        _raise_for(exc, url)
    raw = outcome.get("raw", b"")

    if len(raw) > _MAX_REPLY_BYTES:
        raise LLMError("the reply was too large to be text")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        # Also catches a base_url pointed at something that is not an
        # LLM server at all - a login page, say - which otherwise shows
        # up as a baffling "'str' object is not subscriptable".
        raise LLMError("the reply was not JSON") from None

    return _extract_text(payload, settings)


def _raise_for(exc: BaseException, url: str) -> None:
    """Translate whatever the request raised into an :class:`LLMError`.

    Only the *type* of an underlying failure is ever put in the message,
    never its text: the text can carry the server's own words, the
    resolver's, or - for a malformed header - the API key, and this
    message goes to a log file.
    """
    # The messages below are stable sentences a person can read: they reach
    # the Test connection result and the log line that follows a failed
    # post-processing, and each has a Russian entry in the renderer's
    # ``ru.runtime.json``. They carry the status code or ``host:port`` and
    # nothing else.
    if isinstance(exc, urllib.error.HTTPError):
        if 300 <= exc.code < 400:
            raise LLMError(
                f"The server answered with a redirect (HTTP {exc.code}), "
                "which is not followed."
            ) from None
        if exc.code in (401, 403, 407):
            raise LLMError("The server refused the key.") from None
        # The URL can carry nothing secret, but it can carry the user's
        # LAN address, and the body is the user's own dictation being
        # echoed back by some proxy. Neither belongs in app.log.
        raise LLMError(
            f"The server answered with an error (HTTP {exc.code})."
        ) from None
    if isinstance(exc, (urllib.error.URLError, socket.timeout, OSError)):
        # ``ConnectionRefusedError`` tells the user to start the daemon;
        # its text tells them nothing they do not already have.
        reason = getattr(exc, "reason", None)
        if isinstance(reason if reason is not None else exc, socket.timeout):
            raise LLMUnavailable(
                f"The server at {_where(url)} did not answer in time."
            ) from None
        raise LLMUnavailable(
            f"The server did not answer at {_where(url)}. Is it running?"
        ) from None
    if isinstance(exc, http.client.HTTPException):
        raise LLMError(
            f"the server did not answer in HTTP ({type(exc).__name__})"
        ) from None
    raise LLMError(f"the request failed ({type(exc).__name__})") from None
