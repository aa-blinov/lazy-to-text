"""Progress callbacks for model transfers."""

from __future__ import annotations

from typing import Callable, Optional

_progress_callback: Optional[Callable[[int, int, str], None]] = None


def set_progress_callback(
    callback: Optional[Callable[[int, int, str], None]],
) -> None:
    global _progress_callback
    _progress_callback = callback


def report_progress(current: int, total: int, desc: str) -> None:
    callback = _progress_callback
    if callback is None:
        return
    try:
        callback(int(current), int(total), str(desc))
    except Exception:
        return
