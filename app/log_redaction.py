"""Keeping credentials out of every log, whichever handler writes it.

``app.log``, stderr, the Logs view and the event stream are four sinks
for the same record, and each one used to be protected (or not) on its
own. Redacting where the record is *read* covers all of them at once:
every handler formats a record through ``LogRecord.getMessage``, so a
record class that redacts there cannot be bypassed by a new handler.

What is removed is a credential, never the user's words: the Logs view
keeps showing what was just recognised.
"""

from __future__ import annotations

import logging
import re

# ``scheme://user:password@host`` and ``scheme://token@host``: everything
# between the scheme and the ``@`` of the authority is a credential.
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s@'\"<>]+@")
# ``Authorization: Bearer abc`` / ``Bearer abc``.
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=\-]{6,}")
# Hugging Face and OpenAI-style key shapes, wherever they turn up.
_KNOWN_KEYS = re.compile(r"\b(?:hf_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9_\-]{8,})\b")

REDACTED = "<redacted>"


def redact(text: str) -> str:
    """*text* with URL credentials, bearer tokens and known key shapes removed."""
    if not text or ("@" not in text and "earer" not in text
                    and "hf_" not in text and "sk-" not in text):
        return text
    text = _URL_USERINFO.sub(lambda m: f"{m.group(1)}{REDACTED}@", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    return _KNOWN_KEYS.sub(REDACTED, text)


class _RedactingRecord(logging.LogRecord):
    def getMessage(self) -> str:  # noqa: N802 - the logging API's name
        return redact(super().getMessage())


_installed = False


def install() -> None:
    """Make every record from now on redact itself. Idempotent."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        # Swap the class instead of building a second record, so a custom
        # factory's attributes are kept.
        if type(record) is logging.LogRecord:
            record.__class__ = _RedactingRecord
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
