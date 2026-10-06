"""Platform-native scrolling for Qt scroll areas.

The wheel is left alone. This module used to install an event filter
that broke every notch into 24 eased steps over 400 ms, which felt
wrong on a trackpad — macOS already delivers pixel deltas and scroll
phases for exactly that job, and Qt's documentation says to apply
``pixelDelta()`` directly:

    ``pixelDelta`` contains the scrolling distance in pixels on screen
    [...] but to provide a more native feel, you should prefer
    ``pixelDelta()`` on platforms where it's available.

    — QWheelEvent, https://doc.qt.io/qt-6/qwheelevent.html

The old filter also read only ``angleDelta()`` — a mouse-wheel signal,
not a trackpad one — and always returned ``True``, so Qt's own scrolling
never ran at all: the platform's momentum was replaced by our tween
rather than complemented by it. That is what made the scroll feel
custom.

Dropping the tween alone was not enough, and measuring is why. Sent at
the viewport, one wheel notch moved:

    QTextEdit         60 px   (singleStep 20)
    QPlainTextEdit     3 px   (singleStep  1)
    QListWidget        3 px   (singleStep  1)

Qt scrolls by ``wheelScrollLines()`` × ``singleStep``, and on the two
widgets where ``singleStep`` is left at 1 that is three *pixels* per
notch — unusable with a mouse wheel. The tween had been papering over
exactly this. ``QTextEdit`` was already right and the tween made it
worse: 40px, smeared over 400 ms.

So there are three jobs here, and all of them are configuration rather
than animation:

- item views scroll per pixel instead of per item, which is what makes
  a table leap whole rows under a cheap wheel;
- a degenerate ``singleStep`` is raised to one line, so a notch travels
  a sensible distance;
- the wheel event itself is never touched.

    apply_smooth_scroll(my_scroll_area)

No animation, no timer, no refresh-rate coupling, no events consumed.
"""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QAbstractScrollArea


def apply_smooth_scroll(area: QAbstractScrollArea) -> None:
    """Scroll *area* per pixel, at a sane step, and leave the wheel to Qt.

    ``setVerticalScrollMode`` exists only on ``QAbstractItemView``
    subclasses — measured on the Qt 6 binding in this project,
    ``QTextEdit``, ``QPlainTextEdit`` and ``QScrollArea`` have no such
    property — so those are left alone there. All of them have a
    scrollbar, and that is where the step is fixed.
    """
    if isinstance(area, QAbstractItemView):
        mode = QAbstractItemView.ScrollMode.ScrollPerPixel
        area.setVerticalScrollMode(mode)
        area.setHorizontalScrollMode(mode)

    # One line of content is what a wheel step should cover. Only ever
    # raised: a widget that already sets a real step (QTextEdit uses
    # the font height) keeps its own value.
    line = area.fontMetrics().height()
    bar = area.verticalScrollBar()
    if bar.singleStep() < line:
        bar.setSingleStep(line)
