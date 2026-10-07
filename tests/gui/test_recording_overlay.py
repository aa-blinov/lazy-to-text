import sys

import pytest
from PySide6.QtCore import Qt
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


def test_overlay_centers_on_primary_screen(qtbot):
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    overlay.set_state("recording")

    screen = QApplication.primaryScreen()
    rect = screen.availableGeometry()
    expected_center = rect.x() + rect.width() // 2
    actual_center = overlay.frameGeometry().center().x()

    assert abs(actual_center - expected_center) <= 2


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
    assert "cannot confirm" in overlay._body.text()


def test_delivery_confirmation_names_the_shortcut_the_user_must_press(qtbot):
    """For ``copied`` the one fact that changes what to do next is which
    key — and on this platform it is Cmd+V, not Ctrl+V."""
    from app.gui.widgets.recording_overlay import RecordingOverlay

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    expected = "Cmd+V" if sys.platform == "darwin" else "Ctrl+V"

    overlay.show_delivery("copied", f"Press {expected} in your app")

    assert overlay._title.text() == "Copied"
    assert overlay._body.text() == f"Press {expected} in your app"


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
