"""Progress callbacks for model transfers."""

from __future__ import annotations

import inspect
from typing import Callable, Optional

_progress_callback: Optional[Callable[..., None]] = None


def set_progress_callback(
    callback: Optional[Callable[..., None]],
) -> None:
    global _progress_callback
    _progress_callback = callback


def report_progress(current: int, total: int, desc: str, details=None) -> None:
    callback = _progress_callback
    if callback is None:
        return
    try:
        try:
            supports_details = len(inspect.signature(callback).parameters) >= 4
        except (TypeError, ValueError):
            supports_details = True
        args = (int(current), int(total), str(desc))
        if supports_details:
            try:
                callback(*args, details or {})
            except TypeError:
                callback(*args)
        else:
            callback(*args)
    except Exception:
        return
