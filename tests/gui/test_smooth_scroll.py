"""Tests for the smooth-scroll helper: a wheel notch moves the view at once.

The helper's job is the item view's per-pixel mode and a usable wheel step.
Everything else is left to Qt, and the tests pin both halves.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QWidget

from app.gui.smooth_scroll import apply_smooth_scroll


@pytest.fixture
def scroller(qtbot):
    edit = QPlainTextEdit()
    edit.resize(300, 200)
    edit.setPlainText("\n".join(str(i) for i in range(200)))
    qtbot.addWidget(edit)
    edit.show()
    QApplication.processEvents()
    apply_smooth_scroll(edit)
    return edit


def _wheel(scroll, angle_y: int, pixel_y: int = 0) -> None:
    """Send one wheel event at the widget's viewport.

    ``pixel_y`` reproduces the macOS trackpad shape, where a real event
    carries a pixel delta *and* a synthesised angle delta together.
    """
    event = QWheelEvent(
        QPoint(10, 10),
        QPoint(10, 10),
        QPoint(0, pixel_y),
        QPoint(0, angle_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(scroll.viewport(), event)
    QApplication.processEvents()


def test_per_pixel_mode_is_set_on_item_views(qtbot):
    """Per-pixel is the one setting the helper still touches.

    Item views default to per-*item*, which is what makes a table leap
    whole rows under a cheap mouse wheel. Text edits and scroll areas
    have no scroll-mode property at all and already move per pixel, so
    the helper has to leave them alone rather than poke an API that is
    not there.
    """
    from PySide6.QtWidgets import QAbstractItemView, QListWidget

    view = QListWidget()
    qtbot.addWidget(view)
    apply_smooth_scroll(view)

    mode = QAbstractItemView.ScrollMode.ScrollPerPixel
    assert view.verticalScrollMode() == mode
    assert view.horizontalScrollMode() == mode


def test_a_degenerate_wheel_step_is_raised_to_one_line(qtbot):
    """Without this a notch moves three *pixels*.

    Qt scrolls by ``wheelScrollLines()`` × ``singleStep``, and
    ``QPlainTextEdit`` leaves ``singleStep`` at 1 — measured, one notch
    then travels 3px where ``QTextEdit`` travels 60px. The old tween
    covered that up with its own 40px; dropping it without fixing the
    step would have made the wheel worse, not better.
    """
    from PySide6.QtWidgets import QPlainTextEdit

    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("\n".join(str(i) for i in range(300)))
    edit.show()
    QApplication.processEvents()

    assert edit.verticalScrollBar().singleStep() == 1, (
        "precondition: this widget ships a degenerate wheel step"
    )
    apply_smooth_scroll(edit)

    line = edit.fontMetrics().height()
    assert edit.verticalScrollBar().singleStep() == line


def test_a_widget_that_already_has_a_step_keeps_it(qtbot):
    """Only ever raised. ``QTextEdit`` sets the font height itself and
    must not be nudged downwards to match a different widget."""
    from PySide6.QtWidgets import QTextEdit

    edit = QTextEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("\n".join(str(i) for i in range(300)))
    edit.show()
    QApplication.processEvents()

    before = edit.verticalScrollBar().singleStep()
    assert before > 1, "precondition: this widget steps a line at a time"
    apply_smooth_scroll(edit)
    assert edit.verticalScrollBar().singleStep() == before


def test_text_and_scroll_area_widgets_gain_no_scroll_mode(qtbot):
    """Guarded rather than assumed.

    A bare ``setVerticalScrollMode`` call raises ``AttributeError`` on
    ``QPlainTextEdit`` and ``QScrollArea`` — which is exactly the error
    that surfaced while this was being rewritten.
    """
    from PySide6.QtWidgets import QPlainTextEdit, QScrollArea

    for make in (QPlainTextEdit, QScrollArea):
        widget = make()
        qtbot.addWidget(widget)
        assert not hasattr(widget, "setVerticalScrollMode"), (
            f"{type(widget).__name__} grew a scroll mode — the guard in "
            f"apply_smooth_scroll can now reach it and should"
        )
        apply_smooth_scroll(widget)  # must not raise


def test_a_trackpad_delta_scrolls_immediately_by_its_pixel_distance(
    qtbot, scroller
):
    """The macOS trackpad shape: pixel delta *and* angle delta together.

    The tween read only ``angleDelta``, so a trackpad got 40px smeared
    over 400 ms instead of the pixels the finger actually moved. Qt's
    documentation is explicit that ``pixelDelta()`` is the signal to
    apply directly on platforms that have it, and the old filter
    swallowed the event before Qt could.
    """
    bar = scroller.verticalScrollBar()
    _wheel(scroller, angle_y=-120, pixel_y=-23)

    moved = bar.value()
    assert moved > 0, "the trackpad delta must move the view at all"

    settled = moved
    qtbot.wait(500)
    assert bar.value() == settled, (
        "one trackpad event must land at once — nothing may keep "
        "moving afterwards"
    )


def test_a_mouse_notch_moves_the_view_immediately(qtbot, scroller):
    """No easing, no ramp, no first tick that contributes zero."""
    bar = scroller.verticalScrollBar()
    _wheel(scroller, -120)

    moved = bar.value()
    assert moved > 0, "a notch must take effect on the spot"

    qtbot.wait(500)
    assert bar.value() == moved, "and must already be settled"


def test_two_notches_travel_twice_as_far(qtbot, scroller):
    """Distance is proportional to the input, not to an animation."""
    bar = scroller.verticalScrollBar()

    _wheel(scroller, -120)
    first = bar.value()
    _wheel(scroller, -120)
    second = bar.value()

    assert second > first
    assert second - first == pytest.approx(first, rel=0.15), (
        "the second notch should travel what the first did"
    )


def test_a_wheel_that_hits_the_end_stays_at_the_end(qtbot, scroller):
    """Clamping is Qt's job now — there is no carried remainder to leak."""
    bar = scroller.verticalScrollBar()
    bar.setValue(bar.maximum())

    _wheel(scroller, -120)
    qtbot.wait(300)
    assert bar.value() == bar.maximum()

    bar.setValue(0)
    _wheel(scroller, 120)
    qtbot.wait(300)
    assert bar.value() == 0


def test_the_helper_leaves_the_wheel_to_the_platform(scroller):
    """No event filter may be installed by the helper.

    The old one always returned ``True``, which meant Qt's native
    scrolling never ran at all — the platform's momentum was replaced
    by our tween rather than complemented by it. Pinned structurally,
    because the behavioural tests above would pass against a filter
    that merely tweened quickly.
    """
    from PySide6.QtWidgets import QPlainTextEdit

    fresh = QPlainTextEdit()
    apply_smooth_scroll(fresh)
    # A QObject child on the viewport is what the old filter was;
    # Qt installs no such thing of its own here.
    foreign = [
        child
        for child in fresh.viewport().children()
        if not isinstance(child, QWidget) and type(child).__module__.startswith("app.")
    ]
    assert foreign == [], (
        f"the helper attached {foreign} to the viewport; the wheel must "
        f"be left to Qt"
    )
