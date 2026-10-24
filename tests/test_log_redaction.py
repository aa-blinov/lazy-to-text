"""Credentials never reach a log, whichever handler writes the record.

QA-RUNTIME-4 / QA-SEC-7 / QA-SEC-15: ``user:password@host`` in a preset
address went to app.log, stderr, ``logs.list`` and the ``log`` events.
"""

from __future__ import annotations

import io
import logging

import pytest

from app import log_redaction
from app.log_redaction import redact

PASSWORD = "URLPASSWORDCCC"


@pytest.mark.parametrize(
    "text",
    [
        f"saved https://bob:{PASSWORD}@gw.example.invalid/v1",
        f"'http://{PASSWORD}@host:1/x'",
        f"Authorization: Bearer {PASSWORD}ZZZZ",
        "token hf_PLANTEDTOKENBBB1234",
        "key sk-PLANTED-SECRET-AAA",
    ],
)
def test_redact_removes_the_credential_and_keeps_the_host(text):
    out = redact(text)

    assert PASSWORD not in out and "PLANTED" not in out
    if "gw.example" in text:
        assert "gw.example.invalid" in out


def test_ordinary_text_and_the_users_words_are_untouched():
    for text in ("Transcribed: напиши мне на почту a@b.ru завтра", "plain", ""):
        assert redact(text) == text


@pytest.fixture
def streams():
    log_redaction.install()
    root = logging.getLogger()
    sinks = []
    for fmt in ("%(message)s", "%(levelname)s:%(name)s:%(message)s"):
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.Formatter(fmt))
        root.addHandler(handler)
        sinks.append((handler, buf))
    old = root.level
    root.setLevel(logging.DEBUG)
    yield [b for _, b in sinks]
    root.setLevel(old)
    for handler, _ in sinks:
        root.removeHandler(handler)


def test_every_handler_sees_a_redacted_record(streams):
    logging.getLogger("t").info("endpoint %s", f"https://bob:{PASSWORD}@host/v1")

    for buf in streams:
        assert PASSWORD not in buf.getvalue()
        assert "host/v1" in buf.getvalue()


def test_the_ring_that_feeds_logs_list_and_events_is_redacted(streams):
    import collections

    from app.server.runtime import _RingHandler

    ring = collections.deque()
    handler = _RingHandler(ring)
    logging.getLogger().addHandler(handler)
    try:
        logging.getLogger("t").info("x %s", f"http://u:{PASSWORD}@h/")
    finally:
        logging.getLogger().removeHandler(handler)

    assert ring and PASSWORD not in ring[-1]["message"]


def test_the_change_log_does_not_quote_a_password_in_an_address():
    from app.config_manager import _redact_for_log

    shown = _redact_for_log("llm", "base_url", f"https://bob:{PASSWORD}@gw/v1")
    profiles = _redact_for_log(
        "llm", "profiles",
        [{"id": "a", "base_url": f"https://bob:{PASSWORD}@gw/v1", "api_key": "sk-1234567890"}],
    )

    assert PASSWORD not in shown and PASSWORD not in profiles
    assert "sk-1234567890" not in profiles
    assert "gw/v1" in shown


def test_the_file_handler_carries_no_password(tmp_path, monkeypatch):
    from app import bootstrap

    monkeypatch.setattr("app.utils.get_project_logs_path", lambda: str(tmp_path))
    root = logging.getLogger()
    before = list(root.handlers)
    path = bootstrap._install_file_logging(None)
    try:
        logging.getLogger("t").warning("saved %s", f"https://bob:{PASSWORD}@gw/v1")
        for h in root.handlers:
            h.flush()
        assert PASSWORD not in open(path, encoding="utf-8").read()
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()


def test_a_non_ascii_or_null_token_is_not_applied_and_does_not_raise(monkeypatch):
    import os

    from app.bootstrap import _apply_hf_token

    monkeypatch.delenv("HF_TOKEN", raising=False)
    for bad in ("café", "\u0000", "tok en", "ключ"):
        assert _apply_hf_token(bad) is False
        assert "HF_TOKEN" not in os.environ
    assert _apply_hf_token("hf_good1234567") is True
    assert os.environ["HF_TOKEN"] == "hf_good1234567"
    _apply_hf_token(None)
