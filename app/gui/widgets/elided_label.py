"""Single-line label that elides instead of widening its parent.

Qt's ``QLabel`` reports a minimum width equal to its full text, so a
long string inside a stretched container does not wrap and does not
clip — it *pushes*. On a card inside a horizontally scrollable view
that means the card's action button slides out of reach, and the
containing scroll area grows a horizontal scrollbar nobody asked for.

The Models view already hit this once, for the badge row, which is why
``FlowLayout`` wraps there. The card title and its canonical id had no
equivalent treatment: both are single-line labels whose text comes from
a Hugging Face repo, which is exactly the kind of string that is short
in review and long in the wild.

This label keeps the horizontal size policy at ``Ignored`` so the
layout may shrink it freely, then re-elides the text on every resize
to whatever actually fits. The full string stays available as the
tooltip, so nothing is lost — it is only hidden behind the ellipsis.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    """A ``QLabel`` that shows ``…`` at the end instead of growing."""

    def __init__(
        self,
        text: str = "",
        parent: Optional[QLabel] = None,
        *,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
    ) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self._mode = mode
        # ``Ignored`` tells the layout that this widget's width is not
        # driven by its contents. Without it the size hint wins and the
        # widget never shrinks far enough to need eliding.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if text:
            self.setToolTip(text)

    # ---- text ---------------------------------------------------------------

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._apply_elide()

    def full_text(self) -> str:
        """The untruncated string, for tests and for callers that need it."""
        return self._full_text

    # ---- geometry -----------------------------------------------------------

    def _apply_elide(self) -> None:
        available = max(0, self.width() - 2)
        if available <= 0:
            # Pre-layout: no width to elide against. Setting the full
            # text keeps the size hint correct for the first layout pass.
            super().setText(self._full_text)
            return
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full_text, self._mode, available))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._apply_elide()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        # Never let the untruncated text set a minimum width — that is
        # the behaviour this whole class exists to undo.
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        hint = super().sizeHint()
        return QSize(0, hint.height())
