"""One-time tickets for the event stream.

``EventSource`` cannot send an ``Authorization`` header, so the stream has
had to carry the launch token in its URL, which is the one place a token
ends up in a history, a proxy log or a crash report. A ticket is the
narrower thing to put there: random, valid for a few seconds, and worth
nothing after the first stream that presents it. The token itself stays in
headers.

The store is small and bounded; an expired or spent ticket is simply gone.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from typing import Dict

TTL_S = 30.0
_MAX_PENDING = 64

_lock = threading.Lock()
_pending: Dict[str, float] = {}


def issue() -> str:
    """A fresh ticket, valid for :data:`TTL_S` seconds and for one stream."""
    now = time.monotonic()
    ticket = secrets.token_urlsafe(24)
    with _lock:
        for key in [k for k, until in _pending.items() if until <= now]:
            del _pending[key]
        while len(_pending) >= _MAX_PENDING:
            _pending.pop(next(iter(_pending)))
        _pending[ticket] = now + TTL_S
    return ticket


def redeem(candidate: str) -> bool:
    """True once for a live ticket; the ticket is spent either way it is used."""
    if not candidate:
        return False
    now = time.monotonic()
    with _lock:
        found = None
        for key, until in _pending.items():
            if hmac.compare_digest(key.encode("utf-8"), candidate.encode("utf-8", "replace")):
                found = (key, until)
                break
        if found is None:
            return False
        del _pending[found[0]]
        return found[1] > now
