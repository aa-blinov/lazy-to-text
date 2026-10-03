"""Tests for the motion preference and the toast's authored entrance.

The preference is stubbed at ``_query_reduce_motion`` rather than at
``reduce_motion`` on purpose: ``smooth_scroll`` imports ``reduce_motion``
by name, so patching the module attribute would only fix the toast's
view of it and leave the wheel path reading the real machine state.
Patching the underlying query puts every caller on the same answer.
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
from app.gui.smooth_scroll import _PX_PER_NOTCH, apply_smooth_scroll
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


def _wheel(scroll, angle_y: int) -> None:
    event = QWheelEvent(
        QPoint(10, 10),
        QPoint(10, 10),
        QPoint(0, 0),
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


def test_the_cosine_curve_sums_to_the_full_notch():
    """The curve is exact; only the per-tick rounding was lossy.

    Pinned as a property of the easing itself, so a future rewrite
    cannot quietly start eating distance.
    """
    from app.gui.smooth_scroll import _sub_delta

    for fps in (60, 120, 144, 240):
        steps = max(8, int(round(fps * 0.4)))
        total = sum(_sub_delta(40.0, s, steps) for s in range(steps, 0, -1))
        assert total == pytest.approx(40.0, abs=1e-6), f"{fps}Hz"


def test_smooth_scroll_keeps_the_sub_pixel_remainder_across_ticks(
    qtbot, scroller, full_motion
):
    """A notch lands on the pixel, not a few pixels short of it."""
    bar = scroller.verticalScrollBar()
    _wheel(scroller, -120)
    qtbot.wait(700)
    assert bar.value() == int(_PX_PER_NOTCH)

    # And the carry does not leak into the next notch as a jump.
    _wheel(scroller, -120)
    qtbot.wait(700)
    assert bar.value() == int(_PX_PER_NOTCH) * 2


def test_a_notch_that_hits_the_end_does_not_carry_a_fraction_forward(
    qtbot, scroller, full_motion
):
    bar = scroller.verticalScrollBar()
    bar.setValue(bar.maximum())
    scroller.verticalScrollBar().setValue(bar.maximum())

    _wheel(scroller, -120)  # already at the bottom, clamps
    qtbot.wait(700)
    assert bar.value() == bar.maximum()

    # Scroll back up; a stale fraction would offset the first notch.
    bar.setValue(0)
    _wheel(scroller, 120)
    qtbot.wait(700)
    assert bar.value() == 0


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


def test_smooth_scroll_applies_the_notch_immediately_under_reduce_motion(
    qtbot, scroller, reduced_motion
):
    bar = scroller.verticalScrollBar()

    _wheel(scroller, -120)  # negative angleDelta scrolls down
    assert bar.value() == pytest.approx(int(_PX_PER_NOTCH), abs=2), (
        "one step, not eased over 400ms"
    )

    settled = bar.value()
    qtbot.wait(500)  # well past the tween we expect NOT to run
    assert bar.value() == settled, "nothing may keep moving afterwards"


def test_smooth_scroll_still_animates_normally_without_the_preference(
    qtbot, scroller, full_motion
):
    bar = scroller.verticalScrollBar()

    _wheel(scroller, -120)
    # The cosine bell starts flat — the first tick contributes exactly
    # zero — so "part way" has to be sampled mid-flight, not at once.
    assert bar.value() == 0

    qtbot.wait(150)
    mid = bar.value()
    assert 0 < mid < int(_PX_PER_NOTCH), (
        "mid-flight the tween has only travelled part way"
    )

    qtbot.wait(700)
    # The cosine curve's sub-deltas sum to exactly ``delta`` — verified
    # to six decimals at 60/120/144/240Hz — so the tween must land on
    # the notch it was asked for, not merely near it. This used to
    # settle around 31/40 because every tick truncated its own
    # sub-pixel remainder away.
    assert bar.value() == int(_PX_PER_NOTCH), "and it must not undershoot or overshoot"


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
