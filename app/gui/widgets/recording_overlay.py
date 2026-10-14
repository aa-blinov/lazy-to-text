"""Small always-on-top recording status overlay.

Unlike the in-window toast, this widget is a separate top-level tool
window so it can stay visible while the main app is hidden or unfocused.
"""

from __future__ import annotations

import logging
import sys
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QScreen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.language import bind, bus, tr_text

log = logging.getLogger(__name__)


# Long enough to read one line, short enough that the next dictation is
# not queued behind the previous one's confirmation.
_DELIVERY_VISIBLE_MS = 2000

# How far below the top of the screen's available area the overlay sits.
# A constant rather than an inline literal because the fallback path for
# "no screen at all" reuses it, and two copies of 28 that drift apart
# would move the overlay when the display layout changes.
_OVERLAY_TOP_MARGIN = 28

# A piece of on-screen copy is a zero-argument callable returning
# (title, body, accessible description). It is called again on every
# language switch, so the text is always read in the current language.
# Every literal below is a ``tr_text`` call, because the catalogue extractor
# only collects literal sources.
_Copy = Callable[[], tuple[str, str, str]]


def _recording_copy() -> tuple[str, str, str]:
    return (
        tr_text("RecordingOverlay", "Recording"),
        tr_text("RecordingOverlay", "Speak now"),
        tr_text("RecordingOverlay", "Recording — speak now"),
    )


def _processing_copy() -> tuple[str, str, str]:
    return (
        tr_text("RecordingOverlay", "Processing"),
        tr_text("RecordingOverlay", "Transcribing speech"),
        tr_text("RecordingOverlay", "Processing — transcribing speech"),
    )


def _delivery_copy(outcome: str, detail: str) -> Optional[_Copy]:
    """Copy for one delivery outcome, or ``None`` for an unknown outcome.

    Every state names what happened in the past tense, because that is the
    question being answered; the detail line carries only the fact that
    changes what to do next. A runtime ``detail`` is shown as given and
    never looked up for translation.
    """
    titles: dict[str, Callable[[], str]] = {
        "pasted": lambda: tr_text("RecordingOverlay", "Paste sent"),
        "copied": lambda: tr_text("RecordingOverlay", "Copied"),
        "failed": lambda: tr_text("RecordingOverlay", "Delivery failed"),
    }
    defaults: dict[str, Callable[[], str]] = {
        "pasted": lambda: tr_text(
            "RecordingOverlay", "Keystroke posted — we cannot confirm the paste"
        ),
        "copied": lambda: tr_text(
            "RecordingOverlay", "Press the paste shortcut in your app"
        ),
        "failed": lambda: tr_text(
            "RecordingOverlay", "Nothing was pasted — the reason is in Logs"
        ),
    }
    if outcome not in titles:
        return None

    def copy() -> tuple[str, str, str]:
        title = titles[outcome]()
        body = detail or defaults[outcome]()
        return title, body, f"{title} — {body}"

    return copy


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
        self._copy: Optional[_Copy] = None
        bus.language_changed.connect(self._retranslate)
        # This is a separate top-level window, so a screen reader
        # announces it as one. Without a name it is announced as a bare
        # "window", which tells a non-sighted user nothing about the
        # one piece of app feedback that reaches them mid-sentence —
        # so the name carries the state, and ``set_state`` rewrites it.
        bind(self, "setAccessibleName", "RecordingOverlay", "Recording status")
        self.setAccessibleDescription(tr_text("RecordingOverlay", "Idle"))
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
        bind(self._dot, "setAccessibleName", "RecordingOverlay", "Recording indicator")
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

    def _set_copy(self, copy: _Copy) -> None:
        self._copy = copy
        self._render_copy()

    def _render_copy(self) -> None:
        if self._copy is None:
            return
        title, body, description = self._copy()
        self._title.setText(title)
        self._body.setText(body)
        self.setAccessibleDescription(description)

    def _idle_copy(self) -> tuple[str, str, str]:
        # Idle keeps whatever the last visible copy was; only the
        # accessible description changes.
        return (
            self._title.text(),
            self._body.text(),
            tr_text("RecordingOverlay", "Idle"),
        )

    def _retranslate(self, _language: str = "") -> None:
        if self._copy is not None:
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
        copy = _delivery_copy(outcome, detail)
        if copy is None:
            return
        self._delivery_active = True
        self._state = outcome
        self._set_copy(copy)
        self._dot.setProperty("state", outcome)
        self._dot.setAccessibleDescription(self._title.text())
        self._refresh_styles()
        self._show_overlay()
        self._delivery_timer.start(_DELIVERY_VISIBLE_MS)

    def _on_delivery_elapsed(self) -> None:
        self._delivery_active = False
        self._state = "idle"
        self._set_copy(self._idle_copy)
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
            self._set_copy(_recording_copy)
            self._dot.setProperty("state", "recording")
            self._dot.setAccessibleDescription(
                tr_text("RecordingOverlay", "Recording")
            )
            self._refresh_styles()
            self._show_overlay()
            return
        if state == "processing":
            self._state = "processing"
            self._set_copy(_processing_copy)
            self._dot.setProperty("state", "processing")
            self._dot.setAccessibleDescription(
                tr_text("RecordingOverlay", "Processing")
            )
            self._refresh_styles()
            self._show_overlay()
            return
        self._state = "idle"
        self._set_copy(self._idle_copy)
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

        except Exception:
            # The overlay still shows without the fullscreen behaviour; the
            # failure goes to the app log, where support can find it.
            log.warning("Overlay window behaviour could not be applied", exc_info=True)

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
