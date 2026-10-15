"""Where a floating window goes: the screen the user is looking at."""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QCursor, QGuiApplication, QScreen


def user_screen() -> Optional[QScreen]:
    """The screen the user is looking at, or the primary one.

    Dictation is started by a *global* hotkey while the user is inside some
    other app, quite possibly on another display. Anchoring to the primary
    screen put the recording indicator and the delivery confirmation on the
    panel nobody was looking at, so the cursor stands in for the user.

    The cursor is the proxy, not the focus: no cross-platform API reports
    which screen another application's foreground window is on, and macOS
    anchors its own dictation indicator to the cursor for the same reason.
    ``screenAt`` returns ``None`` while a display layout is being rebuilt and
    the cursor briefly sits outside every screen, so the primary screen is the
    fallback rather than a crash on a null dereference.
    """
    app = QGuiApplication.instance()
    if app is None:
        return None
    return app.screenAt(QCursor.pos()) or app.primaryScreen()
