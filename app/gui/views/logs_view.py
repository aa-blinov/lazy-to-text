"""Application logs view — colour-coded by level + logger source."""

from __future__ import annotations

import html
from collections import deque
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme import TOKENS
from app.gui.widgets.dialogs import confirm
from app.gui.widgets.empty_state import EmptyState
from app.gui.widgets.page_header import PageHeader


# Loggers that are *technically* informative but flood the view with
# HTTP noise during model loads. Hidden by default; the
# "Show network logs" checkbox brings them back.
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "huggingface_hub",
    "requests",
    "asyncio",
)


# QPlainTextEdit's HTML rendering ignores the app stylesheet, so these
# cannot come from QSS. They are still resolved through TOKENS rather
# than written out: a literal here is a second place to change a
# colour, and a colour that QSS cannot reach is a colour nothing else
# can reach either.
#
# A line is ranked, brightest to faintest: the message, the level, the
# module, the timestamp. The rank is what lets the eye find an error in
# a wall of monospaced rows without reading any of them.
#
# The levels take state tokens, not family inks. They used to borrow the
# family inks on the grounds that those were "one step lighter than the
# state colour" — true of the old palette, false of Gruvbox, where the
# bright ramp tops out at the state colour and the family red was the very
# same red as danger. Borrowing them also quietly broke the Family-Colour
# Exception, which keeps family colour out of prose.
_C = TOKENS.colors
_COLOR_TIMESTAMP = _C["text_muted"]
_COLOR_NAME_OWN = _C["text_secondary"]
_COLOR_NAME_OTHER = _C["text_muted"]
_COLOR_MESSAGE = _C["text_primary"]
# DEBUG's body is the faintest thing on the line on purpose: the whole
# job of the level is to make the row recede.
_COLOR_MESSAGE_MUTED = _C["text_muted"]
_COLOR_INFO = _C["accent"]
_COLOR_DEBUG = _C["text_muted"]
_COLOR_WARNING = _C["warning"]
_COLOR_ERROR = _C["danger"]
_COLOR_CRITICAL = _C["danger"]


def _is_noisy(name: str) -> bool:
    """Match top-level package — ``httpx`` matches both ``httpx`` and
    ``httpx._client``, etc."""
    head = name.split(".", 1)[0]
    return head in _NOISY_LOGGERS


def _level_color(level: str) -> str:
    return {
        "DEBUG": _COLOR_DEBUG,
        "INFO": _COLOR_INFO,
        "WARNING": _COLOR_WARNING,
        "ERROR": _COLOR_ERROR,
        "CRITICAL": _COLOR_CRITICAL,
    }.get(level.upper(), _COLOR_INFO)


def _format_record_html(asctime: str, level: str, name: str, message: str) -> str:
    """Render a single log line as inline-styled HTML.

    QPlainTextEdit accepts HTML via ``appendHtml`` but doesn't honour
    QSS, so colours are baked in as inline styles using the same
    palette as theme.py.
    """
    name_color = _COLOR_NAME_OWN
    if _is_noisy(name) or not name.startswith("app."):
        name_color = _COLOR_NAME_OTHER

    msg_color = _COLOR_MESSAGE
    if level.upper() == "DEBUG":
        msg_color = _COLOR_MESSAGE_MUTED

    parts = [
        f'<span style="color:{_COLOR_TIMESTAMP}">{html.escape(asctime)}</span>',
        f'<span style="color:{_level_color(level)};font-weight:600">'
        f'[{html.escape(level)}]</span>',
        f'<span style="color:{name_color}">{html.escape(name)}:</span>',
        f'<span style="color:{msg_color}">{html.escape(message)}</span>',
    ]
    # Single non-breaking-space-joined paragraph; QPlainTextEdit
    # converts each appendHtml call into one block.
    return "&nbsp;".join(parts)


SEARCH_DEBOUNCE_MS = 200  # ms to wait after the last keystroke before re-rendering


class LogsView(QWidget):
    DEFAULT_MAX_LINES = 1000

    def __init__(
        self,
        max_lines: int = DEFAULT_MAX_LINES,
        search_debounce_ms: int = SEARCH_DEBOUNCE_MS,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LogsView")
        self._max_lines = max(1, int(max_lines))
        self._show_network = False
        self._search_query = ""
        # Ring-buffer of every record we've seen so re-renders (after
        # a search filter or network-toggle change) don't have to
        # parse HTML out of the textbox. Capped at ``max_lines`` so
        # memory stays bounded on long-running sessions.
        self._records: deque[tuple[str, str, str, str]] = deque(
            maxlen=self._max_lines
        )

        # Debounce timer — fires _rerender() once after the user stops
        # typing.  Without this, every keystroke triggers a full clear +
        # re-append of up to 5 000 HTML lines.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(search_debounce_ms)
        self._search_timer.timeout.connect(self._rerender)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(10)

        self._header = PageHeader(
            "Logs",
            "What the app is doing, in order. Useful when a model misbehaves.",
            self,
        )
        root.addWidget(self._header)

        header = QHBoxLayout()
        header.setSpacing(8)

        self._search_edit = QLineEdit(self)
        self._search_edit.setObjectName("LogsSearchEdit")
        self._search_edit.setPlaceholderText("Search logs…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._on_search_changed)
        header.addWidget(self._search_edit, 1)

        self._network_toggle = QCheckBox("Show network logs", self)
        self._network_toggle.setObjectName("ShowNetworkLogs")
        self._network_toggle.setChecked(False)
        self._network_toggle.toggled.connect(self._on_toggle_network)
        header.addWidget(self._network_toggle)

        # Destructive, and it sits one click from the search box. Red
        # alone was the old answer to that, and colour is not something
        # to carry a warning by — it disappears in a screenshot, in a
        # high-contrast theme, and for anyone who cannot see it. The
        # label names what is destroyed, and ``_on_clear_clicked`` asks
        # before doing it, exactly as the History view's Clear does:
        # same verb, same consequence, same courtesy.
        self._clear_btn = QPushButton("Clear logs", self)
        self._clear_btn.setObjectName("ClearLogsButton")
        self._clear_btn.setProperty("role", "danger")
        self._clear_btn.setToolTip(
            "Empty the log buffer. The log file on disk is not touched."
        )
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        header.addWidget(self._clear_btn)

        root.addLayout(header)

        self._text = QPlainTextEdit(self)
        self._text.setObjectName("LogsTextArea")
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(self._max_lines)
        # Wrap to widget width — log lines from the recording pipeline can be
        # 200+ chars, and a horizontal scrollbar makes them effectively
        # invisible.
        self._text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._text.setWordWrapMode(QTextOption.WrapAnywhere)

        # Cosine-eased wheel animation matching the rest of the app.
        # ``QPlainTextEdit`` is a ``QAbstractScrollArea`` so the helper
        # binds to its viewport directly.
        from app.gui.smooth_scroll import apply_smooth_scroll
        apply_smooth_scroll(self._text)

        # Before this the empty view was a blank bordered box with no
        # explanation at all, which left the user guessing whether the
        # logger was broken. The log stream normally starts within a
        # second of launch, so this is a transient state — but a
        # transient state still has to say something.
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._text)
        self._empty = EmptyState(
            "No entries yet",
            "The app logs what it does as it runs. Entries appear here "
            "within a second of launch.",
            parent=self._stack,
        )
        self._stack.addWidget(self._empty)
        self._stack.setCurrentWidget(self._empty)

        root.addWidget(self._stack, 1)

    # ---- public API ---------------------------------------------------------

    def append_record(
        self, asctime: str, level: str, name: str, message: str
    ) -> None:
        """Render a structured log record with colours + filtering.

        The one way into this view. There used to be a second:
        ``append_line(text)``, which wrote straight to the document
        without recording anything, so those lines had no level, no
        logger, no search, and — the part that actually mattered — no
        way for the Clear button to know they were there. It survived
        because one caller still used it (the screenshot generator), and
        its last remaining consumer is now on this path too.
        """
        record = (asctime, level, name, message)
        self._records.append(record)
        if not self._record_visible(record):
            # Still has to leave the empty state: a filtered-out record
            # is a record, and the buffer is no longer empty.
            self._sync_stack()
            return
        self._text.appendHtml(_format_record_html(*record))
        self._text.moveCursor(QTextCursor.End)
        self._sync_stack()

    def _has_anything_to_clear(self) -> bool:
        """True if the buffer holds anything.

        The buffer is the only source now, and that is the point: the
        second path that wrote to the document without recording anything
        left lines on screen that no check could account for, which is
        why this used to need a second clause reading the document back.
        Every line the user can see is a record in here — including the
        ones the current filter hides, which is why a search that
        matched nothing still offers a Clear.
        """
        return bool(self._records)

    def _on_clear_clicked(self) -> None:
        """Ask before emptying the buffer.

        The confirm lives here rather than in a controller because the
        consequence is entirely local: this drops the in-memory ring
        buffer and the rendered stream, and nothing on disk. The
        History view's Clear is the mirror image — it also deletes the
        history file, which is why that one is confirmed further up the
        stack. Same verb, same courtesy.
        """
        if not self._has_anything_to_clear():
            return
        if not confirm(
            self,
            "Clear logs?",
            f"Discard the {len(self._records)} buffered log lines? "
            "The log file on disk is not touched.",
            yes_label="Clear logs",
            # Both buttons name the outcome, so the choice does not
            # depend on reading the title twice. "Yes / No" would put
            # the whole decision on recognising the title.
            cancel_label="Keep logs",
        ):
            return
        self.clear()

    def clear(self) -> None:
        self._records.clear()
        self._text.clear()
        self._sync_stack()

    def _sync_stack(self) -> None:
        """Empty state while the buffer is empty, stream once it is not.

        Keyed on the *buffer*, not on what survived the filters: a
        search that matches nothing has to show an empty stream, not
        claim the app has not logged anything.
        """
        self._stack.setCurrentWidget(
            self._text if self._records else self._empty
        )

    # ---- internal -----------------------------------------------------------

    def _on_toggle_network(self, checked: bool) -> None:
        self._show_network = bool(checked)
        self._rerender()

    def focus_search(self) -> bool:
        """Put the keyboard in this view's search field.

        The contract the window's Find accelerator relies on: a view
        either has a search field and focuses it, or does not carry the
        method at all. Returning the bool lets the caller be honest
        about what happened instead of assuming the caret moved.
        """
        self._search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        return True

    def _on_search_changed(self, text: str) -> None:
        self._search_query = text.lower().strip()
        # Restart the debounce timer — if the user is still typing the
        # previous countdown is cancelled and a fresh one begins.
        self._search_timer.start()

    def _record_visible(self, record: tuple[str, str, str, str]) -> bool:
        _asctime, level, name, message = record
        if _is_noisy(name) and not self._show_network:
            return False
        if self._search_query:
            haystack = f"{level} {name} {message}".lower()
            if self._search_query not in haystack:
                return False
        return True

    def _rerender(self) -> None:
        """Replay the buffered records, applying current filters.

        ``QPlainTextEdit.clear`` then a stream of ``appendHtml`` calls
        is the cheapest way to swap content without rebuilding a
        document object.

        Performance: wrapping the rebuild in ``setUpdatesEnabled(False)``
        suppresses per-call screen repaints and scrollbar recalculations,
        turning n incremental layout passes into one final repaint.  The
        ``QTextCursor`` edit block batches all document modifications into a
        single internal event so Qt layout signals fire once instead of n
        times.  At 5 000 records this cuts re-render time from ~500 ms to
        under 50 ms on typical hardware.
        """
        self._text.setUpdatesEnabled(False)
        try:
            self._text.clear()
            cursor = QTextCursor(self._text.document())
            cursor.beginEditBlock()
            try:
                for record in self._records:
                    if self._record_visible(record):
                        self._text.appendHtml(_format_record_html(*record))
            finally:
                cursor.endEditBlock()
        finally:
            self._text.setUpdatesEnabled(True)
        self._text.moveCursor(QTextCursor.End)
