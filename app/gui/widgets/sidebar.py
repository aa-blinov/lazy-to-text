"""Left-hand navigation sidebar for the main window."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from app.gui.smooth_scroll import apply_smooth_scroll
from app.gui.theme import TOKENS, icon_path
from app.gui.widgets.recording_status_widget import RecordingStatusWidget


class _NavFocusDelegate(QStyledItemDelegate):
    """Paint the sidebar's focus ring on the row, not around the list.

    The list is a single tab stop, so Qt puts keyboard focus on the
    widget rather than on an item. QSS can therefore only frame the
    widget — which drew a border around the whole 200 × 601 px
    navigation column, top to bottom, and read as a stray border instead
    of an indicator. QSS also cannot express "the list has focus *and*
    this item is the current one" as one selector, which is why the frame
    ended up where the eye was not.

    Painting it here puts the ring on the row the user just tabbed to.
    Two details follow the rest of the app:

    - Ink Primary, not accent, because the current row is an accent
      fill and an accent ring on an accent fill is invisible — the same
      reason the primary button and the checked chip use ink.
    - 1px, not the 2px every other control uses: a 46px-tall rounded row
      would visibly lose fill to a 2px band, and the ring is drawn
      *inside* the row rather than replacing a border, so it cannot
      change what the user tabbed to.
    """

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802 - Qt naming
        super().paint(painter, option, index)
        rect = _ring_rect(option)
        if rect is None:
            return

        painter.save()
        pen = QPen(QColor(TOKENS.colors["text_primary"]))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            rect, TOKENS.radius["sm"], TOKENS.radius["sm"]
        )
        painter.restore()


def _ring_rect(option) -> Optional[QRect]:
    """Where the sidebar's focus ring goes — or ``None`` for nothing.

    Split out of :meth:`_NavFocusDelegate.paint` so the three decisions
    that matter (has focus, is selected, and *which* rect) are testable
    without standing up a real focus chain for each of them.
    """
    widget = option.widget
    if widget is None or not widget.hasFocus():
        return None
    if not option.state & QStyle.StateFlag.State_Selected:
        return None
    # Inside the row, so the band can never eat into the label or grow
    # the item — the row the user tabbed to must not move.
    return option.rect.adjusted(1, 1, -2, -2)


NavItem = Tuple[str, str]
_DEFAULT_ITEMS: tuple[NavItem, ...] = (
    ("models", "Models"),
    ("transcribe", "Transcribe"),
    ("history", "History"),
    ("logs", "Logs"),
    ("shortcuts", "Settings"),
)
# Filename (without ``.svg``) inside ``app/gui/styles/icons/`` for
# each nav key. Heroicons (outline, 24×24) — line-style works at
# 20 px sidebar size and ages better than custom icons.
_KEY_ICON_FILES: dict[str, str] = {
    "models": "models",
    "transcribe": "transcribe",
    "shortcuts": "settings",
    "history": "history",
    "logs": "logs",
}
_KEY_ROLE = Qt.UserRole + 1
_LABEL_ROLE = Qt.UserRole + 2


class Sidebar(QWidget):
    nav_selected = Signal(str)

    def __init__(
        self,
        items: Optional[Sequence[NavItem]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._list = QListWidget(self)
        self._list.setObjectName("SidebarList")
        self._list.setFrameShape(QListWidget.NoFrame)
        self._list.setSelectionMode(QListWidget.SingleSelection)
        # The list is one tab stop, so focus lands here and never on an
        # item — the ring has to be painted, not styled.
        self._list.setItemDelegate(_NavFocusDelegate(self._list))
        apply_smooth_scroll(self._list)
        # Heroicons render best at ~20 px in a 14-px-text row.
        self._list.setIconSize(QSize(20, 20))
        # Stretch=1 so the nav list eats whatever vertical space the
        # bottom recording-status slot doesn't claim.
        layout.addWidget(self._list, 1)

        # Recording status slot pinned to the bottom-left of the
        # sidebar — chip-style card matching the topbar's resource
        # widget, always shows its placeholder state even when idle.
        # Wrapped in its own widget so the layout's contentsMargins
        # handle the bottom-alignment with the ModelsView's
        # ``setContentsMargins(28, 22, 28, 22)`` (QSS ``margin`` on
        # the chip itself isn't reliable for plain QWidgets — Qt
        # routes it through QStyle which doesn't always apply it).
        chip_holder = QWidget(self)
        chip_holder.setObjectName("RecordingStatusHolder")
        chip_layout = QVBoxLayout(chip_holder)
        chip_layout.setContentsMargins(12, 12, 12, 22)
        chip_layout.setSpacing(0)
        self.recording_status = RecordingStatusWidget(chip_holder)
        chip_layout.addWidget(self.recording_status)
        layout.addWidget(chip_holder)

        resolved = tuple(items) if items is not None else _DEFAULT_ITEMS
        for key, label in resolved:
            entry = QListWidgetItem(label)
            entry.setData(_KEY_ROLE, key)
            entry.setData(_LABEL_ROLE, label)
            icon_name = _KEY_ICON_FILES.get(key)
            if icon_name:
                path = icon_path(f"{icon_name}.svg")
                if path is not None and Path(path).is_file():
                    entry.setIcon(QIcon(path))
            self._list.addItem(entry)

        self._current_key = resolved[0][0] if resolved else ""
        if resolved:
            self._list.setCurrentRow(0)

        self._list.currentRowChanged.connect(self._on_row_changed)

    def items(self) -> List[str]:
        return [
            self._list.item(i).data(_KEY_ROLE) for i in range(self._list.count())
        ]

    def label_for(self, key: str) -> str:
        """Plain display label for a nav key (e.g. ``shortcuts`` ->
        ``Settings``) — strips the icon prefix used in the list row.
        Falls back to ``key.capitalize()`` if the key isn't known."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(_KEY_ROLE) == key:
                return item.data(_LABEL_ROLE) or item.text()
        return key.capitalize()

    def active_key(self) -> str:
        return self._current_key

    def set_active(self, key: str) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).data(_KEY_ROLE) == key:
                if self._list.currentRow() != i:
                    self._list.setCurrentRow(i)
                return
        raise ValueError(f"Unknown nav key: {key!r}")

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        key = self._list.item(row).data(_KEY_ROLE)
        if key == self._current_key:
            return
        self._current_key = key
        self.nav_selected.emit(key)
