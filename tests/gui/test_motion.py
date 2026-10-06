"""Tests for the motion preference and the toast's authored entrance.

The preference is stubbed at ``_query_reduce_motion`` rather than at
``reduce_motion`` on purpose: patching the module attribute would only
fix one caller's view of it and leave the others reading the real
machine state. Patching the underlying query puts every caller on the
same answer.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QPlainTextEdit,
    QWidget,
)

from app.gui import motion
from app.gui.motion import (
    fade_out,
    motion_duration_ms,
    motion_offset,
    reduce_motion,
    refresh_reduce_motion,
    rise_and_fade,
)
from app.gui.smooth_scroll import apply_smooth_scroll
from app.gui.widgets import toast as toast_module
from app.gui.widgets.toast import Toast


@pytest.fixture(autouse=True)
def _no_shared_cache():
    """The module-level cache is process state; never let it leak."""
    motion._cache = None
    motion._checked_at = 0.0
    yield
    motion._cache = None
    motion._checked_at = 0.0


@pytest.fixture
def full_motion(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(motion, "_query_reduce_motion", lambda: False)


@pytest.fixture
def reduced_motion(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(motion, "_query_reduce_motion", lambda: True)


@pytest.fixture
def host(qtbot):
    window = QWidget()
    window.resize(900, 620)
    qtbot.addWidget(window)
    window.show()
    QApplication.processEvents()
    return window


def _rest(toast: Toast, host: QWidget) -> QPoint:
    return QPoint(
        host.width() - toast.width() - 16,
        host.height() - toast.height() - 16,
    )


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


# --- the preference ---------------------------------------------------------


def test_the_platform_query_answers_without_raising():
    """The real read must survive this machine's actual toolkit.

    On macOS that means the AppKit property is genuinely reachable —
    an import typo would only ever show up at runtime otherwise.
    """
    assert motion._query_reduce_motion() in (True, False)


def test_reduce_motion_is_reported_by_the_platform_query(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(motion, "_query_reduce_motion", lambda: True)
    assert refresh_reduce_motion() is True
    monkeypatch.setattr(motion, "_query_reduce_motion", lambda: False)
    assert refresh_reduce_motion() is False


def test_reduce_motion_caches_the_platform_call(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def _query() -> bool:
        calls.append(1)
        return False

    monkeypatch.setattr(motion, "_query_reduce_motion", _query)
    for _ in range(5):
        reduce_motion()
    assert len(calls) == 1, (
        "the wheel path calls this per notch; it must not pay per event"
    )


def test_refresh_reduce_motion_drops_the_cache(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def _query() -> bool:
        calls.append(1)
        return True

    monkeypatch.setattr(motion, "_query_reduce_motion", _query)
    assert reduce_motion() is True
    assert reduce_motion() is True
    assert len(calls) == 1
    assert refresh_reduce_motion() is True
    assert len(calls) == 2


def test_duration_and_offset_follow_the_preference(full_motion):
    assert motion_duration_ms(180) == 180
    assert motion_offset(12) == 12


def test_duration_and_offset_collapse_under_reduce_motion(
    full_motion, reduced_motion
):
    assert motion_duration_ms(180) == motion._REDUCED_FADE_MS
    assert motion_offset(12) == 0


# --- the authored sequence --------------------------------------------------


def test_rise_and_fade_animates_both_position_and_opacity(qtbot, full_motion):
    widget = QPlainTextEdit()
    widget.resize(200, 60)
    widget.move(40, 100)
    rest = QPoint(widget.x(), widget.y())

    group = rise_and_fade(widget, offset_px=12, duration_ms=180)
    try:
        assert group.animationCount() == 2
        assert widget.y() == rest.y() + 12, "must start below its resting place"
        effect = widget.graphicsEffect()
        assert isinstance(effect, QGraphicsOpacityEffect)
        assert effect.opacity() == 0.0
        assert group.duration() == 180
    finally:
        group.stop()


def test_rise_and_fade_lands_on_the_resting_position(qtbot, full_motion):
    widget = QPlainTextEdit()
    widget.resize(200, 60)
    widget.move(40, 100)
    rest = QPoint(widget.x(), widget.y())

    group = rise_and_fade(widget, offset_px=12, duration_ms=20)
    try:
        qtbot.wait(150)
        assert (widget.x(), widget.y()) == (rest.x(), rest.y())
        assert widget.graphicsEffect().opacity() == pytest.approx(1.0, abs=0.01)
    finally:
        group.stop()


def test_rise_and_fade_keeps_the_arrival_but_drops_the_travel_under_reduce_motion(
    qtbot, reduced_motion
):
    widget = QPlainTextEdit()
    widget.resize(200, 60)
    widget.move(40, 100)
    rest = QPoint(widget.x(), widget.y())

    group = rise_and_fade(widget, offset_px=12, duration_ms=180)
    try:
        assert group.animationCount() == 1, "no position animation under Reduce Motion"
        assert (widget.x(), widget.y()) == (rest.x(), rest.y())
        assert group.duration() == motion._REDUCED_FADE_MS
        qtbot.wait(200)
        assert widget.graphicsEffect().opacity() == pytest.approx(1.0, abs=0.01)
    finally:
        group.stop()


def test_rise_and_fade_adopts_an_existing_opacity_effect(qtbot, full_motion):
    widget = QPlainTextEdit()
    existing = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(existing)

    group = rise_and_fade(widget)
    try:
        assert widget.graphicsEffect() is existing, (
            "a second effect would replace the caller's and detach it"
        )
    finally:
        group.stop()


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


def test_fade_out_animates_and_never_reaches_below_zero(qtbot, full_motion):
    widget = QPlainTextEdit()
    widget.show()
    group = fade_out(widget, duration_ms=40)
    assert group is not None
    try:
        qtbot.wait(140)
        assert widget.graphicsEffect().opacity() == pytest.approx(0.0, abs=0.01)
    finally:
        group.stop()


def test_fade_out_cuts_instead_of_running_a_sub_frame_fade(reduced_motion):
    assert fade_out(QPlainTextEdit(), duration_ms=120) is None, (
        "the caller must be able to hide immediately"
    )


# --- smooth scroll ----------------------------------------------------------


@pytest.fixture
def scroller(qtbot, request):
    edit = QPlainTextEdit()
    edit.resize(300, 200)
    edit.setPlainText("\n".join(str(i) for i in range(200)))
    qtbot.addWidget(edit)
    edit.show()
    QApplication.processEvents()
    apply_smooth_scroll(edit)
    return edit


def test_scrolling_is_the_same_under_reduce_motion(qtbot, scroller, reduced_motion):
    """The preference no longer reaches the wheel at all.

    It used to be the switch between "eased over 400 ms" and "jump once"
    — which meant the *non*-reduced path was the odd one. With the tween
    gone, scrolling is a single immediate move either way, and the
    accessibility setting has nothing left to cut.
    """
    bar = scroller.verticalScrollBar()

    _wheel(scroller, -120)
    moved = bar.value()
    assert moved > 0, "one notch moves the view at once"

    qtbot.wait(400)
    assert bar.value() == moved, "and nothing keeps running afterwards"


# --- the toast --------------------------------------------------------------


def test_toast_arrives_with_a_rise_and_a_fade(qtbot, host, full_motion):
    toast = Toast(host)
    toast.show_message("Copied to clipboard")
    try:
        assert toast.isVisible()
        assert toast._anim is not None, "the entrance must be an animation, not a cut"
        assert toast.y() > _rest(toast, host).y(), (
            "it starts below the corner it rests in"
        )
    finally:
        toast._stop_anim()


def test_toast_settles_exactly_in_its_corner(qtbot, host, full_motion):
    toast = Toast(host)
    toast.show_message("Copied to clipboard")
    qtbot.wait(300)

    rest = _rest(toast, host)
    assert (toast.x(), toast.y()) == (rest.x(), rest.y())
    assert toast.graphicsEffect().opacity() == pytest.approx(1.0, abs=0.01)


def test_a_second_message_does_not_replay_the_entrance(qtbot, host, full_motion):
    toast = Toast(host)
    toast.show_message("First")
    qtbot.wait(300)
    settled_y = toast.y()

    toast.show_message("Second")

    assert toast._anim is None, "a visible banner updates in place"
    assert toast.isVisible()
    assert toast.y() == settled_y, "no vertical replay"
    # The preview changed, so the banner is a different width — and
    # re-anchors to the corner at its new width rather than drifting.
    rest = _rest(toast, host)
    assert (toast.x(), toast.y()) == (rest.x(), rest.y())
    assert toast.graphicsEffect().opacity() == pytest.approx(1.0, abs=0.01)
    assert "Second" in toast._body.text()


def test_a_message_arriving_mid_timed_departure_restores_the_banner(
    qtbot, host, full_motion
):
    toast = Toast(host)
    toast.show_message("First", duration_ms=500)

    # Wait for the auto-hide timer to fire, then catch the banner while
    # its 120ms departure is still in flight.
    qtbot.waitUntil(lambda: toast._anim is not None, timeout=2000)
    assert toast.isVisible(), "the departure has to be observable while it runs"

    toast.show_message("Second")

    assert toast.isVisible()
    assert toast.graphicsEffect().opacity() == pytest.approx(1.0, abs=0.01)
    rest = _rest(toast, host)
    assert (toast.x(), toast.y()) == (rest.x(), rest.y())

    qtbot.wait(250)
    assert toast.isVisible(), "a half-faded banner must not blink out afterwards"
    assert toast.graphicsEffect().opacity() == pytest.approx(1.0, abs=0.01)


def test_departure_is_faster_than_the_entrance():
    assert toast_module._DEPART_MS < toast_module._ARRIVAL_MS


def test_hide_message_is_synchronous_even_with_full_motion(qtbot, host, full_motion):
    """The explicit verb is not animated.

    It is the call that runs when something decided the confirmation is
    unwanted. A 120 ms residual would leave a ghost over whatever the
    caller opens next, with the hide timer already stopped.
    """
    toast = Toast(host)
    toast.show_message("Copied", duration_ms=10000)

    toast.hide_message()

    assert not toast.isVisible(), "gone when the call returns, not 120ms later"
    assert not toast._timer.isActive()
    assert toast._anim is None


def test_the_timed_departure_cuts_under_reduce_motion(qtbot, host, reduced_motion):
    toast = Toast(host)
    toast.show_message("Copied", duration_ms=500)

    qtbot.waitUntil(lambda: not toast.isVisible(), timeout=2000)
    assert toast._anim is None, "no sub-frame fade under Reduce Motion"


def test_toast_arrives_by_fade_only_under_reduce_motion(
    qtbot, host, reduced_motion
):
    toast = Toast(host)
    toast.show_message("Copied")
    try:
        rest = _rest(toast, host)
        assert toast.y() == rest.y(), "no travel under Reduce Motion"
        assert toast._anim is not None, "the arrival itself is still animated"
    finally:
        toast._stop_anim()


def test_the_auto_hide_timer_leaves_rather_than_blinks(qtbot, host, full_motion):
    toast = Toast(host)
    toast.show_message("Copied", duration_ms=500)
    qtbot.wait(800)

    assert not toast.isVisible()
