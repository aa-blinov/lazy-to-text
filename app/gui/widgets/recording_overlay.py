"""Small always-on-top recording status overlay, which also carries the result.

It is a separate top-level tool window so it can stay visible while the main
app is hidden or unfocused. It shows the recording and processing states, then
what happened to the dictation, with the text that was delivered.
"""

from __future__ import annotations

import logging
import sys
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.gui.mac_window import float_over_full_screen
from app.gui.placement import (
    FLOATING_MARGIN_PX,
    FLOATING_PLATE_HEIGHT_PX,
    bottom_right_position,
    user_screen,
)
from app.language import bind, bus, tr_text

log = logging.getLogger(__name__)


# Long enough to read the one line of text, short enough that the next
# dictation is not queued behind this one's result.
_DELIVERY_VISIBLE_MS = 3000

# The surface's horizontal chrome: padding on both sides, the state dot and
# its gap to the text, and the border. The text budget leaves room for it.
_SURFACE_PAD_X = 16
_DOT_PX = 14
_DOT_GAP_PX = 12
_BORDER_PX = 1
_CHROME_WIDTH_PX = 2 * _SURFACE_PAD_X + _DOT_PX + _DOT_GAP_PX + 2 * _BORDER_PX

# The most a result's text may take on its line. Past this the text is cut
# with an ellipsis: the whole text is in History, and the popup stays one line
# tall and inside the screen whatever was said.
_RESULT_TEXT_MAX_PX = 440

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
        tr_text("RecordingOverlay", "Recording. Speak now."),
    )


def _processing_copy() -> tuple[str, str, str]:
    return (
        tr_text("RecordingOverlay", "Processing"),
        tr_text("RecordingOverlay", "Transcribing speech"),
        tr_text("RecordingOverlay", "Processing. Transcribing speech."),
    )


def _delivery_title(outcome: str, detail: str) -> str:
    """The line that says what happened to the dictation.

    Every title names the outcome in the past tense, because that is the
    question being answered. ``detail`` is the paste shortcut, given only
    when the user has to press it themselves; the title then says so.
    """
    if outcome == "pasted":
        return tr_text("RecordingOverlay", "Paste sent")
    if outcome == "failed":
        return tr_text("RecordingOverlay", "Delivery failed")
    if detail:
        return tr_text("RecordingOverlay", "Copied — press %1").replace("%1", detail)
    return tr_text("RecordingOverlay", "Copied")


def _delivery_body(outcome: str, text: str) -> str:
    """The text that went out, on one line; the reason when nothing did.

    Whitespace is collapsed, so a multi-line dictation reads as one line. A
    failed delivery never shows the text: nothing went anywhere, and the
    reason is what the user needs.
    """
    if outcome == "failed":
        return tr_text("RecordingOverlay", "Nothing was pasted. The reason is in Logs.")
    line = " ".join((text or "").split())
    if line:
        return line
    return tr_text("RecordingOverlay", "Copied to clipboard")


def _delivery_copy(outcome: str, detail: str, text: str) -> Optional[_Copy]:
    """Copy for one delivery outcome, or ``None`` for an unknown outcome.

    ``detail`` and ``text`` are runtime values, shown as given and never
    looked up for translation; the only catalogue text is the fixed copy.
    """
    if outcome not in ("pasted", "copied", "failed"):
        return None

    def copy() -> tuple[str, str, str]:
        title = _delivery_title(outcome, detail)
        body = _delivery_body(outcome, text)
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
        self.setMinimumHeight(FLOATING_PLATE_HEIGHT_PX)
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
        self._surface.setMinimumHeight(FLOATING_PLATE_HEIGHT_PX)
        root.addWidget(self._surface)

        surface_layout = QHBoxLayout(self._surface)
        surface_layout.setContentsMargins(_SURFACE_PAD_X, 12, _SURFACE_PAD_X, 12)
        surface_layout.setSpacing(_DOT_GAP_PX)

        self._dot = QFrame(self._surface)
        self._dot.setObjectName("RecordingOverlayDot")
        self._dot.setProperty("role", "recording-overlay-dot")
        self._dot.setFixedSize(_DOT_PX, _DOT_PX)
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
        self._body.setText(self._fit_body(body))
        # The screen reader gets the whole text; only the eye gets the cut.
        self.setAccessibleDescription(description)
        self._fit_width()

    def _fit_body(self, text: str) -> str:
        """``text`` cut to one line that the surface can carry.

        Measured with the stylesheet applied: the body's font comes from QSS,
        and a font measured before polish is not the one the user sees.
        """
        self.ensurePolished()
        return self._body.fontMetrics().elidedText(
            text, Qt.ElideRight, self._text_budget()
        )

    def _fit_width(self) -> None:
        """Size the popup to the text it now shows, straight away.

        The layout's own size is only refreshed on the event loop, after the
        call that changed the text has returned, so a width read from the
        layout right away is the one from before the text. The labels know
        their text's width at once, and the rest of the surface is fixed by
        the constants above.
        """
        self.ensurePolished()
        text = max(self._title.sizeHint().width(), self._body.sizeHint().width())
        self.resize(_CHROME_WIDTH_PX + text, FLOATING_PLATE_HEIGHT_PX)

    def _text_budget(self) -> int:
        """Width the body's text may take on the screen the popup sits on.

        ``_RESULT_TEXT_MAX_PX`` is the design's cap. The screen is what keeps
        the popup inside its edges on a narrow display, so the text is cut
        before the surface can be wider than the screen it is anchored to.
        """
        budget = _RESULT_TEXT_MAX_PX
        screen = self._anchor_screen()
        if screen is not None:
            room = (
                screen.availableGeometry().width()
                - 2 * FLOATING_MARGIN_PX
                - _CHROME_WIDTH_PX
            )
            budget = min(budget, room)
        return max(budget, 0)

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

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        # The corner is a function of the size. When the popup changes size
        # while it is up (a new text, or another language), it is placed
        # again in the same corner rather than left where the old size put it.
        if self.isVisible():
            self._reposition()

    def show_delivery(self, outcome: str, detail: str = "", text: str = "") -> None:
        """Report what happened to the dictation, and the text it was about.

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

        ``detail`` is the paste shortcut, given when the user has to press
        it themselves; the title then says so. ``text`` is what was
        delivered, shown on the one line under the title. A failed delivery
        shows the reason instead, because the text went nowhere.

        Holding the overlay open here is the whole point, so ``idle``
        no longer hides while a delivery confirmation is on screen: the
        state machine reaches ``idle`` within milliseconds of this call,
        and an unconditional hide would win that race every time.
        """
        copy = _delivery_copy(outcome, detail, text)
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
        # Polish first: the stylesheet's minimum height only counts once it
        # is applied, and an unpolished window would be placed too short.
        self.ensurePolished()
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
        """The screen the user is looking at, or the primary one."""
        return user_screen()

    def _anchor_screen(self) -> Optional[QScreen]:
        """The screen this appearance is anchored to, while Qt still has it.

        Qt can delete the anchor before the removal signal re-anchors the
        overlay. Every use of the deleted object then raises, so the overlay
        falls back to the user's screen instead of failing its caller.
        """
        if self._screen is not None:
            try:
                self._screen.availableGeometry()
            except RuntimeError:
                self._screen = None
            else:
                return self._screen
        return self._user_screen()

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
        if not float_over_full_screen(self):
            return
        try:
            self._observe_space_changes()
        except Exception:
            # Without the observer the overlay still shows; it just is not
            # re-ordered after a change of Space.
            log.warning("Overlay Space observer could not be registered", exc_info=True)

    def _reposition(self) -> None:
        screen = self._anchor_screen()
        if screen is None:
            return
        self.move(bottom_right_position(self.width(), self.height(), screen))

    def _refresh_styles(self) -> None:
        self.style().unpolish(self._dot)
        self.style().polish(self._dot)
        self.style().unpolish(self._surface)
        self.style().polish(self._surface)
