"""The transcription preview when the main window cannot show it.

The in-window banner belongs to the main window, so it is invisible while
the window is minimised to the Dock or hidden to the tray. The floating
banner is its own window and takes the same message instead.
"""

import pytest
from PySide6.QtCore import Qt


@pytest.fixture
def themed(qtbot):
    """The application stylesheet, as the app runs with it: backings are
    painted by it, so a test of what the user sees needs it too."""
    from PySide6.QtWidgets import QApplication

    from app.gui.theme import load_stylesheet

    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(load_stylesheet("dark"))
    yield app
    app.setStyleSheet(previous)


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


def _let_the_arrival_land(qtbot, toast) -> None:
    from PySide6.QtCore import QAbstractAnimation

    qtbot.waitUntil(
        lambda: toast._anim is None
        or toast._anim.state() == QAbstractAnimation.Stopped,
        timeout=5000,
    )


def test_the_floating_banner_is_drawn_on_a_backing_plate(qtbot, themed):
    from app.gui.widgets.toast import Toast

    toast = Toast()
    qtbot.addWidget(toast)
    toast.show_message("Copied text on a plate")
    _let_the_arrival_land(qtbot, toast)

    image = toast.grab().toImage()
    plate = toast._plate.geometry()
    # Just inside the plate's left edge, halfway down: the backing, not the desktop.
    assert image.pixelColor(plate.x() + 3, plate.y() + plate.height() // 2).alpha() == 255


def test_the_preview_plate_has_the_same_height_as_the_recording_capsule(qtbot, themed):
    from app.gui.placement import FLOATING_PLATE_HEIGHT_PX
    from app.gui.widgets.recording_overlay import RecordingOverlay
    from app.gui.widgets.toast import Toast

    overlay = RecordingOverlay()
    qtbot.addWidget(overlay)
    overlay.set_state("recording")
    toast = Toast()
    qtbot.addWidget(toast)
    toast.show_message("one line of text")
    _let_the_arrival_land(qtbot, toast)

    assert overlay._surface.minimumHeight() == FLOATING_PLATE_HEIGHT_PX
    assert toast._plate.minimumHeight() == FLOATING_PLATE_HEIGHT_PX


def test_the_preview_stacks_just_above_the_capsule_while_both_are_up(qtbot, themed):
    from app.gui.main_window import MainWindow
    from app.gui.placement import FLOATING_GAP_PX

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.hide()
    window.recording_overlay.set_state("recording")

    window.show_transcription_preview("stacked above the capsule")
    # The banner rises into place from 12 px below; measure once it has landed.
    _let_the_arrival_land(qtbot, window.floating_toast)

    capsule = window.recording_overlay.frameGeometry()
    banner = window.floating_toast.frameGeometry()
    assert banner.y() + banner.height() + FLOATING_GAP_PX == capsule.y()
    assert banner.x() + banner.width() == capsule.x() + capsule.width()
