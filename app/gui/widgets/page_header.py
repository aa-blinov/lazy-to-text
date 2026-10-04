"""Page identity: the title and purpose line every view carries.

Five views, one header. The design system already defined the vocabulary
— a 22px ``role="title"`` and a ``role="subtitle"`` — and no real view
used either of them: only ``placeholder.py``, the fallback screen the app
never shows. Without it, Transcribe, History, Logs and Models all read as
one long settings panel, because nothing on screen says which section
you are in once the sidebar highlight is out of the corner of your eye.

Built as a widget rather than as two labels per view for the same reason
the sidebar's focus state moved into the stylesheet: five hand-built
copies is five chances to drift, and the first drift was already there —
``TranscribeView`` had invented 24px margins against the documented
28/22 frame, so its content did not line up with its neighbours.

The optional action slot is for the one control a view would call its
primary. Views with no single primary action leave it empty rather than
promoting something arbitrary — an empty header with a title still beats
a wrong accent-coloured button.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class PageHeader(QWidget):
    """Title on the left, one line of purpose under it, optional action
    on the right."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PageHeader")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        # 2px: the title's cap height needs a little air under it or the
        # subtitle reads as part of the same block.
        text_column.setSpacing(2)

        self._title = QLabel(title, self)
        self._title.setObjectName("PageTitle")
        self._title.setProperty("role", "title")
        self._title.setWordWrap(True)
        text_column.addWidget(self._title)

        self._subtitle = QLabel(subtitle, self)
        self._subtitle.setObjectName("PageSubtitle")
        self._subtitle.setProperty("role", "subtitle")
        self._subtitle.setWordWrap(True)
        # A view that passes no subtitle gets a header, not a gap.
        self._subtitle.setVisible(bool(subtitle))
        text_column.addWidget(self._subtitle)

        outer.addLayout(text_column, 1)

        self._action_row = QHBoxLayout()
        self._action_row.setContentsMargins(0, 0, 0, 0)
        self._action_row.setSpacing(8)
        self._action_row.addStretch(1)
        outer.addLayout(self._action_row)

    def set_action(self, widget: QWidget) -> None:
        """Park the view's one primary action on the right of the header."""
        self._action_row.addWidget(widget)

    @property
    def title_label(self) -> QLabel:
        return self._title

    @property
    def subtitle_label(self) -> QLabel:
        return self._subtitle
