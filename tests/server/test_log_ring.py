"""The runtime's log ring: what a record carries to the Logs screen."""

from __future__ import annotations

import collections
import logging
import re

from app.server.events import bus
from app.server.runtime import _RingHandler


def _record(message="hello", level=logging.INFO, **extra):
    record = logging.LogRecord("app.test", level, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_a_record_carries_its_time_even_though_the_formatter_never_computes_one():
    ring = collections.deque(maxlen=10)

    _RingHandler(ring).emit(_record())

    assert re.fullmatch(r"\d\d:\d\d:\d\d", ring[0]["time"])


def test_the_user_message_flag_and_the_level_reach_the_event():
    ring = collections.deque(maxlen=10)
    sub = bus.subscribe()
    try:
        handler = _RingHandler(ring)
        handler.emit(_record("for you", logging.WARNING, user_message=True))
        handler.emit(_record("bookkeeping"))
        events = []
        while True:
            item = sub.get(timeout=0.2)
            if item is None:
                break
            events.append(item)
    finally:
        sub.close()

    assert ring[0]["user_message"] is True and ring[0]["level"] == "WARNING"
    assert ring[1]["user_message"] is False
    assert [name for name, _ in events if name == "log"] == ["log", "log"]
    assert [r["id"] for r in ring] == [1, 2]
