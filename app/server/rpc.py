"""Method registry for the RPC channel.

A handler is a plain function ``fn(rt, params) -> result`` registered with
:func:`method`. ``rt`` is the :class:`app.server.runtime.Runtime`; ``params``
is the decoded JSON object (never ``None``). The result has to be
JSON-serialisable. Raising :class:`RpcError` produces a structured error
for the renderer; any other exception becomes ``internal`` and is logged
with its traceback, because a handler that fails must never take the
server down with it.

Handlers live in ``app/server/handlers/`` and are imported by
:func:`load_handlers`, so adding a screen's API is adding a file there and
nothing else.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any, Callable, Dict

log = logging.getLogger(__name__)

Handler = Callable[[Any, Dict[str, Any]], Any]

_METHODS: Dict[str, Handler] = {}


class RpcError(Exception):
    """A failure the renderer is expected to show, with a stable code."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def method(name: str) -> Callable[[Handler], Handler]:
    """Register *fn* under *name*. A duplicate name is a programming error."""

    def register(fn: Handler) -> Handler:
        if name in _METHODS:
            raise RuntimeError(f"RPC method {name!r} is registered twice")
        _METHODS[name] = fn
        return fn

    return register


def method_names() -> list[str]:
    return sorted(_METHODS)


def load_handlers() -> None:
    """Import every module in ``app.server.handlers`` once."""
    from app.server import handlers

    for info in pkgutil.iter_modules(handlers.__path__):
        importlib.import_module(f"{handlers.__name__}.{info.name}")


def dispatch(rt: Any, name: str, params: Any) -> Any:
    handler = _METHODS.get(name)
    if handler is None:
        raise RpcError("unknown_method", f"no such method: {name}")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise RpcError("bad_params", "params must be an object")
    return handler(rt, params)


def need(params: Dict[str, Any], key: str, kind: type | tuple = object) -> Any:
    """A required parameter, with a code the renderer can show."""
    if key not in params:
        raise RpcError("bad_params", f"missing parameter: {key}")
    value = params[key]
    if not isinstance(value, kind):
        raise RpcError("bad_params", f"parameter {key} has the wrong type")
    return value
