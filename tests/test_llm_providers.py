"""The provider list the post-processing card offers by name.

Two things are being pinned here. The first is that every entry in the
picker can actually be reached: a name with no address, or an address
that does not match its dialect, is a dropdown entry that cannot work.
The second is the rule the card's own behaviour hangs off — whether the
dictation stays on this machine — which has to come out right for an
address this app does not recognise as well as for one it does.
"""

import pytest

from app.llm.providers import (
    DEFAULT_OLLAMA_URL,
    DIALECT_OLLAMA,
    DIALECT_OPENAI,
    PROVIDERS,
    PROVIDER_CUSTOM,
    PROVIDER_OLLAMA,
    default_url_for,
    dialect_for,
    is_local_url,
    known_default_urls,
    provider_by_id,
)


# ---- the list itself ------------------------------------------------------


def test_every_entry_can_be_reached():
    """A provider with no id is unreachable, one with no name is
    invisible, and Custom excepted — it names the absence of one."""
    for provider in PROVIDERS:
        assert provider.id, "a provider with no id cannot be stored"
        assert provider.label, "a provider with no name cannot be picked"
        assert provider.dialect in (DIALECT_OLLAMA, DIALECT_OPENAI)
        if provider.id != PROVIDER_CUSTOM:
            assert provider.url.startswith(("http://", "https://"))


def test_ids_are_unique():
    ids = [provider.id for provider in PROVIDERS]
    assert len(ids) == len(set(ids))


def test_custom_is_the_last_thing_in_the_picker():
    """It is the fallback for a server nobody here has heard of, and a
    dropdown whose escape hatch is the first row is not read as an
    escape hatch."""
    assert PROVIDERS[-1].id == PROVIDER_CUSTOM


def test_the_services_the_card_was_asked_for_are_in_the_list():
    assert provider_by_id("openai") is not None
    assert provider_by_id("openrouter") is not None


def test_plain_http_only_ever_reaches_this_machine():
    """Every remote preset is https. A dictation is the user's own words,
    and one that crosses a network in clear text because a base URL lost
    an "s" is not something a test suite should have to notice in a bug
    report."""
    for provider in PROVIDERS:
        if not provider.url.startswith("http://"):
            continue
        assert is_local_url(provider.url), (
            f"{provider.label} would send the dictation unencrypted"
        )


# ---- addresses ------------------------------------------------------------


def test_each_provider_is_shown_its_own_address():
    for provider in PROVIDERS:
        if not provider.url:
            continue
        assert default_url_for(provider.id) == provider.url


def test_an_unknown_name_falls_back_to_loopback():
    """A config this build does not recognise should send the dictation
    nowhere rather than somewhere new. Same reasoning as the mode
    fallback: another build's file must not start the app pointed at a
    stranger's server."""
    assert default_url_for("some-future-provider") == DEFAULT_OLLAMA_URL


def test_custom_has_no_default_of_its_own():
    """It stands for an address typed by hand. A placeholder would be
    picked up by the "did the app put that there?" rule that decides
    whether a provider switch may rewrite the field."""
    assert provider_by_id(PROVIDER_CUSTOM).url == ""
    assert default_url_for(PROVIDER_CUSTOM) == DEFAULT_OLLAMA_URL


def test_the_known_defaults_are_exactly_the_presets_addresses():
    """This set is what separates "the user never touched the address"
    from "the user pointed this somewhere of their own"."""
    assert known_default_urls() == {
        p.url for p in PROVIDERS if p.url
    }


# ---- dialects -------------------------------------------------------------


def test_only_ollama_speaks_a_dialect_of_its_own():
    assert dialect_for(PROVIDER_OLLAMA) == DIALECT_OLLAMA
    for provider in PROVIDERS:
        if provider.id == PROVIDER_OLLAMA:
            continue
        assert dialect_for(provider.id) == DIALECT_OPENAI


def test_an_unknown_provider_is_treated_as_openai_shaped():
    """A mistake is the case this has to get right. Treating an unknown
    name as Ollama sends ``POST {base}/api/chat`` at a service serving
    ``/chat/completions``, and the failure is a 404 that reads like the
    server is broken. Somebody running Ollama names Ollama."""
    assert dialect_for("some-future-provider") == DIALECT_OPENAI


# ---- loopback -------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434",
    "http://127.0.0.1:1234/v1",
    "https://localhost:1234/v1",
    "http://LOCALHOST:8000/v1",
    "http://[::1]:1234/v1",
    "http://127.9.9.9:1234",
    "http://0.0.0.0:8000/v1",
])
def test_an_address_on_this_machine_is_recognised(url):
    assert is_local_url(url) is True


@pytest.mark.parametrize("url", [
    "https://api.openai.com/v1",
    "https://openrouter.ai/api/v1",
    "http://192.168.1.10:8000/v1",
    "http://llm.corp.internal/v1",
    "",
    "not a url at all",
])
def test_an_address_away_from_this_machine_is_not(url):
    assert is_local_url(url) is False