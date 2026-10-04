"""History view — searchable table of past transcriptions."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QKeySequence, QShortcut
# Qt is imported above for the alignment flags used by the empty state.

from app.gui.smooth_scroll import apply_smooth_scroll
from app.model_mapping import alias_for
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.config_manager import default_start_hotkey
from app.gui.widgets.empty_state import EmptyState, format_hotkey, hotkey_cap, kbd_chip
from app.gui.widgets.page_header import PageHeader

_HEADERS = ("Time", "Text", "Model", "Language", "Duration")


class HistoryTableModel(QAbstractTableModel):
    def __init__(self, entries: Optional[Sequence[Any]] = None) -> None:
        super().__init__()
        self._entries: List[Any] = list(entries or [])

    # ---- Qt overrides -------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(_HEADERS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return _HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        col = index.column()
        # Tooltip on the Text column carries the full transcription so
        # the user can hover-peek long entries without opening the
        # detail dialog. The Model column tooltip surfaces the full
        # canonical id (since the displayed value is the short alias).
        if role == Qt.ToolTipRole:
            if col == 1:
                return getattr(entry, "text", "")
            if col == 2:
                return getattr(entry, "model", "")
            return None
        if role != Qt.DisplayRole:
            return None
        if col == 0:
            return getattr(entry, "datetime_str", "")
        if col == 1:
            return getattr(entry, "text", "")
        if col == 2:
            # Map the canonical Hugging Face / engine id back to the
            # short registry alias (``large-v3``, ``gigaam-v2-ctc``).
            # Falls through to the original string for unregistered
            # canonicals.
            return alias_for(getattr(entry, "model", ""))
        if col == 3:
            return getattr(entry, "language", "")
        if col == 4:
            duration = getattr(entry, "duration", 0.0)
            return f"{duration:.1f}s"
        return None

    # ---- public API ---------------------------------------------------------

    def set_entries(self, entries: Sequence[Any]) -> None:
        self.beginResetModel()
        self._entries = list(entries)
        self.endResetModel()

    def prepend_entry(self, entry: Any, max_entries: int = 0) -> None:
        """Insert *entry* at row 0 (newest) without a full model reset.

        Using ``beginInsertRows / endInsertRows`` instead of
        ``beginResetModel / endResetModel`` preserves the view's scroll
        position and selection — critical when history is long and the user
        is reading while new transcriptions keep arriving.

        If *max_entries* > 0 and the list would exceed it after the insert,
        the oldest entry (last row) is removed via a separate
        ``beginRemoveRows / endRemoveRows`` pair so the view updates
        incrementally rather than repainting everything.
        """
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._entries.insert(0, entry)
        self.endInsertRows()

        if max_entries > 0 and len(self._entries) > max_entries:
            last = len(self._entries) - 1
            self.beginRemoveRows(QModelIndex(), last, last)
            self._entries.pop(last)
            self.endRemoveRows()

    def entry_at(self, row: int) -> Any:
        if row < 0 or row >= len(self._entries):
            raise IndexError(row)
        return self._entries[row]


class HistoryDetailDialog(QDialog):
    """Modal dialog showing the full transcription text + metadata.

    The history table ellipsises long entries in the Text column, so
    this dialog is what the user opens (via double-click) when they
    actually want to read or copy the whole transcript.
    """

    def __init__(self, entry: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HistoryDetailDialog")
        self.setWindowTitle("Transcription details")
        self.setModal(True)
        self.resize(720, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # ---- meta strip ----------------------------------------------------
        meta = QHBoxLayout()
        meta.setSpacing(8)
        for caption, value in (
            ("Time", str(getattr(entry, "datetime_str", ""))),
            ("Model", str(getattr(entry, "model", ""))),
            ("Language", str(getattr(entry, "language", ""))),
            ("Duration", f"{float(getattr(entry, 'duration', 0.0)):.1f}s"),
        ):
            chip = QLabel(f"{caption}: {value}", self)
            chip.setProperty("role", "badge")
            meta.addWidget(chip)
        meta.addStretch(1)
        layout.addLayout(meta)

        # ---- full text body ------------------------------------------------
        self._text = QPlainTextEdit(self)
        self._text.setObjectName("DetailText")
        self._text.setReadOnly(True)
        self._text.setPlainText(str(getattr(entry, "text", "")))
        layout.addWidget(self._text, 1)

        # ---- footer buttons ------------------------------------------------
        buttons = QHBoxLayout()
        copy_btn = QPushButton("Copy text", self)
        copy_btn.setObjectName("DetailCopyButton")
        copy_btn.setProperty("role", "primary")
        copy_btn.clicked.connect(self._on_copy_clicked)
        buttons.addWidget(copy_btn)
        buttons.addStretch(1)
        close_btn = QPushButton("Close", self)
        close_btn.setObjectName("DetailCloseButton")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _on_copy_clicked(self) -> None:
        QApplication.clipboard().setText(self._text.toPlainText())


SEARCH_DEBOUNCE_MS = 200  # ms to wait after last keystroke before filtering


class HistoryView(QWidget):
    clear_requested = Signal()
    copy_requested = Signal(str)
    export_requested = Signal()

    def __init__(
        self,
        search_debounce_ms: int = SEARCH_DEBOUNCE_MS,
        start_hotkey: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("HistoryView")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(10)

        self._header = PageHeader(
            "History",
            "Every dictation and transcription, newest first.",
            self,
        )
        root.addWidget(self._header)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._search = QLineEdit(self)
        self._search.setObjectName("HistorySearchEdit")
        self._search.setPlaceholderText("Search transcriptions…")
        self._search.textChanged.connect(self._on_search_changed)
        controls.addWidget(self._search, 1)

        # Copy is the action this screen exists for, so it is the one
        # accent-filled control here. Clear is destructive and was
        # previously painted identically to Copy — same weight, same
        # colour, one click apart.
        self._copy_btn = QPushButton("Copy", self)
        self._copy_btn.setObjectName("CopyEntryButton")
        self._copy_btn.setProperty("role", "primary")
        self._copy_btn.clicked.connect(self._on_copy_clicked)
        controls.addWidget(self._copy_btn)

        self._export_btn = QPushButton("Export", self)
        self._export_btn.setObjectName("ExportHistoryButton")
        self._export_btn.clicked.connect(self.export_requested.emit)
        controls.addWidget(self._export_btn)

        # "Clear" on its own was the third button in the app wearing
        # that word and meant a third thing — this one destroys the
        # on-disk history, the Logs one destroys the log buffer, and
        # the Settings one discards a stored credential. Two of the
        # three are irreversible. The label names the object, which is
        # the only thing a user has before the click.
        self._clear_btn = QPushButton("Clear history", self)
        self._clear_btn.setObjectName("ClearHistoryButton")
        self._clear_btn.setProperty("role", "danger")
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        controls.addWidget(self._clear_btn)

        root.addLayout(controls)

        self._source_model = HistoryTableModel([])
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._source_model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterKeyColumn(1)  # Text column

        self._pending_search: str = ""
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(search_debounce_ms)
        self._search_timer.timeout.connect(self._apply_search)
        self._install_escape_clears_search()

        # Wrap the table in a card so it reads as a defined surface
        # against the view background instead of floating with no
        # boundaries. The QStackedWidget swaps between the table card
        # and the empty-state placeholder when the entry count crosses
        # zero.
        self._stack = QStackedWidget(self)

        table_card = QFrame(self._stack)
        table_card.setProperty("role", "card")
        table_card.setFrameShape(QFrame.NoFrame)
        card_layout = QVBoxLayout(table_card)
        card_layout.setContentsMargins(2, 2, 2, 2)
        card_layout.setSpacing(0)

        self._table = QTableView(table_card)
        self._table.setObjectName("HistoryTable")
        self._table.setModel(self._proxy)
        self._table.setFrameShape(QTableView.NoFrame)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        apply_smooth_scroll(self._table)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setStretchLastSection(False)
        card_layout.addWidget(self._table)
        self._stack.addWidget(table_card)

        # The instruction is the one line on this screen the user can
        # act on, so the key is a cap rather than part of the sentence.
        # The cap names the *configured* hotkey, not a literal: the
        # shipped default is ``Ctrl+F8`` on macOS because ``Ctrl+F1..7``
        # are the system's, and the user can rebind it in Settings.
        self._start_hotkey = start_hotkey or default_start_hotkey()
        self._empty_state = EmptyState(
            "Nothing dictated yet",
            "Press the start hotkey and speak — every transcription lands "
            "here, newest first.",
            parent=self._stack,
        )
        self._kbd_cap = hotkey_cap(self._start_hotkey, self._empty_state)
        if self._kbd_cap is not None:
            self._empty_state.set_footer(self._kbd_cap)
        self._stack.addWidget(self._empty_state)

        # A search that matches nothing is a *third* state, and it must
        # not borrow the "nothing here yet" one. Telling a user with 40
        # entries that they have dictated nothing — and offering them
        # the start hotkey — is a lie about their own data that sends
        # them off to redo work they already did. This state names the
        # search that came up empty and offers the way back out of it.
        self._no_results = EmptyState(
            "No matching transcriptions",
            "Nothing here contains that text.",
            parent=self._stack,
        )
        self._no_results.set_footer(kbd_chip("Esc to clear", self._no_results))
        self._stack.addWidget(self._no_results)
        # Pre-fetch the table-card reference so ``_update_empty_state``
        # can swap between them by widget identity.
        self._table_card = table_card

        root.addWidget(self._stack, 1)
        self._update_empty_state()

        footer = QHBoxLayout()
        self._count_label = QLabel("0 entries", self)
        self._count_label.setObjectName("HistoryCountLabel")
        self._count_label.setProperty("role", "muted")
        footer.addWidget(self._count_label)
        footer.addStretch(1)
        root.addLayout(footer)

        self._proxy.rowsInserted.connect(self._refresh_count)
        self._proxy.rowsRemoved.connect(self._refresh_count)
        self._proxy.modelReset.connect(self._refresh_count)
        self._proxy.layoutChanged.connect(self._refresh_count)

        # Double-click on any row opens the full-text detail dialog.
        self._table.doubleClicked.connect(self._on_row_double_clicked)

    def set_export_busy(self, busy: bool) -> None:
        """Disable the Export button while a background export is running."""
        is_busy = bool(busy)
        self._export_btn.setEnabled(not is_busy)
        self._export_btn.setText("Exporting…" if is_busy else "Export")

    # ---- public API ---------------------------------------------------------

    def set_entries(self, entries: Sequence[Any]) -> None:
        self._source_model.set_entries(entries)
        self._refresh_count()
        self._update_empty_state()

    def prepend_entry(self, entry: Any, max_entries: int = 0) -> None:
        """Insert one entry at the top without resetting the whole model."""
        self._source_model.prepend_entry(entry, max_entries)
        self._refresh_count()
        self._update_empty_state()

    # ---- internal -----------------------------------------------------------

    def focus_search(self) -> bool:
        """Put the keyboard in this view's search field.

        The contract the window's Find accelerator relies on: a view
        either has a search field and focuses it, or does not carry the
        method at all. Returning the bool lets the caller be honest
        about what happened instead of assuming the caret moved.
        """
        self._search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        return True

    def _on_search_changed(self, text: str) -> None:
        self._pending_search = text
        self._search_timer.start()  # resets countdown on each keystroke

    def _clear_search(self) -> None:
        """Drop the search, including the text a debounce still owes.

        Applied immediately, not through the debounce. The debounce
        exists because typing is a stream and Escape is a decision: left
        on the timer, the screen would sit for a moment with an empty
        field, the old filter still applied, and a count and a panel
        that all describe a search nobody is running any more.
        """
        self._search_timer.stop()
        self._pending_search = ""
        self._search.setText("")
        self._apply_search()

    def _install_escape_clears_search(self) -> None:
        """Escape clears the search, wherever the caret is.

        The no-results state advertises this key, so it has to work — a
        cap naming a shortcut that does nothing is the same lie the
        state was rebuilt to stop telling. It also matches what every
        other list in the OS does, and it is the one keystroke that gets
        a stuck search back without hunting for the field.

        A shortcut rather than ``keyPressEvent``: the caret lives in the
        ``QLineEdit``, which swallows Escape before the view ever sees
        it, so a handler on the view would never run in the one case it
        exists for. ``WidgetWithChildrenShortcut`` covers the field and
        the table both.
        """
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.activated.connect(self._clear_search)

    def _apply_search(self) -> None:
        self._proxy.setFilterFixedString(self._pending_search)
        self._refresh_count()
        # The count was the only thing the search used to update, which
        # is why a search that matched nothing left "Nothing dictated
        # yet" on screen: the table was filtered to empty but nobody
        # asked the stack which of the three states it was now in.
        self._update_empty_state()

    def _refresh_count(self, *_args) -> None:
        """Report what is on screen, and keep the total when it is filtered.

        The proxy count is the right number for "showing N" and the wrong
        one for "you have N": under an active search that matched nothing
        it reads ``0 entries`` to a user with a thousand of them. So the
        count drops the word and names the search instead.
        """
        shown = self._proxy.rowCount()
        total = self._source_model.rowCount()
        if shown == total:
            self._count_label.setText(
                "1 entry" if total == 1 else f"{total} entries"
            )
        else:
            self._count_label.setText(f"{shown} of {total} entries")

    def set_start_hotkey(self, value: str) -> None:
        """Point the empty state's key cap at the user's actual binding.

        Called when the view is built and again whenever Settings saves
        or resets the hotkeys, so the cap cannot drift into naming a
        shortcut the user no longer holds.
        """
        value = str(value or "").strip() or default_start_hotkey()
        if value == self._start_hotkey:
            return
        self._start_hotkey = value
        if self._kbd_cap is not None:
            self._kbd_cap.setText(format_hotkey(value))

    def _update_empty_state(self) -> None:
        """Pick the one of three states the screen is actually in.

        Two are not enough. "Nothing here" and "nothing *matching that*"
        are different facts, and collapsing them makes the app deny the
        data the user is looking at.
        """
        if self._source_model.rowCount() == 0:
            self._stack.setCurrentWidget(self._empty_state)
        elif self._proxy.rowCount() == 0:
            self._stack.setCurrentWidget(self._no_results)
        else:
            self._stack.setCurrentWidget(self._table_card)

    def _on_copy_clicked(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        source_index = self._proxy.mapToSource(rows[0])
        entry = self._source_model.entry_at(source_index.row())
        text = getattr(entry, "text", "")
        if text:
            self.copy_requested.emit(text)

    def _on_row_double_clicked(self, proxy_index) -> None:
        if not proxy_index.isValid():
            return
        source_index = self._proxy.mapToSource(proxy_index)
        try:
            entry = self._source_model.entry_at(source_index.row())
        except IndexError:
            return
        self._open_detail_for_entry(entry)

    def _open_detail_for_entry(self, entry: Any) -> None:
        """Pop the detail dialog for the given entry. Extracted so
        tests can monkeypatch the dialog opening without bringing up
        a real modal window."""
        dialog = HistoryDetailDialog(entry, self)
        dialog.exec()
