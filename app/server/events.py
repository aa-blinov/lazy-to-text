"""Fan-out of server events to every connected renderer.

Producers call :func:`emit` from any thread. Each subscriber owns a
bounded queue, so a renderer that stopped reading (a hidden window, a
suspended laptop) loses its oldest events instead of growing the server's
memory without bound.

*Sticky* events keep their last payload and are replayed to a new
subscriber. A window opened after the model finished loading must not
have to wait for the next state change to learn what the state is.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Dict, Iterable, Optional, Tuple

_QUEUE_SIZE = 512


class Subscription:
    def __init__(self, bus: "EventBus") -> None:
        self._bus = bus
        self.queue: "queue.Queue[Tuple[str, str]]" = queue.Queue(_QUEUE_SIZE)

    def get(self, timeout: float) -> Optional[Tuple[str, str]]:
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._bus._drop(self)


class EventBus:
    def __init__(self, sticky: Iterable[str] = ()) -> None:
        self._lock = threading.Lock()
        self._subs: list[Subscription] = []
        self._sticky_names = set(sticky)
        self._last: Dict[str, str] = {}
        # Events that are not replayed to a new subscriber but whose last
        # payload can be asked for (``app.last_events``): an outcome that
        # arrives while no renderer is connected is otherwise gone.
        self._keep_names: set[str] = set()
        self._kept: Dict[str, Tuple[float, str]] = {}

    def add_sticky(self, *names: str) -> None:
        with self._lock:
            self._sticky_names.update(names)

    def keep_last(self, *names: str) -> None:
        """Remember the last payload of these events without replaying it."""
        with self._lock:
            self._keep_names.update(names)

    def last(self) -> Dict[str, Dict[str, Any]]:
        """``{name: {"at": epoch_seconds, "data": payload}}`` of kept events."""
        with self._lock:
            kept = dict(self._kept)
        return {
            name: {"at": at, "data": json.loads(payload)}
            for name, (at, payload) in kept.items()
        }

    def emit(self, name: str, data: Any = None) -> None:
        payload = json.dumps(data, default=str, ensure_ascii=False)
        with self._lock:
            if name in self._sticky_names:
                self._last[name] = payload
            if name in self._keep_names:
                self._kept[name] = (time.time(), payload)
            targets = list(self._subs)
        for sub in targets:
            _offer(sub.queue, (name, payload))

    def subscribe(self) -> Subscription:
        sub = Subscription(self)
        with self._lock:
            replay = list(self._last.items())
            self._subs.append(sub)
        for item in replay:
            _offer(sub.queue, item)
        return sub

    def _drop(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    @property
    def subscribers(self) -> int:
        with self._lock:
            return len(self._subs)


def _offer(q: "queue.Queue[Tuple[str, str]]", item: Tuple[str, str]) -> None:
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        try:
            q.put_nowait(item)
        except queue.Full:
            pass


bus = EventBus()
