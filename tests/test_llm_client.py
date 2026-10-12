"""The post-processing client: what it sends, and what it does with a
bad answer.

Everything here is about one thing — a dictation app must never lose
the user's words to an optional network call. The client therefore
raises on every failure rather than passing its input back, because
the caller can only choose a sensible fallback if it is *told* the
step failed. A helper that quietly returned the input on error would
make "post-processing is on" and "post-processing silently did
nothing" indistinguishable at the call site.

The same reasoning drives the empty-reply test, which is the failure
most likely to be written off as harmless: an empty string from a
model is not a short dictation, it is a model that declined, and
delivering it would paste nothing over words the user just spoke.
"""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from app.llm import (
    LLMError,
    LLMSettings,
    LLMUnavailable,
    MODES,
    complete,
    mode_by_id,
)
from app.llm.client import _endpoint, _extract_text

SECRET = "sk-do-not-log-me-0123456789"


def _settings(**overrides) -> LLMSettings:
    base = {
        "enabled": True,
        "provider": "ollama",
        "model": "qwen2.5:7b",
        "base_url": "http://127.0.0.1:11434",
        "api_key": "",
        "mode": "clean",
    }
    base.update(overrides)
    return LLMSettings.from_config(base)


def _reply(payload) -> MagicMock:
    """A ``urlopen`` stand-in that answers with *payload* as JSON."""
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    return MagicMock(return_value=response)


# ---- settings ---------------------------------------------------------------


def test_a_mistyped_setting_falls_back_instead_of_raising():
    """This is a dictation tool. A hand-edited ``timeout_s`` must not
    stop somebody's speech from reaching the window three layers down in
    an HTTP call."""
    settings = LLMSettings.from_config(
        {"timeout_s": "twenty seconds", "model": None, "enabled": True}
    )

    assert settings.timeout_s == 20
    assert settings.model == ""
    assert settings.enabled is True


@pytest.mark.parametrize(
    "section, configured",
    [
        ({"enabled": False, "model": "m"}, False),
        ({"enabled": True, "model": ""}, False),
        ({"enabled": True, "model": "   "}, False),
        ({"enabled": True, "model": "m"}, True),
    ],
)
def test_the_step_only_runs_when_it_has_something_to_run(section, configured):
    """Ticking the box before typing a model name is the state a user
    reaches first. Calling a server with an empty model produces a 404
    that reads like the server is broken, so it is caught here instead."""
    assert LLMSettings.from_config(section).configured is configured


def test_an_absent_section_reads_as_off():
    assert LLMSettings.from_config(None).configured is False


# ---- the request -----------------------------------------------------------


def test_the_local_provider_sends_to_ollama_with_no_auth():
    """Ollama is on loopback and has no notion of a key. Sending an
    Authorization header would put a credential on a request that does
    not need it."""
    url, headers, body = _endpoint(_settings())

    assert url == "http://127.0.0.1:11434/api/chat"
    assert "Authorization" not in headers
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "system"


def test_the_cloud_provider_sends_a_bearer_token():
    url, headers, body = _endpoint(
        _settings(provider="openai", base_url="https://api.example.com/v1",
                  api_key=SECRET, model="gpt-4o-mini")
    )

    assert url == "https://api.example.com/v1/chat/completions"
    assert headers["Authorization"] == f"Bearer {SECRET}"
    assert body["model"] == "gpt-4o-mini"


def test_a_trailing_slash_does_not_double_up_in_the_url():
    url, _, _ = _endpoint(_settings(base_url="http://127.0.0.1:11434/"))
    assert url == "http://127.0.0.1:11434/api/chat"


def test_the_dictation_travels_as_the_user_message():
    """The system prompt and the user's words must not be swapped. It is
    the one bug in this module that produces confident, plausible
    output instead of an error, so it is asserted directly."""
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _reply({"message": {"content": "ok"}})()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        complete("привет мир", _settings())

    assert captured["messages"][-1] == {
        "role": "user", "content": "привет мир",
    }
    assert captured["messages"][0]["content"] == mode_by_id("clean").prompt


# ---- the reply --------------------------------------------------------------


def test_a_reply_from_ollama_is_read():
    assert _extract_text({"message": {"content": " Привет. "}},
                         _settings()) == "Привет."


def test_a_reply_from_a_cloud_provider_is_read():
    assert _extract_text(
        {"choices": [{"message": {"content": "Привет."}}]},
        _settings(provider="openai"),
    ) == "Привет."


def test_an_empty_reply_is_a_failure_and_not_a_short_dictation():
    """The failure most likely to be waved through. An empty ``content``
    is a model that declined, and treating it as text would deliver an
    empty paste over the words the user just spoke."""
    with pytest.raises(LLMError, match="no text"):
        _extract_text({"message": {"content": "   \n "}}, _settings())


def test_a_reply_in_the_wrong_shape_is_a_failure():
    with pytest.raises(LLMError):
        _extract_text({"unexpected": True}, _settings())


def test_a_non_string_reply_is_a_failure():
    with pytest.raises(LLMError, match="not a string"):
        _extract_text({"message": {"content": 42}}, _settings())


def test_a_page_that_is_not_json_does_not_surface_as_a_type_error():
    """A ``base_url`` pointed at a login page is a thing a user does. It
    must arrive as "not JSON", not as a confusing subscript error three
    frames later."""
    response = MagicMock()
    response.read.return_value = b"<html>Sign in</html>"
    response.__enter__.return_value = response

    with patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(LLMError, match="not JSON"):
            complete("привет", _settings())


# ---- failures ---------------------------------------------------------------


def test_a_refused_request_names_the_status_code():
    error = urllib.error.HTTPError(
        "http://127.0.0.1:11434/api/chat", 404, "Not Found", {}, None,
    )
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(LLMError, match="404"):
            complete("привет", _settings())


def test_nothing_listening_is_reported_as_unavailable():
    """Its own exception type, because that is the failure the user can
    fix in ten seconds — start the daemon — and a generic "post-
    processing failed" sends them looking for a bug instead."""
    error = urllib.error.URLError(ConnectionRefusedError("refused"))
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(LLMUnavailable):
            complete("привет", _settings())


def test_an_unconfigured_step_never_reaches_the_network():
    with patch("urllib.request.urlopen") as urlopen:
        with pytest.raises(LLMUnavailable):
            complete("привет", _settings(enabled=False))

    urlopen.assert_not_called()


def test_the_api_key_never_appears_in_an_error_message():
    """``app.log`` is on disk, unbounded, and not cleared by "Clear
    history". A dictation must not end up there by way of an HTTP
    error, so the credential is asserted absent from every failure the
    client can produce."""
    failures = [
        urllib.error.HTTPError(
            "http://x/chat/completions", 401, "Unauthorized", {}, None,
        ),
        urllib.error.HTTPError(
            "http://x/chat/completions", 500, "Server Error", {}, None,
        ),
        urllib.error.URLError(f"cannot reach {SECRET}"),
        ConnectionResetError(f"reset while sending {SECRET}"),
    ]
    settings = _settings(
        provider="openai", base_url="https://api.example.com/v1", api_key=SECRET,
    )

    for error in failures:
        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(LLMError) as caught:
                complete("привет", settings)
        assert SECRET not in str(caught.value), str(caught.value)


def test_a_reply_larger_than_the_cap_is_refused():
    """Not a security control. It stops a runaway or substituted server
    from making the app buffer an unbounded body into a dictation that is
    supposed to arrive immediately."""
    response = MagicMock()
    response.read.return_value = b"x" * (2 * 1024 * 1024 + 1)
    response.__enter__.return_value = response

    with patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(LLMError, match="too large"):
            complete("привет", _settings())


# ---- the modes --------------------------------------------------------------


def test_every_mode_says_what_it_does_and_how_to_do_it():
    """A mode with no description cannot be chosen from a dropdown;
    one with no prompt would send the user's words with no instruction
    attached."""
    for mode in MODES:
        assert mode.id and mode.label and mode.description
        assert len(mode.prompt) > 50, mode.id


def test_the_mode_ids_are_what_gets_written_to_disk():
    """The config stores an id, not a label. Two modes sharing one would
    make the stored value ambiguous and the second unreachable."""
    ids = [m.id for m in MODES]
    assert len(set(ids)) == len(ids)


def test_an_unknown_mode_falls_back_rather_than_raising():
    """The id comes from ``config.yaml``, which is a file on disk. A
    config naming a mode this build does not have is a settings
    mismatch, not a reason to stop dictating."""
    assert mode_by_id("summarise-in-french").id == MODES[0].id


def test_credentials_inside_the_url_are_stripped_before_logging():
    """Some providers take ``https://user:pass@host``. The endpoint is
    worth naming in a connection failure — it is the one part of the
    request that helps diagnose anything — so the password must be
    removed from it rather than the endpoint removed."""
    settings = _settings(
        provider="openai",
        base_url="https://alice:hunter2@api.example.com/v1",
        api_key="",
    )
    error = urllib.error.URLError(ConnectionRefusedError("refused"))

    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(LLMUnavailable) as caught:
            complete("привет", settings)

    message = str(caught.value)
    assert "api.example.com" in message, message
    assert "hunter2" not in message, message
    assert "alice" not in message, message
