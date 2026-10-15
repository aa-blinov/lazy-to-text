"""The transcription preview when the main window cannot show it.

The in-window banner belongs to the main window, so it is invisible while
the window is minimised to the Dock or hidden to the tray. The floating
banner is its own window and takes the same message instead.
"""

from PySide6.QtCore import Qt


def test_the_floating_banner_is_its_own_window_that_never_takes_focus(qtbot):
    from app.gui.widgets.toast import Toast

    toast = Toast()
    qtbot.addWidget(toast)

    assert toast.isWindow()
    assert toast.windowFlags() & Qt.WindowType.Tool
    assert toast.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert toast.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert toast.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert toast.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_the_floating_banner_sits_in_the_bottom_right_of_the_users_screen(qtbot):
    from PySide6.QtCore import QAbstractAnimation

    from app.gui.placement import user_screen
    from app.gui.widgets.toast import Toast

    toast = Toast()
    qtbot.addWidget(toast)
    toast.show_message("A transcription long enough to have a real width")
    # The arrival rises into place; measure once it has landed.
    qtbot.waitUntil(
        lambda: toast._anim is None
        or toast._anim.state() == QAbstractAnimation.Stopped,
        timeout=5000,
    )

    area = user_screen().availableGeometry()
    assert toast.isVisible()
    assert area.x() + area.width() - (toast.x() + toast.width()) == 16
    assert area.y() + area.height() - (toast.y() + toast.height()) == 16


def test_the_preview_stays_in_the_window_only_while_it_is_on_screen_and_in_front():
    from app.gui.main_window import preview_in_window

    assert preview_in_window(visible=True, minimised=False, active=True)
    # Minimised to the Dock: still "visible" to Qt, not on screen.
    assert not preview_in_window(visible=True, minimised=True, active=True)
    # Hidden to the tray.
    assert not preview_in_window(visible=False, minimised=False, active=True)
    # Open, but another app is in front.
    assert not preview_in_window(visible=True, minimised=False, active=False)


def test_a_hidden_window_sends_the_preview_to_the_floating_banner(qtbot):
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.hide()

    window.show_transcription_preview("hidden to the tray")

    assert window.floating_toast.isVisible()
    assert not window.toast.isVisible()
