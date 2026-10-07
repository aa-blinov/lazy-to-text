"""Small always-on-top recording status overlay.

Unlike the in-window toast, this widget is a separate top-level tool
window so it can stay visible while the main app is hidden or unfocused.
"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


# Long enough to read one line, short enough that the next dictation is
# not queued behind the previous one's confirmation.
_DELIVERY_VISIBLE_MS = 2000

# outcome -> (title, default detail). Every state names what happened in
# the past tense, because that is the question being answered; the detail
# line carries only the fact that changes what to do next.
_DELIVERY_COPY = {
    "pasted": ("Paste sent",
               "Keystroke posted — we cannot confirm the paste"),
    "copied": ("Copied", "Press the paste shortcut in your app"),
    "failed": ("Delivery failed", "Nothing was pasted — the reason is in Logs"),
}


class RecordingOverlay(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        flags = (
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        super().__init__(parent, flags)
        self.setObjectName("RecordingOverlay")
        # This is a separate top-level window, so a screen reader
        # announces it as one. Without a name it is announced as a bare
        # "window", which tells a non-sighted user nothing about the
        # one piece of app feedback that reaches them mid-sentence —
        # so the name carries the state, and ``set_state`` rewrites it.
        self.setAccessibleName("Recording status")
        self.setAccessibleDescription("Idle")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        if sys.platform == "darwin":
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._surface = QFrame(self)
        self._surface.setObjectName("RecordingOverlaySurface")
        self._surface.setProperty("role", "recording-overlay-surface")
        self._surface.setMinimumHeight(56)
        root.addWidget(self._surface)

        surface_layout = QHBoxLayout(self._surface)
        surface_layout.setContentsMargins(16, 12, 16, 12)
        surface_layout.setSpacing(12)

        self._dot = QFrame(self._surface)
        self._dot.setObjectName("RecordingOverlayDot")
        self._dot.setProperty("role", "recording-overlay-dot")
        self._dot.setFixedSize(14, 14)
        # The dot is the only element here that carries state by colour
        # alone. Naming it keeps a screen reader from announcing a
        # colour where it should announce a state, and stops the bare
        # QFrame from turning up as an anonymous node.
        self._dot.setAccessibleName("Recording indicator")
        surface_layout.addWidget(self._dot, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)

        self._title = QLabel("", self._surface)
        self._title.setObjectName("RecordingOverlayTitle")
        self._title.setProperty("role", "recording-overlay-title")
        text_col.addWidget(self._title)

        self._body = QLabel("", self._surface)
        self._body.setObjectName("RecordingOverlayBody")
        self._body.setProperty("role", "recording-overlay-body")
        text_col.addWidget(self._body)

        surface_layout.addLayout(text_col, 1)

        self._state = "idle"
        self._delivery_active = False
        self._delivery_timer = QTimer(self)
        self._delivery_timer.setSingleShot(True)
        self._delivery_timer.timeout.connect(self._on_delivery_elapsed)
        self.hide()

    def state(self) -> str:
        return self._state

    def show_delivery(self, outcome: str, detail: str = "") -> None:
        """Report what happened to the dictation, for as long as it matters.

        Until this existed the loop ended in silence: the overlay hid on
        ``idle`` and the text landed in whatever window had focus, so the
        one question the user actually has — "did it go in?" — had no
        answer anywhere. The user is looking at their document, not at
        this app, so the answer has to arrive here.

        ``outcome`` is one of:

        ``"pasted"``
            We asked the focused app to paste and nothing reported a
            failure. Deliberately *not* "Pasted": no platform API
            confirms that the target app pasted, and the rest of the app
            already refuses to claim it (see ``_send_paste_combo``).
        ``"copied"``
            The text is on the clipboard and nobody pasted it.
        ``"failed"``
            The text did not reach the clipboard or the focused app.

        ``detail`` carries the one fact that changes the decision — the
        word count, or the paste shortcut when the user has to press it
        themselves. Left empty, the default line for that outcome is used.

        Holding the overlay open here is the whole point, so ``idle``
        no longer hides while a delivery confirmation is on screen: the
        state machine reaches ``idle`` within milliseconds of this call,
        and an unconditional hide would win that race every time.
        """
        copy = _DELIVERY_COPY.get(outcome)
        if copy is None:
            return
        title, fallback_detail = copy
        self._delivery_active = True
        self._state = outcome
        self._title.setText(title)
        self._body.setText(detail or fallback_detail)
        self._dot.setProperty("state", outcome)
        self.setAccessibleDescription(f"{title} — {self._body.text()}")
        self._dot.setAccessibleDescription(title)
        self._refresh_styles()
        self._show_overlay()
        self._delivery_timer.start(_DELIVERY_VISIBLE_MS)

    def _on_delivery_elapsed(self) -> None:
        self._delivery_active = False
        self._state = "idle"
        self.setAccessibleDescription("Idle")
        self.hide()

    def set_state(self, state: str) -> None:
        state = (state or "").strip().lower()
        if state == "idle" and self._delivery_active:
            # The state machine reaches ``idle`` within milliseconds of
            # ``show_delivery`` — the transcription pipeline finishes and
            # clears its flag right after reporting. An unconditional hide
            # here would win that race every single time and the
            # confirmation would never be seen.
            return
        self._delivery_timer.stop()
        self._delivery_active = False
        if state == "recording":
            self._state = "recording"
            self._title.setText("Recording")
            self._body.setText("Speak now")
            self._dot.setProperty("state", "recording")
            self.setAccessibleDescription("Recording — speak now")
            self._dot.setAccessibleDescription("Recording")
            self._refresh_styles()
            self._show_overlay()
            return
        if state == "processing":
            self._state = "processing"
            self._title.setText("Processing")
            self._body.setText("Transcribing speech")
            self._dot.setProperty("state", "processing")
            self.setAccessibleDescription("Processing — transcribing speech")
            self._dot.setAccessibleDescription("Processing")
            self._refresh_styles()
            self._show_overlay()
            return
        self._state = "idle"
        self.setAccessibleDescription("Idle")
        self.hide()

    def _show_overlay(self) -> None:
        self.adjustSize()
        self._reposition()
        self.show()
        if sys.platform == "darwin":
            self._apply_mac_window_behaviors()

    def _apply_mac_window_behaviors(self) -> None:
        """Apply native macOS behaviors for visibility in fullscreen apps."""
        if hasattr(self, "_mac_behaviors_applied"):
            return

        # Skip if not on a live Cocoa display (e.g. during headless tests)
        if QGuiApplication.platformName() != "cocoa":
            return

        try:
            import objc
            from AppKit import (
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
                NSWindowCollectionBehaviorMoveToActiveSpace,
                NSWindowCollectionBehaviorIgnoresCycle,
                NSWindowCollectionBehaviorStationary,
                NSStatusWindowLevel,
            )

            # PySide6 winId() on macOS is the NSView pointer.
            view_id = int(self.winId())
            if not view_id:
                return

            # Wrap as objc object and find its window.
            ns_view = objc.objc_object(c_void_p=view_id)
            ns_window = ns_view.window()

            if ns_window:
                # 1. Allow window to float over fullscreen apps
                # 2. Allow window to appear on all Spaces/desktops
                # 3. Ensure it moves to the active space immediately
                # 4. Hide from Cmd+Tab and stationary during swipe
                ns_window.setCollectionBehavior_(
                    NSWindowCollectionBehaviorCanJoinAllSpaces
                    | NSWindowCollectionBehaviorFullScreenAuxiliary
                    | NSWindowCollectionBehaviorMoveToActiveSpace
                    | NSWindowCollectionBehaviorIgnoresCycle
                    | NSWindowCollectionBehaviorStationary
                )
                
                # NSStatusWindowLevel is high enough to be above fullscreen 
                # apps but below the Notch/Menu Bar area. 
                ns_window.setLevel_(NSStatusWindowLevel)

                # Prevent the window from being hidden when the app is inactive
                ns_window.setHidesOnDeactivate_(False)
                ns_window.setCanHide_(False)
                
                # Force it to front
                ns_window.orderFrontRegardless()

            self._mac_behaviors_applied = True
        except Exception as e:
            # Silently fail but log to a temp file for debugging
            with open("/tmp/ltt-overlay.log", "a") as f:
                f.write(f"Overlay behavior error: {e}\n")
            pass

    def _reposition(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        margin_top = 28
        x = rect.x() + max(0, (rect.width() - self.width()) // 2)
        y = rect.y() + margin_top
        self.move(x, y)

    def _refresh_styles(self) -> None:
        self.style().unpolish(self._dot)
        self.style().polish(self._dot)
        self.style().unpolish(self._surface)
        self.style().polish(self._surface)
