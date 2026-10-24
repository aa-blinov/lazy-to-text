"""Configuration as the renderer may see it: credentials replaced by a flag.

A credential has no business in a window, least of all in the always-on-top
capsule, which loads the same snapshot as the main window. What a screen
needs is whether a key is set and a way to replace or remove it, so every
``api_key`` and ``token`` in a section is dropped and an ``api_key_set`` /
``token_set`` boolean takes its place. Recursive, because the profiles are
a list of mappings.
"""

from __future__ import annotations

from typing import Any

_SECRET_KEYS = {"api_key": "api_key_set", "token": "token_set"}


def is_set(value: Any) -> bool:
    return bool(isinstance(value, str) and value.strip())


def public(value: Any) -> Any:
    """A deep copy of *value* with every credential replaced by its flag."""
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            if key in _SECRET_KEYS:
                out[_SECRET_KEYS[key]] = is_set(item)
            else:
                out[key] = public(item)
        return out
    if isinstance(value, list):
        return [public(item) for item in value]
    return value
