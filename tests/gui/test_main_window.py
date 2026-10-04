"""Tests for the MainWindow shell."""

from PySide6.QtWidgets import QApplication, QLineEdit, QStackedWidget


def test_main_window_instantiates(qtbot):
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "Lazy to Text"


def test_main_window_has_sidebar(qtbot):
    from app.gui.main_window import MainWindow
    from app.gui.widgets.sidebar import Sidebar

    window = MainWindow()
    qtbot.addWidget(window)
    assert isinstance(window.sidebar, Sidebar)


def test_main_window_has_stack_with_view_per_nav_item(qtbot):
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert isinstance(window.stack, QStackedWidget)
    assert window.stack.count() == len(window.sidebar.items())


def test_main_window_default_view_matches_default_sidebar_key(qtbot):
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    default_key = window.sidebar.active_key()
    assert window.stack.currentWidget() is window.get_view(default_key)


def test_main_window_switches_view_when_sidebar_changes(qtbot):
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)

    window.sidebar.set_active("history")
    assert window.stack.currentWidget() is window.get_view("history")

    window.sidebar.set_active("logs")
    assert window.stack.currentWidget() is window.get_view("logs")


def test_main_window_get_view_raises_on_unknown_key(qtbot):
    import pytest

    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)

    with pytest.raises(KeyError):
        window.get_view("nope")


def test_main_window_uses_models_view_for_models_key(qtbot):
    from app.gui.main_window import MainWindow
    from app.gui.views.models_view import ModelsView

    window = MainWindow()
    qtbot.addWidget(window)
    assert isinstance(window.get_view("models"), ModelsView)
    assert window.models_view is window.get_view("models")


def test_main_window_uses_logs_view_for_logs_key(qtbot):
    from app.gui.main_window import MainWindow
    from app.gui.views.logs_view import LogsView

    window = MainWindow()
    qtbot.addWidget(window)
    assert isinstance(window.get_view("logs"), LogsView)
    assert window.logs_view is window.get_view("logs")


def test_main_window_uses_shortcuts_view_for_shortcuts_key(qtbot):
    from app.gui.main_window import MainWindow
    from app.gui.views.shortcuts_view import ShortcutsView

    window = MainWindow()
    qtbot.addWidget(window)
    assert isinstance(window.get_view("shortcuts"), ShortcutsView)
    assert window.shortcuts_view is window.get_view("shortcuts")


def test_main_window_has_topbar(qtbot):
    from app.gui.main_window import MainWindow
    from app.gui.widgets.topbar import TopBar

    window = MainWindow()
    qtbot.addWidget(window)
    assert isinstance(window.topbar, TopBar)
    assert window.topbar.parent() is not None


def test_main_window_has_recording_overlay(qtbot):
    from app.gui.main_window import MainWindow
    from app.gui.widgets.recording_overlay import RecordingOverlay

    window = MainWindow()
    qtbot.addWidget(window)
    assert isinstance(window.recording_overlay, RecordingOverlay)
    assert window.recording_overlay.parent() is None


def test_main_window_uses_history_view_for_history_key(qtbot):
    from app.gui.main_window import MainWindow
    from app.gui.views.history_view import HistoryView

    window = MainWindow()
    qtbot.addWidget(window)
    assert isinstance(window.get_view("history"), HistoryView)
    assert window.history_view is window.get_view("history")


def test_main_window_no_placeholders_remain(qtbot):
    """All nav keys now map to real views."""
    from app.gui.main_window import MainWindow
    from app.gui.views.placeholder import PlaceholderView

    window = MainWindow()
    qtbot.addWidget(window)
    for key in window.sidebar.items():
        assert not isinstance(window.get_view(key), PlaceholderView), key


# ---- Close-to-tray behaviour -----------------------------------------------


def test_close_event_closes_normally_by_default(qtbot):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QCloseEvent

    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_close_event_hides_when_close_to_tray_enabled(qtbot):
    from PySide6.QtGui import QCloseEvent

    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    window.set_close_to_tray(True)

    event = QCloseEvent()
    window.closeEvent(event)

    assert not event.isAccepted()  # close was vetoed
    assert not window.isVisible()  # but the window was hidden


def test_close_event_emits_hidden_to_tray_signal(qtbot):
    from PySide6.QtGui import QCloseEvent

    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window.set_close_to_tray(True)

    with qtbot.waitSignal(window.hidden_to_tray, timeout=1000):
        window.closeEvent(QCloseEvent())


def test_request_quit_overrides_close_to_tray(qtbot):
    from PySide6.QtGui import QCloseEvent

    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.set_close_to_tray(True)

    # Mark the window as quitting — the next close should be honoured.
    window.request_quit()

    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_set_close_to_tray_can_be_disabled(qtbot):
    from PySide6.QtGui import QCloseEvent

    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.set_close_to_tray(True)
    window.set_close_to_tray(False)

    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_main_window_ctrl_n_shortcuts_switch_tabs(qtbot):
    """Ctrl+1..5 should jump to Models / Transcribe / Settings /
    History / Logs in sidebar order — keyboard-driven nav for power
    users."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    nav_keys = list(window.sidebar.items())
    target_keys = ["models", "transcribe", "history", "logs", "shortcuts"]

    for index, expected_key in enumerate(target_keys[: len(nav_keys)]):
        # Find the QShortcut that matches Ctrl+{index+1} and trigger it.
        matched = None
        for sc in window._shortcuts:
            if sc.key().toString(QKeySequence.NativeText).lower().endswith(
                str(index + 1)
            ):
                matched = sc
                break
        assert matched is not None
        matched.activated.emit()
        assert window.sidebar.active_key() == expected_key


def test_find_action_uses_the_platform_standard_key(qtbot):
    """Find must be ``StandardKey.Find``, not a literal sequence.

    Three of the five views have a search field. Binding ``Cmd+F`` by
    hand would be wrong on Windows; ``StandardKey`` is what makes one
    line correct on both, the same mechanism the app menu already uses
    for ``Cmd+,`` and ``Cmd+Q``.

    Two assertions, because one is not enough. The runtime comparison
    only proves the binding is right on *this* platform — and under
    ``QT_QPA_PLATFORM=offscreen`` Qt reports a non-macOS keyboard, so
    ``StandardKey.Find`` resolves to ``Ctrl+F`` there and a hardcoded
    ``QKeySequence("Ctrl+F")`` is indistinguishable from the real
    thing. The source check is what catches the literal; the runtime
    check is what catches a wrong sequence on the machine it runs on.
    """
    from pathlib import Path

    from PySide6.QtGui import QKeySequence
    from app.gui import main_window as mw
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window._find_action.shortcut() == QKeySequence.StandardKey.Find

    source = Path(mw.__file__).read_text(encoding="utf-8")
    assert "StandardKey.Find" in source, (
        "Find must be bound through StandardKey so macOS gets Cmd+F "
        "and Windows gets Ctrl+F without a branch"
    )


def test_find_action_is_enabled_only_where_there_is_something_to_find(qtbot):
    """A shortcut that silently does nothing is worse than no shortcut.

    Models, History and Logs can be searched. Transcribe and Shortcuts
    cannot, so Find goes dead there rather than pretending — and it has
    to follow the view, not be decided once at startup.
    """
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    for key in ("models", "history", "logs"):
        window._activate_nav(key)
        assert window._find_action.isEnabled(), key

    for key in ("transcribe", "shortcuts"):
        window._activate_nav(key)
        assert not window._find_action.isEnabled(), key

    # ...and back again, so the sync is not a one-shot at construction.
    window._activate_nav("models")
    assert window._find_action.isEnabled()


def test_find_focuses_the_active_view_search_field(qtbot):
    """The point of the accelerator: the caret lands in the search box."""
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    # Offscreen Qt only grants focus to an *active* window; without
    # this every ``setFocus`` below is a silent no-op and the test
    # would pass for the wrong reason — or fail for a reason that has
    # nothing to do with the accelerator.
    window.activateWindow()
    QApplication.processEvents()

    for key, obj_name in (
        ("models", "ModelsSearchEdit"),
        ("history", "HistorySearchEdit"),
        ("logs", "LogsSearchEdit"),
    ):
        window._activate_nav(key)
        field = window.get_view(key).findChild(QLineEdit, obj_name)
        assert field is not None, obj_name
        field.clearFocus()
        window._find_action.trigger()
        assert field.hasFocus(), f"{key}: Find did not reach {obj_name}"


def test_find_never_fires_on_a_view_without_a_search_field(qtbot):
    """A view that cannot be searched must not answer to Find at all.

    ``focus_search`` is the contract: the window duck-types on it rather
    than holding a table of view keys, so a view that lacks the method
    is simply not findable.
    """
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window._activate_nav("transcribe")
    assert window._searchable_view("transcribe") is None
    assert not window._find_action.isEnabled()
    # Triggering anyway (a stale enabled state, say) must be inert
    # rather than raising.
    window._find_action.trigger()


def test_every_searchable_view_exposes_focus_search(qtbot):
    """The duck-typed contract, asserted from the window's side.

    Without this, adding a search field to a view would silently not
    earn an accelerator — the failure mode is an absent method, which
    nothing else would notice.
    """
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)

    searchable = [
        key
        for key in window._views
        if window._searchable_view(key) is not None
    ]
    assert sorted(searchable) == ["history", "logs", "models"]
