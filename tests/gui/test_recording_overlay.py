import sys

import pytest
from PySide6.QtCore import Qt, QRect
from PySide6.QtWidgets import QApplication


def test_overlay_starts_hidden(qtbot):
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    assert overlay.state() == "idle"
    assert not overlay.isVisible()
    assert overlay.testAttribute(Qt.WA_TranslucentBackground)
    if sys.platform == "darwin":
        assert overlay.testAttribute(Qt.WA_MacAlwaysShowToolWindow)


def test_overlay_shows_recording_state(qtbot):
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.set_state("recording")

    assert overlay.isVisible()
    assert overlay.state() == "recording"
    assert overlay._title.text() == "Recording"
    assert overlay._body.text() == "Speak now"
    assert overlay._surface.isVisible()


def test_overlay_shows_processing_state(qtbot):
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.set_state("processing")

    assert overlay.isVisible()
    assert overlay.state() == "processing"
    assert overlay._title.text() == "Processing"
    assert overlay._body.text() == "Transcribing speech"
    assert overlay._dot.property("state") == "processing"


def test_overlay_hides_on_idle(qtbot):
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    overlay.set_state("recording")

    overlay.set_state("idle")

    assert overlay.state() == "idle"
    assert not overlay.isVisible()


def test_overlay_sits_in_the_bottom_right_of_the_primary_screen(qtbot):
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    overlay.set_state("recording")

    _assert_bottom_right(overlay, QApplication.primaryScreen(), "primary screen")


def test_overlay_window_carries_its_state_to_assistive_tech(qtbot):
    """The overlay is a separate top-level window, so a screen reader
    announces it as one. Unnamed, it arrives as a bare "window" — which
    tells a non-sighted user nothing about the only piece of app
    feedback that reaches them mid-sentence."""
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    assert overlay.accessibleName()
    assert overlay.accessibleDescription() == "Idle"

    overlay.set_state("recording")
    assert "Recording" in overlay.accessibleDescription()

    overlay.set_state("processing")
    assert "Processing" in overlay.accessibleDescription()

    overlay.set_state("idle")
    assert overlay.accessibleDescription() == "Idle"


def test_overlay_dot_is_named_not_left_as_an_anonymous_colour(qtbot):
    """The dot is the one element that signals state by colour alone.
    A screen reader must get a state, not a hue."""
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    dot = overlay.findChild(type(overlay._dot), "RecordingOverlayDot")
    assert dot is not None
    assert dot.accessibleName()


# ---- delivery confirmation -------------------------------------------------


def test_overlay_confirms_a_delivery_that_went_out(qtbot):
    """The whole point of the change: dictation used to end in silence.

    The user is looking at their document when this appears, so the
    answer to "did it go in?" has to land here rather than in a log
    line nobody has open.
    """
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("pasted")

    assert overlay.isVisible()
    assert overlay.state() == "pasted"
    assert overlay._title.text() == "Paste sent"
    assert overlay._dot.property("state") == "pasted"


def test_delivery_confirmation_says_paste_sent_not_pasted(qtbot):
    """``_send_paste_combo`` only ever reports that keystrokes went out —
    no platform API confirms the target app pasted. Claiming "Pasted"
    here would be the app asserting something it cannot know."""
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("pasted")

    assert "past" in overlay._title.text().lower()
    assert "sent" in overlay._title.text().lower()
    assert overlay._body.text() == "Copied to clipboard"


def test_copied_title_names_the_shortcut_the_user_must_press(qtbot):
    """For ``copied`` the one fact that changes what to do next is which
    key — and on this platform it is Cmd+V, not Ctrl+V. It goes in the
    title, so the line under it is free for the text itself."""
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    expected = "Cmd+V" if sys.platform == "darwin" else "Ctrl+V"

    overlay.show_delivery("copied", expected, "hello there")

    assert overlay._title.text() == f"Copied — press {expected}"
    assert overlay._body.text() == "hello there"


def test_the_result_popup_carries_the_text_that_was_delivered(qtbot):
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("pasted", "", "Привет, мир")

    assert overlay._title.text() == "Paste sent"
    assert overlay._body.text() == "Привет, мир"


def test_a_multi_line_dictation_reads_as_one_line(qtbot):
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("copied", "Cmd+V", "first line\nsecond   line\n")

    assert overlay._body.text() == "first line second line"


def test_a_failed_delivery_shows_the_reason_and_never_the_text(qtbot):
    """Nothing went anywhere, so the words are not a result to show; the
    reason is what the user needs next."""
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("failed", "", "words that never landed")

    assert overlay._title.text() == "Delivery failed"
    assert "Logs" in overlay._body.text()
    assert "never landed" not in overlay._body.text()


def test_a_long_result_is_cut_to_one_line_and_the_screen_reader_hears_all_of_it(
    qtbot, themed
):
    """The eye gets a line that fits; the assistive description keeps every
    word, because a cut sentence is only a cut for someone who can see it."""
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    transcript = "слово " * 120

    overlay.show_delivery("copied", "Cmd+V", transcript)

    body = overlay._body.text()
    spoken = " ".join(transcript.split())
    assert body.endswith("…")
    assert body != spoken
    assert overlay._body.fontMetrics().horizontalAdvance(body) <= overlay._text_budget()
    assert spoken in overlay.accessibleDescription()


@pytest.mark.parametrize("before", ["idle", "processing"])
def test_a_result_is_in_its_corner_once_the_layout_has_settled(
    qtbot, monkeypatch, themed, before
):
    """The popup was placed by the width it had before the result's text
    arrived. The layout settles on the event loop, so that width was the
    narrow one, and the result then grew the popup to the right, past the
    edge of the screen. The loop is run here the way the app runs it, and
    the final size is what gets measured.

    A long transcript on a narrow display makes this visible: the text is
    cut to what the screen leaves room for, so the popup ends in its corner
    whatever was said.
    """
    from app.gui.widgets import recording_overlay as mod
    from app.gui.widgets.recording_overlay import RecordingOverlay

    narrow = _FakeScreen("narrow", QRect(0, 0, 400, 300))
    layout = _ScreenLayout(narrow, cursor_on=narrow)
    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    _patch_screens(monkeypatch, mod, layout)
    if before == "processing":
        overlay.set_state("processing")

    overlay.show_delivery("copied", "Cmd+V", "слово " * 80)
    QApplication.processEvents()

    assert overlay.width() == overlay.sizeHint().width()
    _assert_bottom_right(overlay, narrow, f"a result shown from {before}")
    assert overlay.frameGeometry().x() >= narrow.availableGeometry().x() + 16


def test_delivery_failure_names_the_log_as_where_the_reason_is(qtbot):
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("failed")

    assert overlay.state() == "failed"
    assert overlay._dot.property("state") == "failed"
    assert "Logs" in overlay._body.text()


def test_idle_does_not_swallow_the_delivery_confirmation(qtbot):
    """The race this guard exists for.

    ``show_delivery`` is called from the pipeline thread; the state
    machine reaches ``idle`` milliseconds later as the same pipeline
    finishes. An unconditional hide on ``idle`` wins that race every
    single time, so the confirmation is never seen.
    """
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("pasted")
    overlay.set_state("idle")

    assert overlay.isVisible(), "idle hid the confirmation it had just shown"
    assert overlay.state() == "pasted"


def test_delivery_confirmation_closes_itself_when_its_time_is_up(
    qtbot, monkeypatch
):
    """Holding the overlay open must not hold it open forever — the next
    dictation has to be able to take the screen back.

    The duration is patched rather than waited out: the test is about the
    timer being wired to the confirmation, not about how long a human
    needs to read one line.
    """
    from app.gui.widgets import recording_overlay as module
    from app.gui.widgets.recording_overlay import RecordingOverlay

    monkeypatch.setattr(module, "_DELIVERY_VISIBLE_MS", 1)

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    overlay.show_delivery("copied")

    qtbot.waitUntil(lambda: not overlay.isVisible(), timeout=2000)

    assert overlay.state() == "idle"
    assert overlay.accessibleDescription() == "Idle"
    assert module._DELIVERY_VISIBLE_MS > 0


def test_idle_hides_normally_once_the_confirmation_has_expired(qtbot):
    """The guard is scoped to an *active* confirmation. Without the
    expiry, "idle does not hide" would leak into ordinary operation and
    the overlay would sit on screen permanently."""
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("copied")
    overlay._on_delivery_elapsed()
    overlay.set_state("recording")
    overlay.set_state("idle")

    assert not overlay.isVisible()


def test_a_new_recording_supersedes_a_live_confirmation(qtbot):
    """Hiding the timer stop is the other half of the guard: the moment
    the user starts talking again the confirmation is stale and its
    timer must not fire later to blank the recording state."""
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("copied")
    overlay.set_state("recording")

    assert overlay.state() == "recording"
    assert not overlay._delivery_timer.isActive()


def test_unknown_delivery_outcome_changes_nothing(qtbot):
    """A vocabulary slip should not blank the overlay the user is
    currently being told something on."""
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    overlay.show_delivery("pasted")

    overlay.show_delivery("banana")

    assert overlay.state() == "pasted"
    assert overlay.isVisible()


def test_delivery_confirmation_reaches_assistive_tech(qtbot):
    """Same argument as the recording states: the confirmation is often
    the only app feedback a non-sighted user gets, so it has to be a
    state and not a colour."""
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("copied")

    assert "Copied" in overlay.accessibleDescription()
    assert overlay._dot.accessibleDescription() == "Copied"


# ---- the delivery states actually paint ------------------------------------


@pytest.fixture
def themed(qtbot):
    """The real stylesheet, restored afterwards.

    Without it every rule below is satisfied by the base fill, which is
    why ``palette()`` is not the witness here and rendered pixels are.
    """
    from PySide6.QtWidgets import QApplication
    from app.gui.theme import load_stylesheet

    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(load_stylesheet("dark"))
    try:
        yield app
    finally:
        app.setStyleSheet(previous)


def _dot_colour(overlay):
    """Centre pixel of the dot, as rendered."""
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    image = overlay._dot.grab().toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2)


def _name(colour):
    return colour.name().lower()


def test_the_confirmed_state_is_green(qtbot, themed):
    """``pasted`` and ``copied`` are the two good answers and they have
    to look like one, not like a third thing."""
    from app.gui.theme import TOKENS
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("pasted")
    assert _name(_dot_colour(overlay)) == TOKENS.colors["success"].lower()

    overlay.show_delivery("copied")
    assert _name(_dot_colour(overlay)) == TOKENS.colors["success"].lower()


def test_the_failed_state_is_red(qtbot, themed):
    from app.gui.theme import TOKENS
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.show_delivery("failed")

    assert _name(_dot_colour(overlay)) == TOKENS.colors["danger"].lower()


def test_the_recording_states_keep_their_own_colours(qtbot, themed):
    """The delivery rules are additive — they must not have swallowed
    the two states that were already there."""
    from app.gui.theme import TOKENS
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    overlay.set_state("recording")
    assert _name(_dot_colour(overlay)) == TOKENS.colors["danger"].lower()

    overlay.set_state("processing")
    assert _name(_dot_colour(overlay)) == TOKENS.colors["warning"].lower()


def test_an_unstated_dot_does_not_look_like_a_live_recording(qtbot, themed):
    """The base fill is what the dot paints before it is given a state.

    It used to be danger, which doubled as the recording colour and made
    the ``[state="failed"]`` rule a copy of the base rather than a rule
    of its own. Pinning the base is what keeps that from coming back.
    """
    from app.gui.theme import TOKENS
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    assert _name(_dot_colour(overlay)) == TOKENS.colors["text_muted"].lower()
    assert TOKENS.colors["text_muted"].lower() != (
        TOKENS.colors["danger"].lower()
    )


# ---------------------------------------------------------------------------
# More than one display
# ---------------------------------------------------------------------------

class _FakeScreen:
    """The only part of ``QScreen`` the placement decision reads.

    Real multi-display setups cannot be built here — the offscreen Qt
    platform plugin reports exactly one screen on every CI leg — so the
    display *arrangement* is stood in for and the geometry is asserted
    on the real widget. What is under test is which screen the overlay
    picks, not how Qt enumerates them.
    """

    def __init__(self, name: str, rect) -> None:
        self._name = name
        self._rect = rect

    def name(self) -> str:
        return self._name

    def availableGeometry(self):
        return self._rect


class _ScreenLayout:
    """Stands in for ``QGuiApplication`` with two screens attached.

    ``screens`` is a list rather than a fixed pair so a test can model a
    display being unplugged — which is the whole point of one of them.
    """

    def __init__(self, *screens, cursor_on=None):
        self.attached = list(screens)
        self.cursor_on = cursor_on if cursor_on is not None else (
            screens[0] if screens else None
        )

    def instance(self):
        return self

    def platformName(self) -> str:
        # Keeps the macOS AppKit branch out of the way; the widget checks
        # this before reaching for Cocoa objects that headless never has.
        return "offscreen"

    def screenAt(self, _pos):
        return self.cursor_on

    def screens(self):
        return self.attached

    def primaryScreen(self):
        return self.attached[0] if self.attached else None


def _assert_bottom_right(overlay, screen, why: str) -> None:
    """The capsule sits in the bottom-right corner of ``screen``'s usable area."""
    from app.gui.placement import FLOATING_MARGIN_PX

    area = screen.availableGeometry()
    frame = overlay.frameGeometry()
    expected = (
        area.x() + area.width() - frame.width() - FLOATING_MARGIN_PX,
        area.y() + area.height() - frame.height() - FLOATING_MARGIN_PX,
    )
    assert (frame.x(), frame.y()) == expected, f"{why}: {frame} not in the corner of {area}"


def _patch_screens(monkeypatch, overlay_module, layout) -> None:
    """Route the overlay and the shared placement helper to ``layout``."""
    from app.gui import placement

    monkeypatch.setattr(overlay_module, "QGuiApplication", layout)
    monkeypatch.setattr(placement, "QGuiApplication", layout)


class _Signal:
    def connect(self, slot):
        pass


_BUILT_IN = _FakeScreen("built-in", QRect(0, 0, 1512, 982))
_EXTERNAL = _FakeScreen("external", QRect(1512, 0, 2560, 1440))


def test_the_overlay_lands_on_the_display_the_user_is_working_on(
    qtbot, monkeypatch
):
    """Dictation is a global hotkey: the user is in another app, quite
    possibly on another monitor.

    The overlay used to anchor to the primary screen, so on a docked
    laptop the recording indicator and the delivery confirmation landed
    on the built-in panel while the user worked on the external one. The
    confirmation was delivered and missed, which is the single outcome
    this widget exists to prevent.
    """
    from app.gui.widgets import recording_overlay as mod
    from app.gui.widgets.recording_overlay import RecordingOverlay

    layout = _ScreenLayout(_BUILT_IN, _EXTERNAL, cursor_on=_EXTERNAL)
    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    _patch_screens(monkeypatch, mod, layout)
    overlay.set_state("recording")

    geometry = overlay.frameGeometry()
    _assert_bottom_right(overlay, _EXTERNAL, "the cursor was on the external display")
    assert _EXTERNAL.availableGeometry().contains(geometry.topLeft())


def test_the_overlay_does_not_chase_the_cursor_mid_dictation(qtbot, monkeypatch):
    """States arrive seconds apart and the user is moving while they do.

    Re-resolving the screen on every state change made the overlay hop
    displays between "Recording" and "Processing" for a dictation the
    user never left. The anchor is captured once per appearance and held
    until the overlay goes down.
    """
    from app.gui.widgets import recording_overlay as mod
    from app.gui.widgets.recording_overlay import RecordingOverlay

    layout = _ScreenLayout(_BUILT_IN, _EXTERNAL, cursor_on=_EXTERNAL)
    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    _patch_screens(monkeypatch, mod, layout)
    overlay.set_state("recording")

    # The user wandered over to the laptop panel mid-dictation.
    layout.cursor_on = _BUILT_IN
    overlay.set_state("processing")

    # The popup keeps its display. Its width follows the words on it, so its
    # left edge may move; its corner on that display must not.
    _assert_bottom_right(overlay, _EXTERNAL, "the anchor should not move")


def test_a_new_dictation_follows_the_cursor_again(qtbot, monkeypatch):
    """The anchor is per appearance, not for the life of the process.

    Holding it past ``idle`` would pin every dictation after the first to
    whichever screen the user happened to be on that time — the overlay
    would be correct once and wrong for the rest of the session.
    """
    from app.gui.widgets import recording_overlay as mod
    from app.gui.widgets.recording_overlay import RecordingOverlay

    layout = _ScreenLayout(_BUILT_IN, _EXTERNAL, cursor_on=_EXTERNAL)
    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    _patch_screens(monkeypatch, mod, layout)
    overlay.set_state("recording")
    assert overlay._screen is _EXTERNAL

    overlay.set_state("idle")
    assert not overlay.isVisible()
    # Hidden holds no anchor. ``_show_overlay`` would re-resolve anyway,
    # so this is not observable in the geometry — it is observable as a
    # dangling reference: a ``QScreen`` the window manager is free to
    # delete at the next display change, reachable from the next caller
    # that repositions while hidden.
    assert overlay._screen is None

    layout.cursor_on = _BUILT_IN
    overlay.set_state("recording")

    _assert_bottom_right(overlay, _BUILT_IN, "the built-in display")


def test_unplugging_the_display_the_overlay_sits_on_re_anchors_it(
    qtbot, monkeypatch
):
    """A dock pulled out from under a live dictation used to strand it.

    After a removal the window manager has nowhere sensible to leave a
    window that belonged to the screen that just went away, so the one
    piece of feedback the user is waiting for can end up off every
    display.
    """
    from app.gui.widgets import recording_overlay as mod
    from app.gui.widgets.recording_overlay import RecordingOverlay

    layout = _ScreenLayout(_BUILT_IN, _EXTERNAL, cursor_on=_EXTERNAL)
    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    _patch_screens(monkeypatch, mod, layout)
    overlay.set_state("recording")
    assert overlay._screen is _EXTERNAL

    # The external display goes away, and the cursor comes back to the
    # built-in panel with the rest of the user.
    layout.attached = [_BUILT_IN]
    layout.cursor_on = _BUILT_IN
    overlay._on_screen_layout_changed(None)

    assert overlay._screen is _BUILT_IN
    _assert_bottom_right(overlay, _BUILT_IN, "the built-in display")
    assert _BUILT_IN.availableGeometry().contains(overlay.frameGeometry().topLeft())


def test_the_overlay_falls_back_to_the_primary_screen_when_the_cursor_is_nowhere(
    qtbot, monkeypatch
):
    """``screenAt`` returns ``None`` while a display layout is rebuilt and
    the cursor sits outside every screen. That is a transient state, and
    the overlay has to survive it rather than dereference ``None``."""
    from app.gui.widgets import recording_overlay as mod
    from app.gui.widgets.recording_overlay import RecordingOverlay

    layout = _ScreenLayout(_BUILT_IN, _EXTERNAL, cursor_on=None)
    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)

    _patch_screens(monkeypatch, mod, layout)
    overlay.set_state("recording")

    assert overlay.isVisible()
    _assert_bottom_right(overlay, _BUILT_IN, "the built-in display")
