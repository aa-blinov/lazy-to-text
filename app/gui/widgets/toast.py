"""Transient notification banner overlaid on the main window.

Used to confirm that a finished transcription landed on the
clipboard — successful runs were silent before, leaving the user
unsure whether the hotkey actually did anything.

Because that confirmation is the product's payoff and usually arrives
while the user is looking at a *different* window, the banner has one
authored entrance: it rises out of the corner it already occupies
while fading in, and leaves faster than it came. See
:mod:`app.gui.motion` for the sequence and the Reduce Motion path.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QParallelAnimationGroup, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from app.gui.motion import fade_out, rise_and_fade

# How far below its resting place the banner starts. 12px reads as
# "arriving from the corner" without turning into a slide.
_ARRIVAL_OFFSET_PX = 12
_ARRIVAL_MS = 180
_DEPART_MS = 120


_DEFAULT_DURATION_MS = 3000
_MAX_PREVIEW_CHARS = 80


def _truncate(text: str, limit: int = _MAX_PREVIEW_CHARS) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class Toast(QFrame):
    """Top-right floating banner that auto-hides after a few seconds.

    The widget is parented to a host (typically ``MainWindow``) and
    positions itself in the top-right corner via ``move``. It does
    nothing until ``show_message`` is called, then re-arms its
    auto-hide timer on every subsequent call so back-to-back
    transcriptions keep extending the banner instead of stacking
    multiple toasts.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("role", "toast")
        self.setFrameShape(QFrame.NoFrame)
        # The toast floats above sibling widgets; turn off mouse
        # interaction so clicks pass through to whatever is beneath.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self._title = QLabel("Copied", self)
        self._title.setObjectName("ToastTitle")
        self._title.setProperty("role", "toast-title")
        layout.addWidget(self._title)

        self._body = QLabel("", self)
        self._body.setObjectName("ToastBody")
        self._body.setProperty("role", "toast-body")
        layout.addWidget(self._body, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)

        # The running entrance or departure. Held so a second message
        # can interrupt the first instead of stacking a second group on
        # the same two properties.
        self._anim: Optional[QParallelAnimationGroup] = None

        self.hide()

    # ---- public API ---------------------------------------------------------

    def show_message(
        self,
        text: str,
        duration_ms: int = _DEFAULT_DURATION_MS,
    ) -> None:
        """Display a confirmation banner with a preview of ``text``.

        Only shows if the parent window is visible — prevents the main
        window from popping up when hidden to tray. Re-arms the
        auto-hide timer if the toast is already visible.

        A second message arriving at a visible banner updates the text
        and re-arms the timer but does **not** replay the entrance: the
        banner is already on screen, and re-running the arrival would
        make a back-to-back pair of transcriptions look like a glitch
        rather than one continuous confirmation.
        """
        host = self.parentWidget()
        if host is not None and not host.isVisible():
            return

        preview = _truncate(text)
        if not preview:
            return
        self._body.setText(preview)
        self.adjustSize()
        self._reposition()
        self._timer.start(max(500, int(duration_ms)))

        if self.isVisible():
            # Cancel whatever is in flight (usually a departure that
            # had not finished) and restore the resting state.
            self._stop_anim()
            self._settle()
            return

        self.show()
        self._anim = rise_and_fade(
            self, offset_px=_ARRIVAL_OFFSET_PX, duration_ms=_ARRIVAL_MS
        )

    def hide_message(self) -> None:
        """Clear the banner now, synchronously.

        Deliberately not animated, and deliberately different from the
        timed departure. This is the imperative verb — something decided
        the confirmation is no longer wanted — and a caller that gets
        control back expects no banner on screen. A 120 ms residual here
        would put a ghost over whatever the caller opens next, with the
        hide timer already stopped so nothing would clean it up.

        The timed path is the one that earns a fade: there the banner is
        leaving on its own schedule, nobody is waiting on the call, and
        the motion costs the user nothing.
        """
        self._timer.stop()
        self._stop_anim()
        self.hide()

    # ---- internal -----------------------------------------------------------

    def _dismiss(self) -> None:
        """Auto-hide fired. Leaves, it doesn't blink out."""
        self._depart()

    def _depart(self) -> None:
        """Timed departure: fade, then hide."""
        if not self.isVisible():
            self._stop_anim()
            return
        self._stop_anim()
        group = fade_out(self, duration_ms=_DEPART_MS)
        if group is None:
            # Reduce Motion: the fade would be indistinguishable from a
            # cut at this length, so cut.
            self.hide()
            return
        # Tracked like the entrance. An untracked group would keep
        # running after a new message cancelled the departure, finish at
        # opacity 0 and hide a banner the user was still reading.
        self._anim = group
        group.finished.connect(self._on_departed)

    def _on_departed(self) -> None:
        self._anim = None
        self.hide()

    def _stop_anim(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim = None

    def _settle(self) -> None:
        """Force the banner back to its resting, fully-opaque state.

        A stopped animation leaves its properties wherever the last tick
        reached them, so anything that cancels motion has to finish the
        last step itself.
        """
        effect = self.graphicsEffect()
        if effect is not None:
            effect.setOpacity(1.0)
        self._reposition()

    def _reposition(self) -> None:
        host = self.parentWidget()
        if host is None:
            return
        margin = 16
        # Bottom-right corner so the banner never lands on top of the
        # search bar / first-row content of whatever view is active.
        # Same convention as Slack / Discord / VS Code notifications.
        x = host.width() - self.width() - margin
        y = host.height() - self.height() - margin
        self.move(max(margin, x), max(0, y))

    # Re-anchor when the host resizes.
    def parentResized(self) -> None:  # pragma: no cover — convenience hook
        self._reposition()
