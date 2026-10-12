"""The services the post-processing step can reach, by name.

There is one wire format in this app and one exception to it. Almost
every text model service now answers ``POST {base}/chat/completions``
with an ``Authorization: Bearer`` header and a reply nested under
``choices[0].message.content``; Ollama answers ``POST {base}/api/chat``
with no header and a reply at ``message.content``. That is the whole
distinction, and it is a property of the *service*, not of the URL, so
it belongs to the provider rather than to a special case in the client.

Naming the services buys three things a free-text URL cannot:

- the dropdown can offer ``OpenRouter`` instead of a base string;
- the wire format follows the choice, so picking a preset cannot leave
  the request pointed at a path that service does not serve;
- whether the dictation leaves the machine can be answered by looking
  at where the address points.

The addresses are each service's published OpenAI-compatible base, and
were cross-checked against more than one independent source before being
written down here. They are defaults, not facts: ``base_url`` stays
editable, because a self-hosted vLLM or a corporate gateway is a
perfectly good target and there is no way to enumerate those.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

#: Ollama's own daemon, bound to loopback: a local model reachable from
#: the network is not a thing anybody asked for.
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

#: Which request/response shape a service speaks.
DIALECT_OLLAMA = "ollama"
DIALECT_OPENAI = "openai"

PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI = "openai"

#: The dropdown's last entry. Not a service — the absence of a choice,
#: for the server the app has never heard of. Its address is whatever
#: the user types, which is why it has no URL here.
PROVIDER_CUSTOM = "custom"


@dataclass(frozen=True)
class Provider:
    """One entry in the picker.

    ``url`` is empty for :data:`PROVIDER_CUSTOM` and that is deliberate:
    the entry stands for an address typed by hand, and a placeholder
    would be picked up by the "is this the untouched default?" rule
    that decides whether a provider switch may rewrite the field.
    """

    id: str
    label: str
    url: str
    dialect: str = DIALECT_OPENAI


#: Ordered as the picker shows them: this machine's own models first,
#: then cloud services roughly by how often somebody reaches for them.
#: Ollama leads because it is the one that keeps the app's local-first
#: claim true, and Custom trails because it is a fallback, not a choice.
PROVIDERS: tuple[Provider, ...] = (
    Provider(PROVIDER_OLLAMA, "This Mac (Ollama)", DEFAULT_OLLAMA_URL,
             DIALECT_OLLAMA),
    Provider("lmstudio", "LM Studio (this Mac)", "http://127.0.0.1:1234/v1"),
    Provider(PROVIDER_OPENAI, "OpenAI", "https://api.openai.com/v1"),
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1"),
    Provider("groq", "Groq", "https://api.groq.com/openai/v1"),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1"),
    Provider("together", "Together AI", "https://api.together.xyz/v1"),
    Provider("mistral", "Mistral", "https://api.mistral.ai/v1"),
    Provider("xai", "xAI (Grok)", "https://api.x.ai/v1"),
    Provider("cerebras", "Cerebras", "https://api.cerebras.ai/v1"),
    Provider("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1"),
    Provider(PROVIDER_CUSTOM, "Custom OpenAI-compatible server…", ""),
)

_BY_ID = {provider.id: provider for provider in PROVIDERS}


def provider_by_id(provider_id: str) -> Provider | None:
    """The named service, or ``None`` when the id is not in the list.

    ``None`` rather than a substitute: an id written by a future build
    or by hand is exactly the case that must reach the Custom
    behaviour, not the case that should quietly become Ollama.
    """
    return _BY_ID.get(provider_id)


def default_url_for(provider_id: str) -> str:
    """The address to show for *provider_id* when nothing is set.

    An id that is not in the list falls back to loopback rather than to
    any cloud address: a config this build does not recognise should
    send the dictation nowhere rather than somewhere new. Custom has no
    default of its own, so it is served by that same fallback and the
    user is expected to type the address.
    """
    provider = _BY_ID.get(provider_id)
    if provider is None or not provider.url:
        return DEFAULT_OLLAMA_URL
    return provider.url


def known_default_urls() -> frozenset[str]:
    """Every address the picker can put in the Server field.

    This is what separates "the user picked a provider and never
    touched the address" from "the user pointed this at something of
    their own". The first may be rewritten when the choice changes; the
    second never is.
    """
    return frozenset(p.url for p in PROVIDERS if p.url)


def dialect_for(provider_id: str) -> str:
    """Which wire format to speak to *provider_id*.

    Anything unrecognised is treated as OpenAI-shaped, which is the
    right way round for a mistake. The alternative — treating it as
    Ollama — sends ``POST {base}/api/chat`` to a service that serves
    ``/chat/completions``, and the failure is a 404 that reads like the
    server is broken. A user who genuinely runs Ollama names Ollama.
    """
    provider = _BY_ID.get(provider_id)
    return provider.dialect if provider is not None else DIALECT_OPENAI


def is_local_url(url: str) -> bool:
    """True when *url* points at this machine.

    Decides both whether the API-key field is offered and whether the
    card warns that the dictation is being sent away. Deriving it from
    the address rather than from a flag on the provider is what makes
    Custom behave sensibly: nobody can say in advance whether the
    address someone typed is a self-hosted model on this machine or a
    gateway three hops away, but the address itself can say.
    """
    host = (urlsplit(url or "").hostname or "").strip().lower()
    if not host:
        return False
    if host == "localhost":
        return True
    if host == "0.0.0.0":
        # Not a loopback address by the standard's own definition, but
        # every platform routes a connection to it to this machine.
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A name that is neither an address nor "localhost" — a LAN box,
        # a public host. Treated as remote, which is the safe direction:
        # the worst outcome is a warning on somebody's own network.
        return False