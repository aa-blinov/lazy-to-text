"""One empty state, used by every view that can be empty.

Three views ship a "nothing here yet" surface and, before this, each
built its own: History centred two labels in a card, Logs showed a bare
box with no explanation at all, and Transcribe leaned on a placeholder
string inside a text area. Same idea, three levels of care — and the
Logs one gave the user nothing to act on.

An empty state is not a gap in the layout, it is the screen's job at the
moment before there is data. So it carries three things: what is
missing, why it is missing, and what to do about it. ``footer`` is where
the third one goes — a hotkey chip, usually, because for a dictation
tool the answer to "no transcriptions yet" is a key press.

No glyph by default. The design system bans decorative marks, and an
icon here would repeat the section name in a second visual language for
no gain; ``glyph`` exists for the one case where it does help.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme import icon_path


class EmptyState(QFrame):
    """Centred title, hint, and an optional footer widget.

    A card, because every empty state here stands in for a surface that
    has content in it — the history table, the log stream, the
    transcript. On a bare QWidget the empty region stops reading as a
    surface at all and becomes a hole in the lower half of the window,
    which is worse than the placeholder it replaced.
    """

    def __init__(
        self,
        title: str,
        hint: str = "",
        *,
        glyph: Optional[str] = None,
        framed: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")
        if framed:
            self.setProperty("role", "card")
            self.setFrameShape(QFrame.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        # The content sits slightly above centre: optical centre beats
        # mathematical centre, and with a tall card below it a
        # dead-centre block reads as a header for the empty space.
        layout.setSpacing(10)
        layout.addStretch(2)

        if glyph:
            path = icon_path(f"{glyph}.svg")
            mark = QLabel(self)
            mark.setObjectName("EmptyStateGlyph")
            if path is not None:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    mark.setPixmap(
                        pixmap.scaled(
                            28,
                            28,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
            mark.setAlignment(Qt.AlignCenter)
            layout.addWidget(mark)

        self._title = QLabel(title, self)
        self._title.setProperty("role", "empty-title")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._hint = QLabel(hint, self)
        self._hint.setProperty("role", "empty-hint")
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setVisible(bool(hint))
        layout.addWidget(self._hint)

        self._footer_row = QHBoxLayout()
        self._footer_row.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(self._footer_row)

        layout.addStretch(3)

    def set_footer(self, widget: QWidget) -> None:
        """Centre the footer under the hint.

        The row is rebuilt rather than appended to: it spans the full
        width, so a widget added after the leading stretch lands hard
        right, and one added before a trailing stretch lands hard left.
        Neither is what a key cap under a centred sentence should do.
        """
        while self._footer_row.count():
            self._footer_row.takeAt(0)
        self._footer_row.addStretch(1)
        self._footer_row.addWidget(widget)
        self._footer_row.addStretch(1)

    @property
    def title_label(self) -> QLabel:
        return self._title


def kbd_chip(keys: str, parent: Optional[QWidget] = None) -> QLabel:
    """A hotkey rendered as a key cap rather than as prose.

    Settings and the History empty state both tell the user to press a
    key. In running text that instruction is the easiest line on screen
    to skim past, because it looks like every other sentence.
    """
    chip = QLabel(keys, parent)
    chip.setObjectName("KbdChip")
    chip.setProperty("role", "kbd")
    chip.setAlignment(Qt.AlignCenter)
    return chip


def format_hotkey(value: str) -> str:
    """``ctrl+f8`` as a key cap reads ``Ctrl+F8``.

    Settings shows the raw config form in its own fields, so this is a
    display transform only — the same shortcut, set the way a key is
    labelled. Splitting on ``+`` keeps multi-modifier bindings intact,
    and the underscore in a lone key like ``right_cmd`` becomes the
    space it stands for.
    """
    parts = [p.strip().replace("_", " ") for p in str(value or "").split("+")]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return "+".join(p[:1].upper() + p[1:] for p in parts)


def hotkey_cap(value: str, parent: Optional[QWidget] = None) -> QLabel:
    """A key cap for *value*, or nothing at all if it is unset.

    The cap is an instruction, so it must name a key the user actually
    holds. It is built from the configured hotkey rather than a literal
    for two reasons: the shipped default differs per platform, and the
    user can rebind it in Settings. An empty value yields no cap at all
    — there is nothing true to print, and a blank square is worse than
    an absent one.
    """
    if not str(value or "").strip():
        return None
    return kbd_chip(format_hotkey(value), parent)
