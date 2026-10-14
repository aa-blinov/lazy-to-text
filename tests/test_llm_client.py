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
    SHARED_NOTE,
    complete,
    default_url_for,
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


def test_every_mode_carries_the_shared_rules():
    """A rule written into one prompt is a rule the other two quietly
    lack, and the modes differ in what they *do* with the words — not in
    how careful they are about them. Checked by identity rather than by
    content so that editing a rule cannot quietly drop it from one
    mode."""
    from app.llm.modes import _HOUSE_RULES

    for mode in MODES:
        assert mode.prompt.endswith(_HOUSE_RULES), (
            f"{mode.id} is missing the shared rules"
        )


def test_the_shared_rules_pin_the_two_failures_nobody_would_see():
    """Language and numerals are the two ways this step can be broken
    while still looking like it worked: an English answer to a Russian
    dictation, and "сорок два" left as words in a document that wanted a
    digit.

    The language rule is checked for its positive form and for the trap
    it exists to close. The old wording — "never translate", "stay in the
    original language" — was a prohibition, written in English, about an
    input that is usually not English; that is a much weaker signal than
    an instruction saying what to write instead.
    """
    from app.llm.modes import _HOUSE_RULES

    assert "Answer in the language the dictation is in" in _HOUSE_RULES
    assert "not a reason to answer in English" in _HOUSE_RULES
    assert "Write numbers as digits" in _HOUSE_RULES


def test_the_shared_rules_keep_repetition_that_was_intentional():
    """"repeated words" as a phrase tells a model to delete repeated
    words. The speaker who said "очень-очень хорошо" meant it, and the
    one who stumbled did not — so the rule has to name the difference or
    it removes emphasis along with the stutter."""
    from app.llm.modes import _HOUSE_RULES

    assert "accidental repetition" in _HOUSE_RULES
    assert "Keep repetition the speaker chose" in _HOUSE_RULES


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


# ---- any OpenAI-compatible endpoint, not just OpenAI -------------------------


def test_an_openrouter_base_url_produces_the_request_it_expects():
    """OpenRouter documents itself as a drop-in OpenAI replacement:
    ``POST {base}/chat/completions``, Bearer token, ``choices[].message``
    back. Nothing below the provider switch is OpenAI-specific, so the
    generic endpoint is what makes it work — no new code path."""
    settings = _settings(
        provider="openai",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-abc",
        model="anthropic/claude-sonnet-4",
    )
    url, headers, body = _endpoint(settings)

    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-or-abc"
    assert body["model"] == "anthropic/claude-sonnet-4"
    # No temperature on this dialect: see _endpoint for why the provider's
    # default is left in charge.
    assert set(body) == {"model", "messages"}


def test_the_reply_is_read_back_the_way_openrouter_returns_it():
    """``choices`` is always an array on OpenRouter, with ``message`` on
    a non-streamed completion. We never ask for a stream, so this is the
    only shape that can come back."""
    payload = {
        "id": "gen-1",
        "choices": [{
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "Привет."},
        }],
    }
    assert _extract_text(payload, _settings(provider="openai")) == "Привет."


def test_a_cloud_provider_with_no_endpoint_gets_a_cloud_default():
    """The trap this closes: a config naming a cloud provider with no
    ``base_url`` used to inherit ``127.0.0.1:11434``, which sends the
    dictation — and its ``Authorization`` header — back to the user's
    own machine."""
    settings = LLMSettings.from_config({"provider": "openai"})

    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.base_url != "http://127.0.0.1:11434"


def test_the_local_provider_still_defaults_to_loopback():
    settings = LLMSettings.from_config({"provider": "ollama"})
    assert settings.base_url == "http://127.0.0.1:11434"


def test_an_unknown_provider_falls_back_to_the_local_default():
    """A config written by a build that shipped a provider this one does
    not have must not send dictations somewhere unexpected."""
    assert default_url_for("gemini-cli") == "http://127.0.0.1:11434"


# ---- what the card promises, as opposed to what the prompt does --------
#
# A mode's ``description``, the shared line under the picker, and the
# prompt sent to the model are three separate strings describing one
# transformation, and nothing forced them to agree. They disagreed three
# ways at once, all invisible from the code: "Formal letter" promised a
# letter the prompt is forbidden to produce, "a short summary" invited
# exactly the compression the prompt forbids, and numerals were the most
# visible thing Clean up does while its description said nothing —
# with the first version of this fix putting the rule in Clean up alone,
# which left the other two lying by omission.


def test_formal_prose_does_not_promise_a_letter_it_may_not_produce():
    """``Formal letter`` promised an official letter. The prompt says
    ``do not add anything the speaker did not say``, so no salutation and
    no sign-off can come out of it — the promise and the prompt could not
    both be satisfied, and the prompt is the part that runs."""
    mode = mode_by_id("formal")

    assert mode.label == "Formal prose"
    text = mode.description.lower()
    assert "salutation" in text
    assert "sign-off" in text


def test_formal_prompt_forbids_the_salutation_its_card_promises_to_leave_out():
    """The card says no salutation and no sign-off. The prompt used to
    imply that only through "do not add anything the speaker did not
    say", while "suitable for an official letter" invited the very thing
    it left unforbidden. The prompt has to say it itself."""
    prompt = mode_by_id("formal").prompt.lower()

    assert "salutation" in prompt
    assert "sign-off" in prompt


def test_concise_does_not_describe_itself_as_a_summary():
    """A summary is allowed to drop. The prompt is not: it keeps every
    fact, name, number and commitment and keeps hedged things hedged. The
    word "summary" was asking the user to expect the first and promising
    the second."""
    mode = mode_by_id("concise")

    assert "summary" not in mode.description.lower()


def test_concise_leads_with_what_it_keeps():
    """Same promise as the old wording, but as the first thing read
    rather than a clause after the one word that misleads."""
    description = mode_by_id("concise").description.lower()

    assert description.startswith("the same facts in fewer words")


def test_the_shared_line_carries_the_numeral_rule_for_every_mode():
    """``сорок два`` arrives as ``42`` under all three modes, because the
    rule lives in the shared rules. This line is the only place it is
    said out loud — it used to go into Clean up's description alone, and
    a user reading Make concise's line could not tell that it rewrites
    numbers too."""
    from app.llm.modes import _HOUSE_RULES

    for mode in MODES:
        assert _HOUSE_RULES in mode.prompt, mode.id

    assert "digits" in SHARED_NOTE.lower()
    assert "42" in SHARED_NOTE


def test_the_shared_line_says_the_language_never_changes():
    """No mode translates, and that is a decision rather than an
    accident — the module docstring is an argument about why a
    translation mode was left out. The user cannot see a docstring, and
    this is the question everyone has before pointing a cloud model at
    their own dictation."""
    assert "never changes" in SHARED_NOTE.lower()
    assert "translat" in SHARED_NOTE.lower()


def test_the_shared_line_is_shorter_than_any_prompt():
    """It is read once, below a dropdown, while deciding. A paragraph
    there stops being read at all, and a shared rule that goes unread is
    the same failure as a shared rule that was never written."""
    assert len(SHARED_NOTE) < 200, SHARED_NOTE
