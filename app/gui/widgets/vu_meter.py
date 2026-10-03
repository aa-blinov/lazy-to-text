"""Live audio-level indicator shown in the TopBar during recording.

Custom-painted instead of a styled QProgressBar so we get smooth
gradient fills and a colour change at clip levels without fighting
the QSS engine.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.gui.theme import TOKENS


_BG_COLOR = QColor(TOKENS.colors["bg_elevated"])
_BORDER_COLOR = QColor(TOKENS.colors["border"])
_GREEN = QColor(TOKENS.colors["success"])
_AMBER = QColor(TOKENS.colors["warning"])
_RED = QColor(TOKENS.colors["danger"])

_DECAY = 0.85   # how fast the bar falls between updates (0..1, lower → faster)


class VUMeter(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("VUMeter")
        # Drawn entirely with QPainter — there is no child label, so
        # without this a screen reader finds nothing at all where the
        # level is drawn. The name says what the control is; the level
        # itself is carried by the adjacent text (the chip value, or
        # the mic-test result line) rather than re-announced 60x/second.
        self.setAccessibleName("Microphone level")
        self.setAccessibleDescription(
            "Live input level meter. The current level is shown as a bar "
            "and is reported in text beside it."
        )
        # Fixed height so the bar reads as a slim strip; width grows
        # with the parent layout so the meter spans the sidebar's
        # full slot rather than sitting as a 140 px chip in the corner.
        # Min-width keeps the bar wide enough to register at narrow
        # window sizes.
        self.setFixedHeight(8)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._level = 0.0  # smoothed display value, 0..1

    # ---- public API ---------------------------------------------------------

    def set_level(self, raw_level: float) -> None:
        """Push a new amplitude reading into the meter.

        Applies a small exponential decay so the bar falls back
        gracefully on quiet samples instead of flickering off.
        """
        try:
            new = max(0.0, min(1.0, float(raw_level)))
        except (TypeError, ValueError):
            new = 0.0
        # Peak-and-decay envelope: instantly track louder samples,
        # decay smoothly back during silence.
        self._level = max(new, self._level * _DECAY)
        self.update()

    def reset(self) -> None:
        self._level = 0.0
        self.update()

    def current_level(self) -> float:
        return self._level

    # ---- painting -----------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        radius = rect.height() / 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(_BG_COLOR)
        painter.drawRoundedRect(rect, radius, radius)

        if self._level <= 0.0:
            return

        fill_width = max(1, int(rect.width() * self._level))
        if self._level < 0.5:
            color = _GREEN
        elif self._level < 0.85:
            color = _AMBER
        else:
            color = _RED
        painter.setBrush(color)
        fill_rect = rect.adjusted(0, 0, fill_width - rect.width(), 0)
        painter.drawRoundedRect(fill_rect, radius, radius)
