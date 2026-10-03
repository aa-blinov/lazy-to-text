"""Browser-like smooth scrolling for Qt scroll areas.

Implements the "FixedStep + COSINE" algorithm from qfluentwidgets
(zhiyiYo/PyQt-Fluent-Widgets).  Each wheel notch is broken into
``_STEPS_TOTAL`` equal-interval ticks whose per-tick displacement
follows a cosine bell curve:

    sub = (cos(x * π / m) + 1) / (2*m) * delta

where x = |step_done - m| and m = _STEPS_TOTAL / 2.  The curve
integrates exactly to ``delta`` so the total scroll distance per
notch is preserved.

Key properties:
- Ease-in-out feel: slow at start and end, peak in the middle.
- Accumulation: rapid notches append independent items to the queue;
  each tick sums contributions from all active items, so fast
  flicking naturally builds momentum.
- **Display-refresh-aware** ticks: the per-instance timer is created
  with a tick interval matching the user's monitor (60 / 144 / 240 Hz),
  so animations don't stutter on high-refresh displays.
- **Reduce Motion aware**: when the OS asks for less movement the
  tween is dropped entirely and each wheel notch is applied as one
  step. 400 ms of travel is the single largest source of motion in
  the app, so this is where the preference has to land.

Usage::

    from app.gui.smooth_scroll import apply_smooth_scroll
    apply_smooth_scroll(my_scroll_area)
"""

from __future__ import annotations

from collections import deque
from math import cos, pi

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QAbstractScrollArea

from app.gui.motion import reduce_motion
from app.gui.refresh_rate import display_refresh_rate, tick_interval_ms

_DURATION_MS = 400            # total animation length per notch
_PX_PER_NOTCH = 40.0          # reduced from 100.0 for more precision
_STEP_RATIO = 1.0             # reduced from 1.5


def _sub_delta(delta: float, steps_left: int, steps_total: int) -> float:
    """Cosine bell contribution for this step."""
    m = steps_total / 2
    x = abs(steps_total - steps_left - m)
    return (cos(x * pi / m) + 1) / (2 * m) * delta


class _SmoothScrollFilter(QObject):
    def __init__(self, area: QAbstractScrollArea) -> None:
        super().__init__(area)
        self._area = area
        # Queue of [remaining_delta_px, steps_left] pairs.
        # Each wheel notch appends one item; all active items contribute
        # to every tick, then items are dropped when steps_left reaches 0.
        self._queue: deque[list[float]] = deque()
        # Sub-pixel remainder carried between ticks — see _tick.
        self._fraction = 0.0

        # Match the display refresh.  ``_DURATION_MS`` is constant so
        # 60 Hz monitors keep the original 24-step animation; 144 Hz
        # monitors get 57 steps of 7 ms each — same feel, smoother
        # rendering.
        fps = display_refresh_rate()
        self._steps_total = max(8, int(round(fps * _DURATION_MS / 1000)))
        self._timer = QTimer(self)
        self._timer.setInterval(tick_interval_ms())
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ timer

    def _tick(self) -> None:
        if not self._queue:
            self._timer.stop()
            self._fraction = 0.0
            return

        total = 0.0
        for item in self._queue:
            step = _sub_delta(item[0], int(item[1]), self._steps_total)
            total += step
            item[1] -= 1

        # Drop exhausted items.
        while self._queue and self._queue[0][1] <= 0:
            self._queue.popleft()

        # Carry the sub-pixel remainder across ticks. Truncating
        # ``bar.value() + total`` independently every tick threw that
        # remainder away, and over the 24 ticks of a 60Hz notch it cost
        # about 9px of the 40px requested — the animation spent its
        # whole budget travelling to a place it never reached, and the
        # view drifted short of where the user scrolled. The curve
        # itself is exact (its sub-deltas sum to ``delta`` to six
        # decimals at 60, 120, 144 and 240Hz); the rounding was the
        # only thing losing the distance.
        self._fraction += total
        whole = int(self._fraction)
        self._fraction -= whole

        bar = self._area.verticalScrollBar()
        target = bar.value() + whole
        clamped = max(bar.minimum(), min(bar.maximum(), target))
        if clamped != target:
            # Hitting an end. The leftover fraction belongs to a
            # distance we are not travelling, so drop it instead of
            # carrying it into the next notch and jumping there.
            self._fraction = 0.0
        bar.setValue(clamped)

    # ----------------------------------------------------------- event filter

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.Wheel:
            return False

        angle = event.angleDelta().y()
        if angle == 0:
            return False

        delta_px = -angle * _PX_PER_NOTCH * _STEP_RATIO / 120.0

        if reduce_motion():
            # Reduce Motion drops the tween, not the scroll. The user
            # still asked for 40px with that notch and must land
            # 40px away — what goes away is 400 ms of travelling to
            # get there. A crossfade is the prescribed substitute for
            # a slide, but there is nothing to cross *between* here:
            # one scroll position simply becomes another, and the
            # correct reduced form of that is the cut.
            #
            # The event is still consumed, so Qt's own step-scroll
            # never runs behind us and doubles the distance.
            self._queue.clear()
            self._timer.stop()
            self._fraction = 0.0
            bar = self._area.verticalScrollBar()
            bar.setValue(
                max(bar.minimum(), min(bar.maximum(), int(bar.value() + delta_px)))
            )
            return True

        self._queue.append([delta_px, float(self._steps_total)])

        if not self._timer.isActive():
            self._timer.start()
        return True


def apply_smooth_scroll(area: QAbstractScrollArea) -> None:
    """Enable qfluentwidgets-style smooth scrolling on *area*."""
    from PySide6.QtWidgets import QAbstractItemView
    if isinstance(area, QAbstractItemView):
        area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    f = _SmoothScrollFilter(area)
    area.viewport().installEventFilter(f)
