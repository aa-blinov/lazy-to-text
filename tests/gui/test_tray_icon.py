"""Tests for the Qt-native AppTrayIcon."""

import pytest

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QSystemTrayIcon


def _find_action(menu, label_substr: str) -> QAction:
    for action in menu.actions():
        if label_substr.lower() in action.text().lower():
            return action
    raise AssertionError(f"action containing {label_substr!r} not found")


# ---- Construction ----------------------------------------------------------


def test_tray_icon_constructs(qtbot, qapp):
    from app.gui.widgets.tray_icon import AppTrayIcon

    tray = AppTrayIcon(parent=qapp)
    assert tray is not None
    # Tooltip is state-dependent now — default state is ``idle`` so the
    # initial tooltip is the idle one.  ``set_state`` updates it as the
    # backend transitions through recording / processing / model_loading.
    assert tray.toolTip() == "Lazy to Text — idle"


def test_tray_default_state_is_idle(qtbot, qapp):
    from app.gui.widgets.tray_icon import AppTrayIcon

    tray = AppTrayIcon(parent=qapp)
    assert tray.state() == "idle"


def test_tray_has_show_and_quit_actions(qtbot, qapp):
    from app.gui.widgets.tray_icon import AppTrayIcon

    tray = AppTrayIcon(parent=qapp)
    menu = tray.contextMenu()
    assert menu is not None
    assert _find_action(menu, "show") is not None
    assert _find_action(menu, "quit") is not None


# ---- State transitions -----------------------------------------------------


@pytest.mark.parametrize(
    "state", ["idle", "recording", "processing", "model_loading"]
)
def test_set_state_updates_internal_state(qtbot, qapp, state):
    from app.gui.widgets.tray_icon import AppTrayIcon

    tray = AppTrayIcon(parent=qapp)
    tray.set_state(state)
    assert tray.state() == state


def test_set_state_rejects_unknown_value(qtbot, qapp):
    from app.gui.widgets.tray_icon import AppTrayIcon

    tray = AppTrayIcon(parent=qapp)
    with pytest.raises(ValueError):
        tray.set_state("dancing")


@pytest.mark.parametrize(
    ("state", "expected_tooltip"),
    [
        ("idle", "Lazy to Text — idle"),
        ("recording", "Lazy to Text — recording"),
        ("processing", "Lazy to Text — transcribing"),
        ("model_loading", "Lazy to Text — loading model"),
    ],
)
def test_set_state_updates_tooltip(qtbot, qapp, state, expected_tooltip):
    """Hover-tooltip should mirror the current state — particularly
    important on macOS where the menu-bar template icons are
    minimalist shapes (ring / disc / dots / dashed ring) and the
    tooltip is the only place the user can read the human-readable
    name."""
    from app.gui.widgets.tray_icon import AppTrayIcon

    tray = AppTrayIcon(parent=qapp)
    tray.set_state(state)
    assert tray.toolTip() == expected_tooltip


# ---- Signals ---------------------------------------------------------------


def test_show_action_emits_show_requested(qtbot, qapp):
    from app.gui.widgets.tray_icon import AppTrayIcon

    tray = AppTrayIcon(parent=qapp)
    show_action = _find_action(tray.contextMenu(), "show")

    with qtbot.waitSignal(tray.show_requested, timeout=1000):
        show_action.trigger()


def test_quit_action_emits_quit_requested(qtbot, qapp):
    from app.gui.widgets.tray_icon import AppTrayIcon

    tray = AppTrayIcon(parent=qapp)
    quit_action = _find_action(tray.contextMenu(), "quit")

    with qtbot.waitSignal(tray.quit_requested, timeout=1000):
        quit_action.trigger()


def test_left_click_shows_the_window_off_macos(qtbot, qapp, monkeypatch):
    """Windows and Linux: a left click restores the window."""
    import app.gui.widgets.tray_icon as tray_module
    from app.gui.widgets.tray_icon import AppTrayIcon

    monkeypatch.setattr(tray_module.sys, "platform", "win32")
    tray = AppTrayIcon(parent=qapp)

    with qtbot.waitSignal(tray.show_requested, timeout=1000):
        tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)


def test_left_click_on_macos_opens_the_menu_instead_of_showing(qtbot, qapp, monkeypatch):
    """A menu-bar extra is its menu — clicking it must not also act.

    The old behaviour emitted ``show_requested`` from the same click
    that opened the menu, so the window appeared while "Show window"
    was still being drawn: the first click did two things, and the
    menu's own action looked like it did nothing.
    """
    import app.gui.widgets.tray_icon as tray_module
    from app.gui.widgets.tray_icon import AppTrayIcon

    monkeypatch.setattr(tray_module.sys, "platform", "darwin")
    tray = AppTrayIcon(parent=qapp)

    emissions: list[None] = []
    tray.show_requested.connect(lambda: emissions.append(None))

    for reason in (
        QSystemTrayIcon.ActivationReason.Trigger,
        QSystemTrayIcon.ActivationReason.DoubleClick,
    ):
        tray.activated.emit(reason)
    qtbot.wait(50)

    assert emissions == [], (
        "a macOS status-item click must leave the work to the menu"
    )


def test_the_menu_still_shows_the_window_on_macos(qtbot, qapp, monkeypatch):
    """The menu action is the way in on macOS, and it still works."""
    import app.gui.widgets.tray_icon as tray_module
    from app.gui.widgets.tray_icon import AppTrayIcon

    monkeypatch.setattr(tray_module.sys, "platform", "darwin")
    tray = AppTrayIcon(parent=qapp)

    with qtbot.waitSignal(tray.show_requested, timeout=1000):
        tray._menu.actions()[0].trigger()


def test_right_click_activation_does_not_emit_show_requested(qtbot, qapp, monkeypatch):
    import app.gui.widgets.tray_icon as tray_module
    from app.gui.widgets.tray_icon import AppTrayIcon

    monkeypatch.setattr(tray_module.sys, "platform", "win32")
    tray = AppTrayIcon(parent=qapp)

    emissions: list[None] = []
    tray.show_requested.connect(lambda: emissions.append(None))

    # Context (right-click) opens the menu — should not duplicate-emit show.
    tray.activated.emit(QSystemTrayIcon.ActivationReason.Context)
    qtbot.wait(50)
    assert emissions == []
