"""Native macOS behaviour for a floating window that has to stay on screen.

Qt can ask for "always on top", but not for "on top of another app's
full-screen Space", so the native window is adjusted once it is shown. The
recording overlay, which also carries each dictation's result, uses this.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)


def float_over_full_screen(widget: QWidget) -> bool:
    """Keep an already-shown window on screen above full-screen apps.

    Returns True when the native window was reached and adjusted. Off macOS,
    or off the cocoa platform (offscreen tests), there is nothing to adjust
    and this returns False.
    """
    if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
        return False

    try:
        import objc
        from AppKit import (
            NSApplication,
            NSStatusWindowLevel,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorIgnoresCycle,
            NSWindowCollectionBehaviorStationary,
            NSWindowStyleMaskNonactivatingPanel,
        )

        # PySide6 winId() on macOS is the NSView pointer.
        view_id = int(widget.winId())
        if not view_id:
            return False
        ns_window = objc.objc_object(c_void_p=view_id).window()
        if not ns_window:
            return False

        # A non-activating panel shows without making the app active. An
        # activating window pulls the app forward, and that takes a full-screen
        # Space away from the app the user is working in.
        ns_window.setStyleMask_(
            ns_window.styleMask() | NSWindowStyleMaskNonactivatingPanel
        )
        # 1. Allow window to float over fullscreen apps
        # 2. Allow window to appear on all Spaces/desktops
        # 3. Hide from Cmd+Tab and stationary during swipe
        # MoveToActiveSpace is left out on purpose: it is exclusive with
        # CanJoinAllSpaces, and the pair is not a valid request.
        ns_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorIgnoresCycle
            | NSWindowCollectionBehaviorStationary
        )
        # NSStatusWindowLevel is high enough to be above fullscreen apps but
        # below the Notch/Menu Bar area.
        ns_window.setLevel_(NSStatusWindowLevel)

        # Prevent the window from being hidden when the app is inactive.
        ns_window.setHidesOnDeactivate_(False)
        ns_window.setCanHide_(False)

        # A window of a hidden application is not on screen, and
        # ``orderFrontRegardless`` does not unhide the application — it
        # only orders the window.  The app spends most of its life
        # hidden (its main window sits in the tray), and a capsule that
        # is ordered front into a hidden app is invisible.  Waking the
        # app without activating it is what puts the capsule on screen
        # and leaves the focus where the user is dictating into.
        ns_app = NSApplication.sharedApplication()
        was_hidden = ns_app.isHidden()
        if was_hidden:
            ns_app.unhideWithoutActivation()

        # Force it to front, without activating the app.
        ns_window.orderFrontRegardless()

        # A window that is not on the space the user is looking at is
        # on screen and not visible at the same time. The collection
        # behaviour above makes the window join every space, but a
        # window that was already ordered out stays where it was, so
        # the overlay has to be re-ordered onto the active space.
        on_active_space = True
        try:
            on_active_space = bool(ns_window.isOnActiveSpace())
        except Exception:  # pragma: no cover — defensive
            on_active_space = True
        if not on_active_space:
            log.warning(
                "The overlay window was not on the active space — "
                "re-ordering it onto it"
            )
            ns_window.orderFrontRegardless()

        # Logged on every appearance, not once: the overlay disappears
        # without an error, and the state at the moment it was shown is
        # the only evidence there is. A window of a hidden application
        # reports itself visible while being nowhere on screen, so
        # "hidden" and "on the active space" are the two numbers that
        # tell the two failures apart.
        log.info(
            "Overlay window: hidden=%s policy=%s level=%s visible=%s "
            "on_active_space=%s screen=%s",
            was_hidden,
            ns_app.activationPolicy(),
            ns_window.level(),
            ns_window.isVisible(),
            on_active_space,
            ns_window.screen().localizedName()
            if ns_window.screen() is not None else "?",
        )
        return True
    except Exception:
        # The window still shows without the fullscreen behaviour; the
        # failure goes to the app log, where support can find it.
        log.warning("Floating window behaviour could not be applied", exc_info=True)
        return False
