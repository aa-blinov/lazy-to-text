"""Tests for the focus helper and the eliding label.

Both exist to stop widgets from pushing their parents around: one when
focus moves, the other when text is too long. Neither is reachable
through the widgets' public API, so they are tested directly.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget


def _row(parent: QWidget, *buttons: QPushButton) -> None:
    layout = QVBoxLayout(parent)
    for button in buttons:
        layout.addWidget(button)
    layout.addStretch()


def QApplication_for_testing():  # noqa: N802
    from PySide6.QtWidgets import QApplication

    return QApplication.instance()


def _activate(window: QWidget) -> None:
    """Show and activate, then pump events.

    Offscreen Qt only grants focus to an *active* window, and it only
    becomes active once its children exist — so this has to run after
    the widgets are laid out, not once in a fixture. Calling it before
    the children are added makes every later ``setFocus`` a silent
    no-op and the assertions pass vacuously.
    """
    from PySide6.QtWidgets import QApplication

    window.resize(400, 200)
    window.show()
    window.activateWindow()
    QApplication.processEvents()


@pytest.fixture
def window(qtbot):
    w = QWidget()
    qtbot.addWidget(w)
    return w


# --- release_focus_before ----------------------------------------------


def test_release_focus_before_moves_focus_to_the_named_fallback(window):
    from app.gui.focus import release_focus_before

    victim = QPushButton("Test microphone", window)
    fallback = QPushButton("Device", window)
    _row(window, victim, fallback)
    _activate(window)

    victim.setFocus()
    assert victim.hasFocus()

    assert release_focus_before(victim, fallback) is True
    assert fallback.hasFocus()
    assert not victim.hasFocus()


def test_release_focus_before_is_a_noop_when_focus_is_elsewhere(window):
    from app.gui.focus import release_focus_before

    victim = QPushButton("Test microphone", window)
    other = QPushButton("Device", window)
    fallback = QPushButton("Elsewhere", window)
    _row(window, victim, other, fallback)
    _activate(window)

    other.setFocus()
    assert release_focus_before(victim, fallback) is False
    assert other.hasFocus(), "focus must not move when the victim never had it"


def test_release_focus_before_skips_an_unusable_fallback(window):
    """A hidden or disabled fallback would silently swallow the focus
    move, so the helper falls through to the window instead."""
    from app.gui.focus import release_focus_before

    victim = QPushButton("Victim", window)
    hidden = QPushButton("Hidden", window)
    hidden.setVisible(False)
    _row(window, victim, hidden)
    _activate(window)

    victim.setFocus()
    assert release_focus_before(victim, hidden) is True
    assert not victim.hasFocus()
    assert not hidden.hasFocus()


def test_release_focus_before_without_a_fallback_uses_the_window(window):
    from app.gui.focus import release_focus_before

    victim = QPushButton("Victim", window)
    survivor = QPushButton("Survivor", window)
    _row(window, victim, survivor)
    _activate(window)

    victim.setFocus()
    assert release_focus_before(victim) is True
    assert survivor.hasFocus()


def test_release_focus_before_never_targets_the_victim_itself(window):
    """The window-wide fallback must skip the widget that is about to
    disappear, or the 'neighbour' is the very thing being torn down."""
    from app.gui.focus import release_focus_before

    only = QPushButton("Only", window)
    _row(window, only)
    _activate(window)

    only.setFocus()
    assert release_focus_before(only) is True
    assert not only.hasFocus()


def test_release_focus_before_without_an_app_is_safe(qtbot):
    from PySide6.QtWidgets import QApplication

    from app.gui.focus import release_focus_before

    orphan = QPushButton("Orphan")
    assert release_focus_before(orphan) is False


# --- install_tab_order --------------------------------------------------


def test_install_tab_order_walks_the_given_sequence(window):
    from app.gui.focus import install_tab_order

    buttons = [QPushButton(name, window) for name in "ABCD"]
    _row(window, *buttons)
    _activate(window)
    install_tab_order(*buttons)

    # ``focusNextPrevChild`` is Qt's own tab-chain walk — the same
    # traversal the Tab key performs. Synthesising a KeyPress does not
    # drive it, so this asserts the real chain rather than the call.
    buttons[0].setFocus()
    assert buttons[0].hasFocus()
    # Walk from the *focused* widget: the chain traversal is anchored on
    # a focusable node, not on the window (which has NoFocus itself).
    current = buttons[0]
    for expected in buttons[1:]:
        current.focusNextPrevChild(True)
        current = QApplication_for_testing().focusWidget()
        assert current is expected, (
            f"expected focus on {expected.text()}, got "
            f"{current.text() if current else None}"
        )


def test_install_tab_order_tolerates_missing_entries(window):
    from app.gui.focus import install_tab_order

    a = QPushButton("A", window)
    c = QPushButton("C", window)
    _row(window, a, c)
    _activate(window)
    install_tab_order(a, None, c)  # must not raise
    a.setFocus()
    assert a.hasFocus()


# --- ElidedLabel --------------------------------------------------------


def test_elided_label_truncates_instead_of_widening(qtbot):
    from app.gui.widgets.elided_label import ElidedLabel

    text = "onnx-community/whisper-large-v3-turbo-ONNX-int8-float16-extra-long-repo"
    holder = QWidget()
    qtbot.addWidget(holder)
    holder.resize(220, 80)
    layout = QVBoxLayout(holder)
    label = ElidedLabel(text, holder)
    layout.addWidget(label)
    holder.show()

    assert label.full_text() == text
    assert label.text() != text
    assert "…" in label.text()
    assert label.minimumSizeHint().width() == 0
    assert label.sizeHint().width() == 0
    assert label.toolTip() == text, "the full string must stay reachable"


def test_elided_label_shows_everything_when_it_fits(qtbot):
    from app.gui.widgets.elided_label import ElidedLabel

    holder = QWidget()
    qtbot.addWidget(holder)
    holder.resize(900, 60)
    layout = QHBoxLayout(holder)
    label = ElidedLabel("GigaAM v3 CTC", holder)
    layout.addWidget(label)
    holder.show()

    assert label.text() == "GigaAM v3 CTC"
    assert "…" not in label.text()


def test_elided_label_tracks_resize_in_both_directions(qtbot):
    from app.gui.widgets.elided_label import ElidedLabel

    text = "onnx-community/whisper-large-v3-turbo-ONNX-int8-float16-extra-long-repo"
    holder = QWidget()
    qtbot.addWidget(holder)
    holder.resize(200, 60)
    layout = QVBoxLayout(holder)
    label = ElidedLabel(text, holder)
    layout.addWidget(label)
    holder.show()

    assert "…" in label.text()
    holder.resize(1000, 60)
    assert label.text() == text, "widening must restore the full string"


def test_elided_label_set_text_updates_the_tooltip(qtbot):
    from app.gui.widgets.elided_label import ElidedLabel

    label = ElidedLabel("first")
    label.setText("second")
    assert label.full_text() == "second"
    assert label.toolTip() == "second"
