"""Tests for the HistoryView and its backing table model."""

from dataclasses import dataclass

import pytest

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QTableView

from app.gui.widgets.empty_state import format_hotkey


@dataclass
class FakeEntry:
    timestamp: float
    text: str
    duration: float
    model: str
    language: str
    # Overridable so the column-width tests can use a real-width stamp
    # without every other test caring what the timestamp looks like.
    stamp: str = "00:00:00 01.01.2026"

    @property
    def datetime_str(self) -> str:
        return self.stamp

    @property
    def short_text(self) -> str:
        return self.text[:50]


def _make_entries(n: int = 3):
    return [
        FakeEntry(
            timestamp=float(i),
            text=f"entry text {i}",
            duration=float(i + 1),
            model="gigaam-v3-ctc",
            language="ru",
        )
        for i in range(n)
    ]


# ---- Table model ------------------------------------------------------------


def test_history_model_reports_row_and_column_counts(qtbot):
    from app.gui.views.history_view import HistoryTableModel

    entries = _make_entries(3)
    model = HistoryTableModel(entries)
    assert model.rowCount() == 3
    assert model.columnCount() == 5


def test_history_model_row_zero_contains_first_entry(qtbot):
    from app.gui.views.history_view import HistoryTableModel

    entries = _make_entries(3)
    model = HistoryTableModel(entries)

    row_zero_text = model.data(model.index(0, 1), Qt.DisplayRole)
    assert row_zero_text == "entry text 0"


def test_history_model_headers_exposed(qtbot):
    from app.gui.views.history_view import HistoryTableModel

    model = HistoryTableModel([])
    headers = [
        model.headerData(i, Qt.Horizontal, Qt.DisplayRole)
        for i in range(model.columnCount())
    ]
    assert headers[0].lower().startswith("time")
    assert "text" in headers[1].lower()
    assert "model" in headers[2].lower()
    assert "lang" in headers[3].lower()
    assert "duration" in headers[4].lower()


def test_history_model_set_entries_replaces_data(qtbot):
    from app.gui.views.history_view import HistoryTableModel

    model = HistoryTableModel([])
    assert model.rowCount() == 0

    model.set_entries(_make_entries(2))
    assert model.rowCount() == 2


def test_history_model_entry_at_returns_original(qtbot):
    from app.gui.views.history_view import HistoryTableModel

    entries = _make_entries(3)
    model = HistoryTableModel(entries)
    assert model.entry_at(0) is entries[0]
    assert model.entry_at(2) is entries[2]
    with pytest.raises(IndexError):
        model.entry_at(99)


# ---- View -------------------------------------------------------------------


def _table(view) -> QTableView:
    return view.findChild(QTableView, "HistoryTable")


def test_history_view_has_expected_widgets(qtbot):
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)

    assert _table(view) is not None
    assert view.findChild(QLineEdit, "HistorySearchEdit") is not None
    assert view.findChild(QPushButton, "CopyEntryButton") is not None
    assert view.findChild(QPushButton, "ClearHistoryButton") is not None
    assert view.findChild(QLabel, "HistoryCountLabel") is not None


def test_set_entries_populates_table(qtbot):
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)

    view.set_entries(_make_entries(3))
    table = _table(view)
    assert table.model().rowCount() == 3


def test_search_filter_narrows_rows(qtbot):
    from app.gui.views.history_view import HistoryView

    view = HistoryView(search_debounce_ms=0)
    qtbot.addWidget(view)

    entries = [
        FakeEntry(0.0, "apple pie", 1.0, "m", "en"),
        FakeEntry(1.0, "banana bread", 1.0, "m", "en"),
        FakeEntry(2.0, "cherry cake", 1.0, "m", "en"),
    ]
    view.set_entries(entries)

    search = view.findChild(QLineEdit, "HistorySearchEdit")
    search.setText("banana")
    qtbot.wait(50)  # let debounce timer fire

    table = _table(view)
    proxy = table.model()
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 1), Qt.DisplayRole) == "banana bread"


def test_count_label_reflects_visible_rows(qtbot):
    from app.gui.views.history_view import HistoryView

    view = HistoryView(search_debounce_ms=0)
    qtbot.addWidget(view)

    view.set_entries(_make_entries(3))

    label = view.findChild(QLabel, "HistoryCountLabel")
    assert "3" in label.text()

    search = view.findChild(QLineEdit, "HistorySearchEdit")
    search.setText("entry text 1")
    qtbot.wait(50)
    assert "1" in label.text()


def test_clear_button_emits_clear_requested(qtbot):
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    view.show()

    btn = view.findChild(QPushButton, "ClearHistoryButton")
    with qtbot.waitSignal(view.clear_requested, timeout=1000):
        qtbot.mouseClick(btn, Qt.LeftButton)


def test_copy_button_emits_copy_requested_with_text(qtbot):
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    view.show()

    entries = _make_entries(3)
    view.set_entries(entries)

    table = _table(view)
    table.selectRow(1)

    btn = view.findChild(QPushButton, "CopyEntryButton")
    with qtbot.waitSignal(view.copy_requested, timeout=1000) as blocker:
        qtbot.mouseClick(btn, Qt.LeftButton)

    assert blocker.args == ["entry text 1"]


def test_copy_button_does_not_emit_when_no_selection(qtbot):
    """Nothing to copy means Copy is *not offered*, not offered and mute.

    The click alone stopped being evidence when the button began
    disabling itself: a disabled button swallows the click, so this
    would have gone on passing against a build that emitted on every
    click. The enabled state is the part that can actually fail.
    """
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    view.show()
    view.set_entries(_make_entries(3))

    emissions: list[str] = []
    view.copy_requested.connect(emissions.append)

    btn = view.findChild(QPushButton, "CopyEntryButton")
    assert btn.isEnabled() is False

    qtbot.mouseClick(btn, Qt.LeftButton)

    assert emissions == []


# ---- Copy is live exactly when it would deliver something ------------------
#
# Copy was accent-filled and clickable on a screen with nothing to copy,
# and did nothing when clicked. The button that says what the app is for
# was lying about there being something to do, which is the one state a
# user cannot tell apart from the app having lost their transcription.
#
# Every test below pins the same single answer — "is there an entry Copy
# would hand over" — and checks it through a different door. That is the
# point: the button, the two keys and the handler used to be four
# independent answers to one question.


def _copy_btn(view) -> QPushButton:
    return view.findChild(QPushButton, "CopyEntryButton")


def _native_copy_modifier() -> Qt.KeyboardModifier:
    """The modifier the running platform actually binds Copy to.

    Derived from ``StandardKey.Copy`` because that is what the shortcut is
    built from: a literal ``Ctrl+C`` in the test would pass on CI and
    prove nothing about the platform where Qt maps that key elsewhere.
    """
    return QKeySequence(QKeySequence.StandardKey.Copy)[0].keyboardModifiers()


def _history_with(entries, qtbot):
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    view.show()
    view.set_entries(entries)
    return view


def _focus(qtbot, widget):
    """Put the keyboard on ``widget`` and prove it landed.

    Two things had to be got right for the assertion to mean anything.
    ``setFocus`` returns nothing, so the only witness is the focus
    itself. And it does not land synchronously: on a widget that was
    just shown, Qt defers the policy change to the next event-loop turn —
    the widget is visible and enabled the whole time, and ``hasFocus``
    is still False. A real click does not show this, because the user
    has given the window the keyboard by then.

    Without the turn, every keyboard test below passes for the wrong
    reason: no shortcut ever matches, and nothing ever emitted.
    """
    widget.setFocus()
    qtbot.wait(1)
    assert widget.hasFocus() is True
    return widget


def _press_copy(qtbot, widget, *, focused: bool = False):
    """Press the platform's Copy key on ``widget``.

    A widget-scoped shortcut is only live while something inside its
    scope holds the focus, so a test that sends the key without focus
    asserts nothing: the shortcut simply never matches.
    """
    if focused:
        _focus(qtbot, widget)
    qtbot.keyClick(widget, Qt.Key_C, _native_copy_modifier())


def test_copy_is_disabled_until_a_row_is_under_the_caret(qtbot):
    view = _history_with(_make_entries(3), qtbot)
    btn = _copy_btn(view)

    assert btn.isEnabled() is False

    _table(view).selectRow(2)
    assert btn.isEnabled() is True

    # ...and off again when the caret leaves. A control that can only be
    # switched on is half a state machine.
    _table(view).clearSelection()
    _table(view).setCurrentIndex(QModelIndex())
    assert btn.isEnabled() is False


def test_copy_is_disabled_while_history_is_empty(qtbot):
    view = _history_with([], qtbot)
    assert _copy_btn(view).isEnabled() is False


def test_copy_goes_disabled_when_history_is_cleared_under_the_caret(qtbot):
    """The row the caret was on does not survive being deleted.

    A user clears History with three hundred entries in it and then finds
    Copy still lit, still accent-filled, and still copying a row that is
    no longer on the screen.
    """
    view = _history_with(_make_entries(3), qtbot)
    _table(view).selectRow(1)
    assert _copy_btn(view).isEnabled() is True

    view.set_entries([])

    assert _copy_btn(view).isEnabled() is False


def test_copy_is_disabled_for_a_row_with_no_transcript(qtbot):
    """An empty row is not a copy.

    Writing "" to the clipboard does not copy the entry — it destroys
    whatever the user had there, and it is reachable: a dictation can
    come back with no text and still land in history.
    """
    entries = _make_entries(2)
    entries[1].text = ""
    view = _history_with(entries, qtbot)

    _table(view).selectRow(1)
    assert _copy_btn(view).isEnabled() is False

    emissions: list[str] = []
    view.copy_requested.connect(emissions.append)
    qtbot.keyClick(_table(view), Qt.Key_Return)
    assert emissions == []


def test_copy_follows_the_caret_when_the_selection_is_cleared(qtbot):
    """The caret is the source, and this is the state that proves it.

    ``clearSelection`` leaves the current row in place. A handler that
    read the selection had nothing to emit here — while the row sat
    highlighted, Copy stayed accent-filled, and the click did nothing.
    """
    view = _history_with(_make_entries(3), qtbot)
    table = _table(view)
    table.selectRow(1)
    table.selectionModel().clearSelection()

    assert table.currentIndex().isValid() is True

    emissions: list[str] = []
    view.copy_requested.connect(emissions.append)
    _press_copy(qtbot, table, focused=True)

    assert emissions == ["entry text 1"]


def test_enter_copies_the_row_under_the_caret(qtbot):
    view = _history_with(_make_entries(3), qtbot)
    table = _table(view)
    table.selectRow(1)
    _focus(qtbot, table)

    with qtbot.waitSignal(view.copy_requested, timeout=1000) as blocker:
        qtbot.keyClick(table, Qt.Key_Return)

    assert blocker.args == ["entry text 1"]


def test_the_platform_copy_key_copies_the_row_under_the_caret(qtbot):
    view = _history_with(_make_entries(3), qtbot)
    table = _table(view)
    table.selectRow(1)
    _focus(qtbot, table)

    with qtbot.waitSignal(view.copy_requested, timeout=1000) as blocker:
        _press_copy(qtbot, table)

    assert blocker.args == ["entry text 1"]


def test_the_copy_key_works_from_the_button_too(qtbot):
    """Focus is on the button, not the table — the key still has to work.

    The shortcut is scoped to the view rather than the table precisely
    so that clicking Copy does not take the keyboard out of the action
    the user just invoked.
    """
    view = _history_with(_make_entries(3), qtbot)
    _table(view).selectRow(1)
    btn = _copy_btn(view)
    _focus(qtbot, btn)

    with qtbot.waitSignal(view.copy_requested, timeout=1000) as blocker:
        _press_copy(qtbot, btn)

    assert blocker.args == ["entry text 1"]


def test_the_copy_key_in_the_search_field_copies_the_search_text(qtbot):
    """The search field owns Copy. Taking it would be the same lie.

    A user who selects what they typed and hits Cmd+C to send it
    somewhere gets a history row instead, and the clipboard they were
    about to paste from now holds the wrong thing.

    The first press is the control: the same key, in the same view, with
    the caret on the table, does copy a row. Without it this test would
    also pass against a build whose shortcut never fires at all.
    """
    view = _history_with(_make_entries(3), qtbot)
    table = _table(view)
    table.selectRow(1)

    emissions: list[str] = []
    view.copy_requested.connect(emissions.append)

    _focus(qtbot, table)
    _press_copy(qtbot, table)
    assert emissions == ["entry text 1"], "control: the shortcut must be live"

    search = view.findChild(QLineEdit, "HistorySearchEdit")
    search.setText("entry text 1")
    search.selectAll()
    _focus(qtbot, search)
    QApplication.clipboard().clear()
    emissions.clear()

    _press_copy(qtbot, search)

    assert emissions == []
    assert QApplication.clipboard().text() == "entry text 1"


def test_enter_in_the_search_field_does_not_copy_a_row(qtbot):
    """Return belongs to the field while the caret is in it.

    Typed a query, pressed Return to accept it — and the screen quietly
    put a transcript on the clipboard instead of running the search.
    """
    view = _history_with(_make_entries(3), qtbot)
    _table(view).selectRow(1)

    search = view.findChild(QLineEdit, "HistorySearchEdit")
    _focus(qtbot, search)

    emissions: list[str] = []
    view.copy_requested.connect(emissions.append)
    qtbot.keyClick(search, Qt.Key_Return)

    assert emissions == []


def test_the_copy_key_in_the_search_field_with_nothing_selected_stays_there(qtbot):
    """The case a selected field hides from you.

    Measured: with text selected, ``QLineEdit`` claims Cmd+C through its
    own Copy action and the shortcut is never reached. With nothing
    selected there is no action to claim it, the OS hands the key to
    the view, and a transcript the user never selected lands on their
    clipboard while they are still typing in the field.

    Driven through ``activated`` rather than a key press, and that is
    the honest limit of what a headless test can do: ``QTest.keyClick``
    delivers straight to the widget and never runs the ShortcutOverride
    handshake Qt uses to decide who owns a key, so a synthetic press
    cannot tell "the field took it" from "the shortcut was live and
    declined". Emitting the signal exercises the decision itself — which
    is the part this app owns.
    """
    view = _history_with(_make_entries(3), qtbot)
    _table(view).selectRow(1)

    search = view.findChild(QLineEdit, "HistorySearchEdit")
    search.setText("entry")
    search.setCursorPosition(0)
    search.deselect()
    _focus(qtbot, search)
    assert search.selectedText() == ""

    emissions: list[str] = []
    view.copy_requested.connect(emissions.append)

    # Control: the same call with the caret on the table does copy, so a
    # pass below is the guard and not a shortcut that never fires.
    _focus(qtbot, view._table)
    view._copy_shortcut.activated.emit()
    assert emissions == ["entry text 1"]
    emissions.clear()

    _focus(qtbot, search)
    view._copy_shortcut.activated.emit()

    assert emissions == []


def test_copy_is_disabled_before_the_first_entries_arrive(qtbot):
    """The window between the view existing and history loading.

    A view that is shown before its first ``set_entries`` had Copy lit,
    because nothing had asked it not to be — and a fresh install shows
    an empty History long before the first dictation exists.
    """
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    view.show()

    assert _copy_btn(view).isEnabled() is False
    assert view._enter_shortcut.isEnabled() is False
    assert view._copy_shortcut.isEnabled() is False


def test_a_search_that_hides_the_current_row_disables_copy(qtbot):
    """The row under the caret leaves the screen and Copy leaves with it.

    The "No matching transcriptions" state is showing, there is nothing
    on screen to copy, and the accent-filled button is still right there
    in the toolbar saying there is.
    """
    view = _history_with(_make_entries(3), qtbot)
    table = _table(view)
    table.selectRow(2)
    assert _copy_btn(view).isEnabled() is True

    view._search.setText("nothing matches this")
    view._apply_search()

    assert view._stack.currentWidget() is view._no_results
    assert _copy_btn(view).isEnabled() is False
    # The keys go dark with the button. Nothing could deliver a key to
    # them here anyway — the table is behind the no-results page — but
    # a live shortcut is the same mismatch one control further out.
    assert view._copy_shortcut.isEnabled() is False
    assert view._enter_shortcut.isEnabled() is False

    emissions: list[str] = []
    view.copy_requested.connect(emissions.append)
    view._on_copy_clicked()
    assert emissions == []


def test_a_capped_prepend_keeps_copy_pointing_at_the_same_entry(qtbot):
    """A new dictation arrives and pushes the oldest one out.

    The caret follows its entry down the list rather than staying on a
    row number, so Copy keeps naming the transcript the user picked —
    which is the whole reason it reads the caret and not the row.
    """
    view = _history_with(_make_entries(3), qtbot)
    table = _table(view)
    table.selectRow(0)  # the oldest — the row a capped prepend drops
    assert _copy_btn(view).isEnabled() is True

    incoming = FakeEntry(
        timestamp=99.0, text="the newest one", duration=1.0,
        model="gigaam-v3-ctc", language="ru",
    )
    view.prepend_entry(incoming, max_entries=3)

    assert view._proxy.rowCount() == 3
    emissions: list[str] = []
    view.copy_requested.connect(emissions.append)
    _press_copy(qtbot, table, focused=True)
    assert emissions == ["entry text 0"], "Copy stopped naming the chosen entry"


def test_the_copy_keys_go_dark_exactly_when_the_button_does(qtbot):
    """One question, one answer — including for the two shortcuts.

    A shortcut left live while the button is greyed out is the same
    mismatch one control further out: the two ways of asking for a copy
    disagree about whether there is one to give.
    """
    view = _history_with(_make_entries(3), qtbot)
    btn = _copy_btn(view)

    assert btn.isEnabled() is False
    assert view._enter_shortcut.isEnabled() is False
    assert view._copy_shortcut.isEnabled() is False

    _table(view).selectRow(1)
    assert btn.isEnabled() is True
    assert view._enter_shortcut.isEnabled() is True
    assert view._copy_shortcut.isEnabled() is True


def test_the_copy_button_names_the_keys_it_accepts(qtbot):
    """A key nothing mentions is a feature nobody finds.

    The names come from the platform, not from a literal: the shortcut
    is ``StandardKey.Copy``, so a hardcoded "Ctrl+C" would tell a Mac
    user about a key their keyboard does not have.
    """
    view = _history_with(_make_entries(3), qtbot)
    native = QKeySequence.SequenceFormat.NativeText
    tooltip = _copy_btn(view).toolTip()

    assert QKeySequence(Qt.Key_Return).toString(native) in tooltip
    assert QKeySequence(QKeySequence.StandardKey.Copy).toString(native) in tooltip


def test_history_model_exposes_full_text_via_tooltip(qtbot):
    """Long transcripts are ellipsised in the table, so the tooltip
    must carry the full text — quick hover-peek without opening the
    detail dialog."""
    from app.gui.views.history_view import HistoryTableModel

    long_text = "a long transcription that overflows the column width " * 4
    entry = FakeEntry(
        timestamp=0.0, text=long_text, duration=1.0,
        model="gigaam-v3-ctc", language="ru",
    )
    model = HistoryTableModel([entry])
    text_index = model.index(0, 1)  # Text column
    assert model.data(text_index, Qt.ToolTipRole) == long_text


def test_history_detail_dialog_shows_full_entry(qtbot):
    """The detail dialog must surface every field — full text, time,
    model, language, duration — so the user can read what got
    transcribed without round-tripping through the clipboard."""
    from app.gui.views.history_view import HistoryDetailDialog

    entry = FakeEntry(
        timestamp=0.0,
        text="full transcription body that's too long for the table cell",
        duration=12.5,
        model="gigaam-v3-ctc",
        language="ru",
    )
    dialog = HistoryDetailDialog(entry)
    qtbot.addWidget(dialog)
    assert dialog._text.toPlainText() == entry.text
    rendered = " ".join(
        lbl.text() for lbl in dialog.findChildren(QLabel)
    )
    assert "gigaam-v3-ctc" in rendered
    assert "ru" in rendered
    assert "12.5" in rendered


def test_history_detail_dialog_copy_button_copies_text(qtbot):
    """The dialog's Copy button must put the full text on the
    clipboard so the user can paste it elsewhere."""
    from PySide6.QtWidgets import QApplication
    from app.gui.views.history_view import HistoryDetailDialog

    entry = FakeEntry(
        timestamp=0.0, text="transcribed words", duration=1.0,
        model="gigaam-v3-ctc", language="ru",
    )
    dialog = HistoryDetailDialog(entry)
    qtbot.addWidget(dialog)

    QApplication.clipboard().clear()
    btn = next(
        b for b in dialog.findChildren(QPushButton)
        if b.objectName() == "DetailCopyButton"
    )
    btn.click()
    assert QApplication.clipboard().text() == "transcribed words"


def test_history_view_double_click_opens_detail(qtbot, monkeypatch):
    """Double-clicking a row must surface the full transcript, not
    just toggle selection — that's how the user reads long entries
    when the table cell ellipsises."""
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)

    captured: list = []

    def fake_open(self, entry):
        captured.append(entry)

    monkeypatch.setattr(HistoryView, "_open_detail_for_entry", fake_open)

    entries = _make_entries(2)
    view.set_entries(entries)

    # Simulate double-click on first row — bypass mouse mechanics by
    # invoking the slot directly via the underlying signal.
    proxy_index = view._proxy.index(0, 1)
    view._table.doubleClicked.emit(proxy_index)

    assert len(captured) == 1
    assert captured[0] is entries[0]


def test_history_view_uses_pixel_scroll_mode(qtbot):
    """History table should scroll smoothly per pixel, not per row,
    matching the rest of the UI's scroll feel."""
    from PySide6.QtWidgets import QAbstractItemView
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    assert view._table.verticalScrollMode() == QAbstractItemView.ScrollPerPixel


def test_history_view_shows_empty_state_when_no_entries(qtbot):
    """A blank table is unfriendly — surface a 'press the hotkey'
    placeholder when there's nothing to show."""
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    view.set_entries([])
    assert view._stack.currentWidget() is view._empty_state


def test_history_view_swaps_to_table_when_entries_arrive(qtbot):
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    view.set_entries(_make_entries(2))
    assert view._stack.currentWidget() is view._table_card


def test_history_model_column_shows_short_alias(qtbot):
    """The Model column should display the registry alias
    (``large-v3``, ``turbo-int8``) rather than the full canonical id
    (``istupakov/gigaam-v3-onnx``) — it's what the user
    actually picked, and short enough not to truncate."""
    from app.gui.views.history_view import HistoryTableModel

    entry = FakeEntry(
        timestamp=0.0,
        text="x",
        duration=1.0,
        model="istupakov/gigaam-v3-onnx",
        language="ru",
    )
    model = HistoryTableModel([entry])
    cell = model.data(model.index(0, 2), Qt.DisplayRole)
    assert cell == "gigaam-v3-ctc"


def test_history_model_column_tooltip_shows_full_canonical(qtbot):
    """Hovering still reveals the full canonical id for power users
    who want to know exactly which Hugging Face repo was used."""
    from app.gui.views.history_view import HistoryTableModel

    entry = FakeEntry(
        timestamp=0.0,
        text="x",
        duration=1.0,
        model="istupakov/gigaam-v3-onnx",
        language="ru",
    )
    model = HistoryTableModel([entry])
    tooltip = model.data(model.index(0, 2), Qt.ToolTipRole)
    assert tooltip == "istupakov/gigaam-v3-onnx"


def test_history_model_column_passes_unknown_canonical_through(qtbot):
    """If the model isn't in the registry (legacy entry, custom HF
    id), display it as-is so the data isn't lost."""
    from app.gui.views.history_view import HistoryTableModel

    entry = FakeEntry(
        timestamp=0.0,
        text="x",
        duration=1.0,
        model="some-org/custom-model",
        language="en",
    )
    model = HistoryTableModel([entry])
    cell = model.data(model.index(0, 2), Qt.DisplayRole)
    assert cell == "some-org/custom-model"


# ---- prepend_entry ----------------------------------------------------------


# ---- Search debounce --------------------------------------------------------


def test_history_search_debounce_does_not_filter_immediately(qtbot):
    """Typing must not filter the table until the debounce timer fires.
    Without this, every keystroke causes a full QSortFilterProxyModel pass."""
    from app.gui.views.history_view import HistoryView

    DEBOUNCE_MS = 120
    view = HistoryView(search_debounce_ms=DEBOUNCE_MS)
    qtbot.addWidget(view)

    entries = [
        FakeEntry(0.0, "alpha text", 1.0, "m", "en"),
        FakeEntry(1.0, "beta text", 1.0, "m", "en"),
    ]
    view.set_entries(entries)

    # Simulate a keystroke without waiting.
    view._on_search_changed("alpha")

    # Immediately after: both rows must still be visible (no filter yet).
    proxy = _table(view).model()
    assert proxy.rowCount() == 2, (
        "Filter must not apply synchronously on keystroke"
    )

    # After debounce fires: only the matching row survives.
    qtbot.wait(DEBOUNCE_MS + 60)
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 1), Qt.DisplayRole) == "alpha text"


def test_history_search_debounce_rapid_keystrokes_single_filter(qtbot):
    """Five rapid keystrokes must not apply the filter five times."""
    from app.gui.views.history_view import HistoryView

    DEBOUNCE_MS = 120
    view = HistoryView(search_debounce_ms=DEBOUNCE_MS)
    qtbot.addWidget(view)
    view.set_entries(_make_entries(3))

    proxy = _table(view).model()

    # Rapid partial inputs — each restarts the timer.
    for prefix in ("e", "en", "ent", "entr", "entry"):
        view._on_search_changed(prefix)

    # Still unfiltered (timer hasn't fired).
    assert proxy.rowCount() == 3

    # After debounce: all three entries match "entry" → still 3.
    qtbot.wait(DEBOUNCE_MS + 60)
    assert proxy.rowCount() == 3  # "entry text N" all match


def test_history_search_debounce_timer_is_single_shot(qtbot):
    """The debounce timer must be single-shot so filtering stops after
    one pass and doesn't keep running on a fixed interval."""
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    assert view._search_timer.isSingleShot()


# ---- prepend_entry ----------------------------------------------------------


def test_history_model_prepend_entry_inserts_at_top(qtbot):
    """prepend_entry must place the new entry at row 0, not the bottom."""
    from app.gui.views.history_view import HistoryTableModel

    model = HistoryTableModel(_make_entries(2))
    new_entry = FakeEntry(99.0, "newest", 1.0, "m", "en")
    model.prepend_entry(new_entry)

    assert model.rowCount() == 3
    assert model.data(model.index(0, 1), Qt.DisplayRole) == "newest"


def test_history_model_prepend_entry_emits_rows_inserted_not_model_reset(qtbot):
    """prepend_entry must emit rowsInserted, NOT modelReset.

    A full reset discards the view's scroll position and selection on
    every transcription — catastrophic UX when history is long.
    """
    from app.gui.views.history_view import HistoryTableModel

    model = HistoryTableModel(_make_entries(2))

    reset_fired: list = []
    inserted_fired: list = []
    model.modelReset.connect(lambda: reset_fired.append(True))
    model.rowsInserted.connect(lambda *_: inserted_fired.append(True))

    model.prepend_entry(FakeEntry(99.0, "newest", 1.0, "m", "en"))

    assert reset_fired == [], "modelReset must NOT fire on prepend_entry"
    assert inserted_fired != [], "rowsInserted must fire on prepend_entry"


def test_history_model_prepend_trims_oldest_when_over_cap(qtbot):
    """When max_entries is exceeded after a prepend, the oldest row is dropped."""
    from app.gui.views.history_view import HistoryTableModel

    model = HistoryTableModel(_make_entries(3))  # [text 0, text 1, text 2]
    model.prepend_entry(FakeEntry(99.0, "newest", 1.0, "m", "en"), max_entries=3)

    assert model.rowCount() == 3
    texts = [model.data(model.index(r, 1), Qt.DisplayRole) for r in range(3)]
    assert texts[0] == "newest"
    assert "entry text 2" not in texts  # oldest dropped


def test_history_view_prepend_entry_adds_row_at_top(qtbot):
    """HistoryView.prepend_entry delegates to the model and updates the count."""
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    view.set_entries(_make_entries(2))

    view.prepend_entry(FakeEntry(99.0, "newest", 1.0, "m", "en"))

    proxy = _table(view).model()
    assert proxy.rowCount() == 3
    assert proxy.data(proxy.index(0, 1), Qt.DisplayRole) == "newest"

    label = view.findChild(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel,
                           "HistoryCountLabel")
    assert "3" in label.text()


# ---- the search that matches nothing ---------------------------------------
#
# Two of these used to fail, and both failed the same way: the app
# told the user they had dictated nothing while their own transcriptions
# sat filtered out of sight one field above the claim.


def test_a_search_matching_nothing_does_not_claim_history_is_empty(qtbot):
    """The screen has three states, not two.

    With entries on disk and a search that matches none of them, the
    "Nothing dictated yet" panel is a lie about the user's own data —
    and it names the start hotkey, so it also sends them off to redo
    work they already did. The no-results state has to be its own.
    """
    from app.gui.views.history_view import HistoryView

    view = HistoryView(search_debounce_ms=0)
    qtbot.addWidget(view)
    view.set_entries(_make_entries(3))

    search = view.findChild(QLineEdit, "HistorySearchEdit")
    search.setText("absolutely-not-present")
    qtbot.wait(50)

    # Which of the three is showing is the contract; ``isVisible`` is not,
    # because a child of a widget the test never showed is never visible
    # and the assertion would be about the harness, not the view.
    assert view._stack.currentWidget() is view._no_results
    assert view._stack.currentWidget() is not view._empty_state, (
        "the 'nothing dictated yet' state must not stand in for "
        "'nothing matched your search'"
    )


def test_the_no_results_state_says_what_happened(qtbot):
    """Name the situation and offer the way out of it."""
    from app.gui.views.history_view import HistoryView

    view = HistoryView(search_debounce_ms=0)
    qtbot.addWidget(view)
    view.set_entries(_make_entries(3))
    search = view.findChild(QLineEdit, "HistorySearchEdit")
    search.setText("absent")
    qtbot.wait(50)

    texts = [lbl.text() for lbl in view._no_results.findChildren(QLabel) if lbl.text()]
    assert any("No matching" in t for t in texts), texts
    # The key cap names a shortcut, so the shortcut has to exist.
    assert any("Esc" in t for t in texts), texts


def test_clearing_the_search_restores_the_first_state(qtbot):
    """Empty history and filtered-to-nothing must be reversible states."""
    from app.gui.views.history_view import HistoryView

    view = HistoryView(search_debounce_ms=0)
    qtbot.addWidget(view)
    view.set_entries(_make_entries(3))
    search = view.findChild(QLineEdit, "HistorySearchEdit")
    search.setText("absent")
    qtbot.wait(50)
    assert view._stack.currentWidget() is view._no_results

    search.setText("")
    qtbot.wait(50)
    assert view._stack.currentWidget() is view._table_card


def test_escape_clears_the_search_and_shows_the_table_again(qtbot):
    """The cap advertises Escape, so Escape works — from the field, which
    is where the caret is and where a view-level keyPressEvent would
    never see it."""
    from app.gui.views.history_view import HistoryView

    view = HistoryView(search_debounce_ms=0)
    qtbot.addWidget(view)
    view.show()
    view.set_entries(_make_entries(3))
    search = view.findChild(QLineEdit, "HistorySearchEdit")
    search.setText("absent")
    qtbot.wait(50)
    assert view._no_results.isVisible() is True

    search.setFocus()
    qtbot.wait(10)
    qtbot.keyClick(search, Qt.Key_Escape)
    qtbot.wait(50)

    assert search.text() == ""
    assert view._no_results.isVisible() is False
    assert _table(view).isVisible() is True


def test_escape_applies_immediately_rather_than_waiting_for_the_debounce(qtbot):
    """Escape is a decision, typing is a stream.

    Left on the debounce timer, the screen sits with an empty field and
    the old filter still applied — a count and a panel that all describe
    a search nobody is running any more.
    """
    from PySide6.QtWidgets import QApplication

    from app.gui.views.history_view import HistoryView

    view = HistoryView(search_debounce_ms=5000)  # long enough to be obvious
    qtbot.addWidget(view)
    view.show()
    view.set_entries(_make_entries(3))
    search = view.findChild(QLineEdit, "HistorySearchEdit")
    search.setText("absent")
    # Reach the filtered state by applying it directly: the whole point
    # of the long debounce is that waiting for the timer must NOT be how
    # Escape gets its job done, so the timer cannot be used to get here
    # either.
    view._apply_search()
    assert view._stack.currentWidget() is view._no_results

    search.setFocus()
    qtbot.wait(10)
    qtbot.keyClick(search, Qt.Key_Escape)
    # No wait: the whole point is that the state is already correct.
    QApplication.processEvents()
    assert view._stack.currentWidget() is view._table_card


def test_count_keeps_the_total_when_a_search_filters(qtbot):
    """``0 entries`` to a user with 40 of them is false.

    The proxy count is the right number for "showing N" and the wrong
    one for "you have N", so the label has to carry both.
    """
    from app.gui.views.history_view import HistoryView

    view = HistoryView(search_debounce_ms=0)
    qtbot.addWidget(view)
    view.set_entries(_make_entries(3))
    label = view.findChild(QLabel, "HistoryCountLabel")

    search = view.findChild(QLineEdit, "HistorySearchEdit")
    search.setText("absent")
    qtbot.wait(50)

    text = label.text()
    assert text == "0 of 3 entries", text

    search.setText("entry text 1")
    qtbot.wait(50)
    assert label.text() == "1 of 3 entries", label.text()


def test_count_is_singular_for_one_entry(qtbot):
    from app.gui.views.history_view import HistoryView

    view = HistoryView(search_debounce_ms=0)
    qtbot.addWidget(view)
    view.set_entries(_make_entries(1))
    assert view.findChild(QLabel, "HistoryCountLabel").text() == "1 entry"


# ---- the key cap names a key the user holds -------------------------------


def test_key_cap_uses_the_platform_default_not_a_literal(qtbot):
    """``Ctrl+F2`` hardcoded is the wrong key on macOS.

    macOS reserves ``Ctrl+F1..F7`` for system navigation, so the shipped
    start hotkey there is ``Ctrl+F8``. A cap that names a shortcut the
    platform cannot receive is worse than no cap.
    """
    from app.config_manager import default_start_hotkey
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)

    cap = view._kbd_cap
    assert cap is not None
    assert cap.text() == format_hotkey(default_start_hotkey())
    assert view._empty_state._title.text() == "Nothing dictated yet"


def test_key_cap_follows_a_rebind(qtbot):
    from app.gui.views.history_view import HistoryView

    view = HistoryView(start_hotkey="ctrl+f8")
    qtbot.addWidget(view)
    assert view._kbd_cap.text() == "Ctrl+F8"

    view.set_start_hotkey("cmd+shift+k")
    assert view._kbd_cap.text() == "Cmd+Shift+K"


def test_key_cap_falls_back_to_the_default_when_the_binding_is_blank(qtbot):
    from app.config_manager import default_start_hotkey
    from app.gui.views.history_view import HistoryView

    view = HistoryView(start_hotkey="ctrl+f8")
    qtbot.addWidget(view)

    view.set_start_hotkey("   ")
    assert view._kbd_cap.text() == format_hotkey(default_start_hotkey())


def test_transcribe_key_cap_uses_the_platform_default_not_a_literal(qtbot):
    """The History view had this test and Transcribe did not, so a
    hardcoded ``"ctrl+f2"`` in *its* constructor passed every guard in
    the file. A mutation confirmed it. The default is the value most
    users will ever see, so it is the one that must be right."""
    from app.config_manager import default_start_hotkey
    from app.gui.views.transcribe_view import TranscribeView

    view = TranscribeView()
    qtbot.addWidget(view)

    assert view._kbd_cap is not None
    assert view._kbd_cap.text() == format_hotkey(default_start_hotkey())


def test_transcribe_key_cap_follows_the_same_rule(qtbot):
    from app.gui.views.transcribe_view import TranscribeView

    view = TranscribeView()
    qtbot.addWidget(view)
    assert view._kbd_cap is not None

    view.set_start_hotkey("cmd+alt+f4")
    assert view._kbd_cap.text() == "Cmd+Alt+F4"


def test_no_empty_state_hardcodes_a_hotkey_anymore():
    """Source guard, because a literal here is invisible to every test
    above — they all read the value the view was given, and a re-hardcode
    would pass all of them while the cap quietly goes back to lying.

    The same trap the Find accelerator's ``StandardKey`` guard hit.
    """
    from pathlib import Path

    import app.gui.views.history_view as hv
    import app.gui.views.transcribe_view as tv

    for module in (hv, tv):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "hotkey_cap(" in source, module.__name__
        # Precise on purpose. ``kbd_chip`` is also how the no-results
        # state prints "Esc to clear", which is a fixed key name and
        # not a rebindable binding — banning every literal would ban
        # that one too. The invariant is about the *default binding*:
        # a literal here reads identically in every test that builds the
        # view and then calls the setter, which is exactly how a
        # hardcoded ``"ctrl+f2"`` passed all 41 of them.
        assert "_start_hotkey = start_hotkey or default_start_hotkey()" in source, (
            f"{module.__name__}: the cap's default must come from "
            f"default_start_hotkey(), not a literal"
        )
        assert '_start_hotkey = "' not in source, (
            f"{module.__name__}: a hardcoded default hotkey"
        )


# ---- Column widths ---------------------------------------------------------


def _header(view):
    return _table(view).horizontalHeader()


def _sizes(view) -> list:
    header = _header(view)
    return [header.sectionSize(i) for i in range(header.count())]


def _column(name: str) -> int:
    from app.gui.views.history_view import _HEADERS

    return _HEADERS.index(name)


def _shown_view(qtbot, entries, width: int = 900):
    """A shown view holding *entries* — fitting needs real font metrics."""
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    view.resize(width, 620)
    view.show()
    QApplication.processEvents()
    view.set_entries(entries)
    QApplication.processEvents()
    return view


def _columns():
    """``(index, name)`` for every column the view fits by hand."""
    from app.gui.views.history_view import _FITTED_COLUMNS, _HEADERS

    return [(col, _HEADERS[col]) for col in _FITTED_COLUMNS]


def _label_floor(view, name):
    """Width a header label needs to stay readable in its section.

    Two things eat into a section beyond the label's own advance: the
    style's header margin on each side, and the sort mark
    ``QHeaderView`` reserves inside every section. Both come from the
    live style, so this is the same arithmetic the view does.
    """
    from PySide6.QtWidgets import QStyle

    header = _header(view)
    style = header.style()
    slack = (
        2 * style.pixelMetric(QStyle.PixelMetric.PM_HeaderMargin, None, header)
        + style.pixelMetric(QStyle.PixelMetric.PM_HeaderMarkSize, None, header)
    )
    return _table(view).fontMetrics().horizontalAdvance(name) + slack


def _worst_headers(view):
    """Columns whose header label does not fit, as ``(name, have, need)``."""
    header = _header(view)
    tight = []
    for col, name in _columns():
        needed = _label_floor(view, name)
        have = header.sectionSize(col)
        if have < needed:
            tight.append((name, have, needed))
    return tight


def _worst_fit(view):
    """Columns too narrow for what they hold, as ``(name, have, need)``.

    Both halves matter, and a cell-only check misses the second: the
    header labels elided to "anguag" and "uratior" on a build where
    every cell fitted, because ``QHeaderView`` keeps a sort-mark reserve
    inside each section that the cell margin does not cover.
    """
    header = _header(view)
    metrics = _table(view).fontMetrics()
    model = view._source_model
    tight = []
    for col, name in _columns():
        widest_cell = max(
            (metrics.horizontalAdvance(model.cell_text(row, col))
             for row in range(model.rowCount())),
            default=0,
        )
        # The cell delegate's own margin has to survive the fit too, or
        # the text sits flush against the column edge.
        needed = max(widest_cell + 4, _label_floor(view, name))
        have = header.sectionSize(col)
        if have < needed:
            tight.append((name, have, needed))
    return tight


def test_columns_are_wide_enough_for_their_content(qtbot):
    """The defect: every fixed column sat at 100px whatever the window
    was, so the timestamp — 132px of it — was cut on every screen size.
    """
    entries = [
        FakeEntry(
            timestamp=float(i),
            text=f"entry text {i}",
            duration=float(i + 1),
            model="istupakov/gigaam-v3-onnx",
            language="ru",
        )
        for i in range(12)
    ]
    for width in (900, 1100, 1400):
        view = _shown_view(qtbot, entries, width=width)
        assert _worst_fit(view) == [], f"at {width}px wide"


def test_time_column_clears_the_old_hundred_pixel_default(qtbot):
    """Named because the 100px it replaced came from Qt, not from us."""
    entries = _make_entries(4)
    view = _shown_view(qtbot, entries)

    assert _header(view).sectionSize(_column("Time")) > 100


def test_widest_cell_in_the_last_row_still_fits(qtbot):
    """A sampled width would miss this; a full pass does not.

    The long value sits in the final row on purpose — the case that
    ``setResizeContentsPrecision`` gets wrong. The window is wide on
    purpose too: what this covers is that nothing is sampled away, and a
    window that cannot hold the content is
    ``test_columns_yield_before_the_table_scrolls``'s subject.
    """
    entries = _make_entries(40)
    entries[-1].model = "parakeet-tdt-0.6b-v3-en-an-unusually-long-canonical-alias"
    entries[-1].language = "yue-Hant-HK"
    view = _shown_view(qtbot, entries, width=1900)

    assert _worst_fit(view) == []
    widest = max(
        _table(view).fontMetrics().horizontalAdvance(e.model) for e in entries
    )
    assert _header(view).sectionSize(_column("Model")) >= widest + 4


def test_columns_yield_before_the_table_scrolls(qtbot):
    """Fitted to their content the four identity columns do not always
    fit beside the transcript — at 175% text in a 900px window they want
    628px of a 624px viewport. The transcript keeps its share and the
    identity columns give up width down to their own header labels,
    rather than Qt answering with a 3px horizontal scrollbar over a
    transcript squeezed to 25px.
    """
    from app.gui.theme import apply_text_scale
    from app.gui.views.history_view import _TRANSCRIPT_MINIMUM_RATIO

    entries = _make_entries(30)
    view = _shown_view(qtbot, entries, width=700)
    app = QApplication.instance()
    try:
        apply_text_scale(app, 1.75)
        qtbot.wait(20)  # the re-fit is deferred one event-loop turn
        table = _table(view)
        header = _header(view)
        fixed = sum(header.sectionSize(i) for i in range(4))
        share = header.sectionSize(1) / table.viewport().width()
        assert fixed < table.viewport().width(), "the fixed columns ate the table"

        assert table.horizontalScrollBar().maximum() == 0, "the table scrolls"
        assert share >= _TRANSCRIPT_MINIMUM_RATIO - 0.02, (
            f"the transcript got {share:.0%} of the table"
        )
        # The headers are what a squeezed row must not lose: they are
        # the floor the columns shrink to.
        assert _worst_headers(view) == []
    finally:
        apply_text_scale(app, 1.0)
        qtbot.wait(20)


def test_resizing_the_window_re_balances_the_columns(qtbot):
    """The measured widths are cached and re-applied against the width the
    table has now, so a window that is dragged in from 1400px does not
    keep handing the columns the width it needed out there.
    """
    entries = _make_entries(6)
    entries[-1].model = "parakeet-tdt-0.6b-v3-en-an-unusually-long-canonical-alias"
    view = _shown_view(qtbot, entries, width=1400)
    assert _worst_fit(view) == [], "the wide window should have had room"
    roomy = _sizes(view)

    view.resize(700, 620)
    QApplication.processEvents()

    assert _table(view).horizontalScrollBar().maximum() == 0, "the table scrolls"
    assert _worst_headers(view) == [], "a header was traded away"
    assert _sizes(view) != roomy, "the columns did not move at all"


def test_shrinking_always_makes_progress(qtbot):
    """An excess of a single pixel must not wedge the loop that hands the
    width out.

    Four equal columns one pixel over budget split that pixel four ways,
    every share rounds to zero, nothing moves, and the loop that was
    going to fix the overflow spins forever instead — the window stops
    answering drags. So a cut is never allowed to be less than a pixel
    while the column still has room to give one.
    """
    from app.gui.views.history_view import _TRANSCRIPT_MINIMUM_RATIO

    view = _shown_view(qtbot, _make_entries(4), width=900)
    table = _table(view)
    viewport = table.viewport().width()
    budget = viewport - int(viewport * _TRANSCRIPT_MINIMUM_RATIO)

    columns = [col for col, _ in _columns()]
    target = budget + 1
    share, remainder = divmod(target, len(columns))
    view._fitted_widths = {
        col: share + (1 if i < remainder else 0) for i, col in enumerate(columns)
    }
    view._label_widths = {col: 20 for col in columns}

    view._apply_column_widths()

    assert sum(view._fitted_widths.values()) == target
    header = _header(view)
    assert sum(header.sectionSize(col) for col in columns) <= budget


def test_columns_follow_the_text_scale(qtbot):
    """Widths are measured, not hardcoded — 175% has to fit too."""
    from app.gui.theme import apply_text_scale

    entries = _make_entries(8)
    view = _shown_view(qtbot, entries)
    at_default = _sizes(view)
    assert _worst_fit(view) == []

    app = QApplication.instance()
    try:
        apply_text_scale(app, 1.75)
        qtbot.wait(20)  # the re-fit is deferred one event-loop turn
        at_large = _sizes(view)
    finally:
        apply_text_scale(app, 1.0)
        qtbot.wait(20)

    assert at_large[0] > at_default[0], "Time did not grow with the text"
    assert _worst_fit(view) == []


def test_apply_column_widths_before_the_first_fit_hands_out_nothing(qtbot):
    """An unmeasured view has no widths to apply, and applying the empty
    set is a crash, not a no-op.

    The two width dicts are documented as empty until the first fit, and
    the sections are meant to keep their defaults until then. But
    ``eventFilter`` re-fits on *every* viewport Resize, and the first
    Resize arrives when the window is first shown — which on a view
    nobody has populated is strictly before the first ``set_entries``.
    Indexing an empty dict there raises out of a Qt event filter, and
    PySide6 answers an exception escaping a filter by taking the whole
    process down. So the no-op is the contract, and it is asserted here
    directly: called as a plain Python call it fails this test cleanly,
    instead of the paint path failing as a signal.
    """
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)

    assert view._fitted_widths == {}, "precondition: nothing has been measured"
    assert view._label_widths == {}, "precondition: nothing has been measured"

    # Must not raise. The sections are left exactly as they were.
    before = _sizes(view)
    view._apply_column_widths()
    assert _sizes(view) == before, "an unmeasured view must keep its defaults"


def test_window_survives_its_first_paint_with_an_unpopulated_history(qtbot):
    """The shape that actually took the process down, end to end.

    An ``AppController`` built without a history manager never calls
    ``set_entries``, so the HistoryView reaches its first paint with
    nothing measured. The window has to come up regardless.

    This is the honest witness — a regression here does not fail one
    test, it takes pytest with it, which is exactly the failure mode
    being pinned down.
    """
    from app.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)

    history = window.history_view
    # Empty the width state explicitly rather than trusting that nothing
    # has measured this view yet. An earlier test in this file changes
    # the application font, and a font change lands on a fresh view as a
    # ``changeEvent`` that schedules the deferred re-fit — so by the
    # time this window is shown the view may already have been measured
    # by an empty table, and the shape under test would be gone. The
    # bug is specifically the fit running *before* any measurement, so
    # that is the state to set up.
    history._fitted_widths.clear()
    history._label_widths.clear()

    window.show()
    QApplication.processEvents()

    # The history page is *not* the one on screen — Models is. That is
    # the whole shape of the bug: a ``QStackedWidget`` lays out and
    # resizes its hidden pages anyway, so the table viewport gets its
    # first Resize — and therefore its first call into the fit — while
    # the page is off screen. Asserting on ``isVisible`` as the proof of
    # a paint would be the classic Qt trap and would quietly stop
    # testing anything.
    assert window.stack.currentWidget() is not history
    assert not history.isVisibleTo(window), "precondition: history is off screen"
    assert history._table.viewport().width() > 0, (
        "precondition: the hidden page was still laid out, so the "
        "Resize-driven fit really did run against it"
    )
    assert window.isVisible(), "the window did not survive its first paint"
    assert len(_sizes(history)) == 5, "the header came up with all its sections"


def test_header_labels_are_not_elided(qtbot):
    """The regression the first version of this fit shipped with: every
    cell fitted and the labels still came out as "anguag" and "uratior",
    because a section has to clear the sort-mark reserve as well as the
    cell margin.

    Asserted through Qt's own elide check rather than by restating the
    arithmetic, so the test says what the header does, not what the
    implementation assumed.
    """
    from PySide6.QtWidgets import QStyle

    from app.gui.views.history_view import _FITTED_COLUMNS, _HEADERS

    view = _shown_view(qtbot, _make_entries(6))
    header = _header(view)
    metrics = _table(view).fontMetrics()
    style = header.style()
    margins = 2 * style.pixelMetric(QStyle.PixelMetric.PM_HeaderMargin, None, header)
    mark = style.pixelMetric(QStyle.PixelMetric.PM_HeaderMarkSize, None, header)

    for col in _FITTED_COLUMNS:
        label = _HEADERS[col]
        available = header.sectionSize(col) - margins - mark
        assert metrics.elidedText(label, Qt.ElideRight, available) == label, (
            f"the {label!r} header is elided at {header.sectionSize(col)}px"
        )


def test_re_fit_does_not_outlive_the_view(qtbot):
    """The deferred re-fit must be scheduled on the view, and must not be
    able to fire at a dead one.

    ``QTimer.singleShot(0, self._fit_columns)`` schedules on a timer with
    no receiver: it survives the view that asked for it and then runs
    ``_fit_columns`` against a table whose C++ object is gone. The
    RuntimeError surfaces in whatever event-loop turn comes next, which
    is how it reached tests for a screen that has nothing to do with
    History. A child timer is owned by the view and dies with it.

    Two halves, because they fail in different ways: the first asserts
    the re-fit really is on the view's own timer, the second lets the
    pending turn come due after the view is gone — a RuntimeError raised
    inside the event loop fails the test through pytest-qt.
    """
    from PySide6.QtCore import QEvent

    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    view.set_entries(_make_entries(4))

    QApplication.sendEvent(view, QEvent(QEvent.Type.StyleChange))
    assert view._refit_timer.isSingleShot()
    assert view._refit_timer.isActive(), "the re-fit is not on the view's timer"

    view.deleteLater()
    QApplication.processEvents()  # the view is gone; the pending turn is not
    qtbot.wait(20)


def test_transcript_column_absorbs_the_extra_width(qtbot):
    """Only the transcript is elastic; the identity columns hold still."""
    entries = _make_entries(8)
    narrow = _sizes(_shown_view(qtbot, entries, width=900))
    wide = _sizes(_shown_view(qtbot, entries, width=1400))

    assert wide[1] > narrow[1], "the transcript column did not take the slack"
    assert wide[0] == narrow[0]
    assert wide[2:] == narrow[2:]


def test_last_column_does_not_stretch(qtbot):
    """``setStretchLastSection`` defaults to on, which would out-rank the
    fitted width of Duration whenever the window got wide."""
    entries = _make_entries(8)
    view = _shown_view(qtbot, entries, width=1400)
    sizes = _sizes(view)

    header = _header(view)
    total_fixed = sum(
        header.sectionSize(i) for i in range(header.count() - 1)
    )
    assert total_fixed + header.count() - 1 <= _table(view).width()


def test_no_column_is_left_to_measure_itself(qtbot):
    """``ResizeToContents`` re-measures on every section-size change, so
    a window drag re-scanned the whole history: 296ms per step at 1000
    entries, measured. The widths are ours to apply now.
    """
    from PySide6.QtWidgets import QHeaderView

    from app.gui.views.history_view import _FITTED_COLUMNS

    view = _shown_view(qtbot, _make_entries(6))
    header = _header(view)

    for col in _FITTED_COLUMNS:
        assert header.sectionResizeMode(col) != QHeaderView.ResizeToContents
    assert header.sectionResizeMode(1) == QHeaderView.Stretch


def test_window_drag_over_a_long_history_stays_responsive(qtbot):
    """The cost guard behind the mode test above, measured rather than
    asserted. 1000 entries is the app's own cap on history.

    Budget: 10 resize steps in under 700ms. The measurement came out at
    ~90ms; the ``ResizeToContents`` version it replaced took ~3s, so
    neither side of the line is a close call.
    """
    import time

    entries = _make_entries(1000)
    view = _shown_view(qtbot, entries, width=900)

    started = time.perf_counter()
    for width in range(900, 1110, 21):
        view.resize(width, 620)
        qtbot.wait(1)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms < 700, f"10 resize steps took {elapsed_ms:.0f}ms"


def test_prepending_a_wider_entry_widens_its_column(qtbot):
    """The hot path has to keep the fit honest, not just the initial load.

    Wide enough that the columns are not already at the point where they
    start yielding — that behaviour is
    ``test_columns_yield_before_the_table_scrolls``.
    """
    entries = _make_entries(6)
    view = _shown_view(qtbot, entries, width=1400)
    before = _sizes(view)

    fresh = FakeEntry(
        timestamp=99.0,
        text="a fresh dictation",
        duration=1.0,
        model="parakeet-tdt-0.6b-v3-en-longer-canonical-alias",
        language="yue-Hant-HK",
    )
    view.prepend_entry(fresh)
    after = _sizes(view)

    assert after[2] > before[2], "the Model column did not grow for a longer id"
    assert after[3] > before[3], "the Language column did not grow"
    assert _worst_fit(view) == []


def test_searching_does_not_move_the_columns(qtbot):
    """Widths are fitted against every entry, not the visible ones, so
    the columns do not jump while the user types."""
    entries = _make_entries(20)
    view = _shown_view(qtbot, entries)
    before = _sizes(view)

    view.findChild(QLineEdit, "HistorySearchEdit").setText("entry 1")
    qtbot.wait(220)  # the search box debounces

    assert _sizes(view) == before


def test_model_column_shows_the_alias_not_the_canonical_id(qtbot):
    """Pins the formatting the widths are measured against: the column is
    sized for the short alias, so a cell that printed the full canonical
    id would overflow the fit that was computed for it.
    """
    from app.model_mapping import alias_for
    from app.gui.views.history_view import HistoryTableModel

    entry = FakeEntry(
        timestamp=0.0,
        text="text",
        duration=1.5,
        model="istupakov/gigaam-v3-onnx",
        language="ru",
    )
    model = HistoryTableModel([entry])

    assert model.data(model.index(0, 2), Qt.DisplayRole) == "gigaam-v3-ctc"
    assert model.data(model.index(0, 2), Qt.DisplayRole) == alias_for(entry.model)
    assert model.data(model.index(0, 0), Qt.DisplayRole) == entry.datetime_str
    assert model.data(model.index(0, 4), Qt.DisplayRole) == "1.5s"


def test_no_cell_is_elided_under_the_real_theme(qtbot):
    """The width of a cell is its text plus the item delegate's margin,
    and the margin is not a number this code gets to choose: 8px on a
    default-styled view, 11–12px under this app's theme, moving with the
    font.

    A guessed 8 left the timestamp four pixels short and the History
    screen rendered "18:13:55 …" — which is how it reached the README
    screenshot, having passed every other assertion in this file. The
    columns now ask the delegate, and this walks the rows checking the
    result against the delegate's own margin rather than a constant.
    """
    from app.gui.theme import apply_text_scale
    from PySide6.QtWidgets import QStyleOptionViewItem

    entries = [
        FakeEntry(
            timestamp=float(i),
            text=f"entry text {i}",
            duration=float(i) / 3,
            # Mixed on purpose: the shortest and the longest alias in the
            # registry, and an empty language.
            model=("gigaam-v3-ctc", "whisper-large-v3-turbo")[i % 2],
            language=("ru", "", "en", "yue-Hant-HK")[i % 4],
        )
        for i in range(24)
    ]
    view = _shown_view(qtbot, entries, width=1400)
    app = QApplication.instance()
    table = _table(view)
    header = _header(view)
    delegate = table.itemDelegate()

    # The invariant: no cell in the column needs more room than the
    # column has. "Needs" is the delegate's own answer for that cell,
    # which is the number Qt paints against — the same source the view
    # now measures from, checked here against every row rather than the
    # one that happened to be widest.
    option = QStyleOptionViewItem()
    option.initFrom(table)
    option.font = table.font()

    for scale in (1.0, 1.75):
        try:
            apply_text_scale(app, scale)
            qtbot.wait(20)
            for row in range(len(entries)):
                for col, name in _columns():
                    if not view._source_model.cell_text(row, col):
                        continue
                    index = view._source_model.index(row, col)
                    needed = delegate.sizeHint(option, index).width()
                    section = header.sectionSize(col)
                    # One pixel of slack on top of the delegate's minimum:
                    # cells in the same column ask for a pixel or two more
                    # than the widest one did, and a column sized exactly
                    # at the minimum has no room for that.
                    assert section >= needed + 1, (
                        f"{name} row {row} needs {needed}px and the column "
                        f"is {section}px, at text scale {scale}"
                    )
        finally:
            apply_text_scale(app, 1.0)
            qtbot.wait(20)


def test_the_delegate_option_carries_the_tables_font(qtbot):
    """The delegate reads the font off the style option, not off the
    widget.

    ``initFrom`` leaves ``option.font`` at a value the delegate
    disagrees with — it measured a 211px timestamp as 126px, and the
    column was sized from that, which is how "18:13:55 …" reached the
    README screenshot. The columns cannot catch this on their own: the
    two fonts only disagree in the window between a stylesheet being
    re-resolved and the paint that follows, and no test drives that.
    """
    view = _shown_view(qtbot, _make_entries(4))
    table = _table(view)
    option = view._delegate_option()

    assert option.font == table.font()
