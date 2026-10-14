"""Small always-on-top recording status overlay.

Unlike the in-window toast, this widget is a separate top-level tool
window so it can stay visible while the main app is hidden or unfocused.
"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QCoreApplication, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QScreen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.language import bus


# Long enough to read one line, short enough that the next dictation is
# not queued behind the previous one's confirmation.
_DELIVERY_VISIBLE_MS = 2000

# How far below the top of the screen's available area the overlay sits.
# A constant rather than an inline literal because the fallback path for
# "no screen at all" reuses it, and two copies of 28 that drift apart
# would move the overlay when the display layout changes.
_OVERLAY_TOP_MARGIN = 28

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
    # The Dock icon follows whether this is up (see ``dock_presence``),
    # so the main window needs to hear about every show and hide.
    visibility_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        flags = (
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        super().__init__(parent, flags)
        self.setObjectName("RecordingOverlay")
        bus.language_changed.connect(self._retranslate)
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

        # The screen this appearance belongs to. Captured when the
        # overlay goes up and held until it goes down, so the delivery
        # confirmation stays where the recording indicator was instead
        # of following a mouse the user moved while dictating.
        self._screen: Optional[QScreen] = None

        # A display can be unplugged, or the layout rebuilt, while the
        # overlay is up. Left unhandled, the window is left wherever the
        # window manager put it — which after an unplug can be off every
        # screen, holding the one piece of feedback the user is waiting
        # for.
        #
        # Connected once per overlay rather than per appearance because
        # ``MainWindow`` builds exactly one overlay and holds it for the
        # life of the window, so this is one pair of connections for the
        # life of the process. (Disconnection on destroy was not
        # measurable here — PySide6 exposes no way to fire
        # ``screenRemoved`` by hand — so it is not claimed as a
        # mechanism; it does not need to be, at this ownership.)
        app = QGuiApplication.instance()
        if app is not None:
            app.screenRemoved.connect(self._on_screen_layout_changed)
            app.screenAdded.connect(self._on_screen_layout_changed)

        self.hide()

    def state(self) -> str:
        return self._state

    def _set_copy(self, title: str, body: str, *, translate_body: bool = True) -> None:
        self._copy = (title, body, translate_body)
        self._render_copy()

    def _render_copy(self) -> None:
        title, body, translate_body = self._copy
        self._title.setText(QCoreApplication.translate("RecordingOverlay", title))
        self._body.setText(
            QCoreApplication.translate("RecordingOverlay", body)
            if translate_body else body
        )

    def _retranslate(self, _language: str = "") -> None:
        # Only the visible copy is re-read; the accessible name and
        # description keep the English until they are translated too.
        if getattr(self, "_copy", None) is not None:
            self._render_copy()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().hideEvent(event)
        self.visibility_changed.emit(False)

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
        # ``detail`` is a runtime message (a reason, an error), not a source
        # string, so it is shown as given and never looked up for translation.
        if detail:
            self._set_copy(title, detail, translate_body=False)
        else:
            self._set_copy(title, fallback_detail)
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
        self._screen = None

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
            self._set_copy("Recording", "Speak now")
            self._dot.setProperty("state", "recording")
            self.setAccessibleDescription("Recording — speak now")
            self._dot.setAccessibleDescription("Recording")
            self._refresh_styles()
            self._show_overlay()
            return
        if state == "processing":
            self._state = "processing"
            self._set_copy("Processing", "Transcribing speech")
            self._dot.setProperty("state", "processing")
            self.setAccessibleDescription("Processing — transcribing speech")
            self._dot.setAccessibleDescription("Processing")
            self._refresh_styles()
            self._show_overlay()
            return
        self._state = "idle"
        self.setAccessibleDescription("Idle")
        self.hide()
        self._screen = None

    def _show_overlay(self) -> None:
        self.adjustSize()
        if not self.isVisible():
            # Anchored once per appearance. Re-resolving on every state
            # change made the overlay chase the cursor across a recording
            # — the states arrive seconds apart, and the user is moving.
            self._screen = self._user_screen()
        self._reposition()
        self.show()
        if sys.platform == "darwin":
            self._apply_mac_window_behaviors()

    def _user_screen(self) -> Optional[QScreen]:
        """The screen the user is looking at, or the primary one.

        Dictation is started by a *global* hotkey while the user is
        inside some other app, quite possibly on another display. The
        overlay used to anchor to the primary screen, so on a laptop
        docked to an external display the recording indicator and the
        delivery confirmation landed on the panel nobody was looking at
        — technically delivered, practically invisible, which is the one
        outcome this widget exists to prevent.

        The cursor is the proxy, not the focus: no cross-platform API
        reports which screen another application's foreground window is
        on, and macOS anchors its own dictation indicator to the cursor
        for the same reason. ``screenAt`` returns ``None`` while a
        display layout is being rebuilt and the cursor briefly sits
        outside every screen, so the primary screen is the fallback
        rather than a crash on a null dereference.
        """
        app = QGuiApplication.instance()
        if app is None:
            return None
        return app.screenAt(QCursor.pos()) or app.primaryScreen()

    def _on_screen_layout_changed(self, *_args) -> None:
        """Re-anchor when the display layout changes under the overlay."""
        if not self.isVisible():
            return
        app = QGuiApplication.instance()
        if app is None:
            return
        # The anchor may be the screen that just went away. Qt removes it
        # from ``screens()`` before the handler runs, so membership is the
        # test — not the screen's geometry, which is already stale by the
        # time anyone asks.
        if self._screen is None or self._screen not in app.screens():
            self._screen = self._user_screen()
        self._reposition()

    def _observe_space_changes(self) -> None:
        """Re-show the overlay when the user moves to another Space.

        A window joined to all Spaces is not re-raised on a Space that
        appears after it was shown, so the overlay is re-ordered each time
        the active Space changes while it is up. Registered once.
        """
        if getattr(self, "_space_observer", None) is not None:
            return
        from AppKit import NSWorkspace, NSWorkspaceActiveSpaceDidChangeNotification

        center = NSWorkspace.sharedWorkspace().notificationCenter()
        self._space_observer = center.addObserverForName_object_queue_usingBlock_(
            NSWorkspaceActiveSpaceDidChangeNotification,
            None,
            None,
            # The notification arrives on the posting thread; hop back to
            # the Qt thread before touching the widget.
            lambda _note: QTimer.singleShot(0, self._on_active_space_changed),
        )

    def _on_active_space_changed(self) -> None:
        if self.isVisible():
            self._apply_mac_window_behaviors()

    def _apply_mac_window_behaviors(self) -> None:
        """Apply native macOS behaviors for visibility in fullscreen apps.

        Runs on every show, not once: the Dock icon policy changes while the
        overlay is up (see ``dock_presence``), and the window's fullscreen
        behaviour has to be set again after each change rather than only on
        the first appearance.
        """
        # Skip if not on a live Cocoa display (e.g. during headless tests)
        if QGuiApplication.platformName() != "cocoa":
            return

        try:
            import objc
            from AppKit import (
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
                NSWindowCollectionBehaviorIgnoresCycle,
                NSWindowCollectionBehaviorStationary,
                NSWindowStyleMaskNonactivatingPanel,
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
                # A non-activating panel shows without making the app
                # active. An activating window pulls the app forward, and
                # that takes a full-screen Space away from the app the user
                # is dictating into.
                ns_window.setStyleMask_(
                    ns_window.styleMask() | NSWindowStyleMaskNonactivatingPanel
                )
                # 1. Allow window to float over fullscreen apps
                # 2. Allow window to appear on all Spaces/desktops
                # 3. Hide from Cmd+Tab and stationary during swipe
                # MoveToActiveSpace is left out on purpose: it is exclusive
                # with CanJoinAllSpaces, and the pair is not a valid request.
                ns_window.setCollectionBehavior_(
                    NSWindowCollectionBehaviorCanJoinAllSpaces
                    | NSWindowCollectionBehaviorFullScreenAuxiliary
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

            self._observe_space_changes()

        except Exception as e:
            # Silently fail but log to a temp file for debugging
            with open("/tmp/ltt-overlay.log", "a") as f:
                f.write(f"Overlay behavior error: {e}\n")
            pass

    def _reposition(self) -> None:
        screen = self._screen or self._user_screen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        x = rect.x() + max(0, (rect.width() - self.width()) // 2)
        y = rect.y() + _OVERLAY_TOP_MARGIN
        self.move(x, y)

    def _refresh_styles(self) -> None:
        self.style().unpolish(self._dot)
        self.style().polish(self._dot)
        self.style().unpolish(self._surface)
        self.style().polish(self._surface)
