"""Where a floating window goes: the screen the user is looking at.

Every floating message (the recording capsule and the transcription preview)
sits in the bottom-right corner of that screen, on the same backing plate and
at the same height, so one corner carries all of the app's feedback.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor, QGuiApplication, QScreen

# The backing plate's height, shared by the recording capsule and the
# preview, so the two read as one stack.
FLOATING_PLATE_HEIGHT_PX = 56

# Distance from the screen's available edges to the stack.
FLOATING_MARGIN_PX = 16

# Space between two stacked floating messages.
FLOATING_GAP_PX = 8


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


def bottom_right_position(
    width: int, height: int, screen: QScreen, *, lift_px: int = 0
) -> QPoint:
    """Top-left corner for a floating window in the bottom-right of ``screen``.

    ``lift_px`` raises the window above the bottom edge, to stack it over
    another floating message.
    """
    area = screen.availableGeometry()
    x = area.x() + area.width() - width - FLOATING_MARGIN_PX
    y = area.y() + area.height() - height - FLOATING_MARGIN_PX - lift_px
    return QPoint(max(area.x() + FLOATING_MARGIN_PX, x), max(area.y(), y))
