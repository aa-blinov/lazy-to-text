"""Whether the app shows a Dock icon, decided by what is on screen.

macOS keeps the activation policy per process, not per window, so the
Dock icon cannot belong to the main window alone. The recording overlay
needs the accessory policy to float over another app's full-screen
Space; the main window wants the regular policy to have a Dock icon and
Cmd-Tab entry. The two are reconciled by time: regular while the main
window is up and nothing is being dictated, accessory otherwise.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtGui import QGuiApplication

log = logging.getLogger(__name__)


def wants_dock_icon(main_visible: bool, overlay_visible: bool) -> bool:
    """The policy rule, kept free of Qt and AppKit so it can be tested."""
    return main_visible and not overlay_visible


def apply_dock_presence(main_visible: bool, overlay_visible: bool) -> None:
    """Switch the process between regular and accessory activation.

    No-op off macOS and off the cocoa platform (offscreen tests), where
    there is no NSApplication to change.
    """
    if sys.platform != "darwin":
        return
    if QGuiApplication.platformName() != "cocoa":
        return

    try:
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyAccessory,
            NSApplicationActivationPolicyRegular,
        )

        app = NSApplication.sharedApplication()
        wanted = (
            NSApplicationActivationPolicyRegular
            if wants_dock_icon(main_visible, overlay_visible)
            else NSApplicationActivationPolicyAccessory
        )
        if app.activationPolicy() != wanted:
            app.setActivationPolicy_(wanted)
    except Exception:
        # The Dock icon is cosmetic next to dictation itself; a failed
        # policy switch must never take the recording down with it.
        log.warning("Could not change the Dock icon policy", exc_info=True)
