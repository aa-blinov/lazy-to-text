"""Tests for the HistoryView and its backing table model."""

from dataclasses import dataclass

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QTableView

from app.gui.widgets.empty_state import format_hotkey


@dataclass
class FakeEntry:
    timestamp: float
    text: str
    duration: float
    model: str
    language: str

    @property
    def datetime_str(self) -> str:
        return "00:00:00 01.01.2026"

    @property
    def short_text(self) -> str:
        return self.text[:50]


def _make_entries(n: int = 3):
    return [
        FakeEntry(
            timestamp=float(i),
            text=f"entry text {i}",
            duration=float(i + 1),
            model="whisper-large-v3",
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
    from app.gui.views.history_view import HistoryView

    view = HistoryView()
    qtbot.addWidget(view)
    view.show()
    view.set_entries(_make_entries(3))

    emissions: list[str] = []
    view.copy_requested.connect(emissions.append)

    btn = view.findChild(QPushButton, "CopyEntryButton")
    qtbot.mouseClick(btn, Qt.LeftButton)

    assert emissions == []


def test_history_model_exposes_full_text_via_tooltip(qtbot):
    """Long transcripts are ellipsised in the table, so the tooltip
    must carry the full text — quick hover-peek without opening the
    detail dialog."""
    from app.gui.views.history_view import HistoryTableModel

    long_text = "a long transcription that overflows the column width " * 4
    entry = FakeEntry(
        timestamp=0.0, text=long_text, duration=1.0,
        model="whisper-large-v3", language="ru",
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
        model="whisper-large-v3",
        language="ru",
    )
    dialog = HistoryDetailDialog(entry)
    qtbot.addWidget(dialog)
    assert dialog._text.toPlainText() == entry.text
    rendered = " ".join(
        lbl.text() for lbl in dialog.findChildren(QLabel)
    )
    assert "whisper-large-v3" in rendered
    assert "ru" in rendered
    assert "12.5" in rendered


def test_history_detail_dialog_copy_button_copies_text(qtbot):
    """The dialog's Copy button must put the full text on the
    clipboard so the user can paste it elsewhere."""
    from PySide6.QtWidgets import QApplication
    from app.gui.views.history_view import HistoryDetailDialog

    entry = FakeEntry(
        timestamp=0.0, text="transcribed words", duration=1.0,
        model="whisper-large-v3", language="ru",
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
    (``onnx-community/whisper-large-v3``) — it's what the user
    actually picked, and short enough not to truncate."""
    from app.gui.views.history_view import HistoryTableModel

    entry = FakeEntry(
        timestamp=0.0,
        text="x",
        duration=1.0,
        model="onnx-community/whisper-large-v3",
        language="ru",
    )
    model = HistoryTableModel([entry])
    cell = model.data(model.index(0, 2), Qt.DisplayRole)
    assert cell == "whisper-large-v3"


def test_history_model_column_tooltip_shows_full_canonical(qtbot):
    """Hovering still reveals the full canonical id for power users
    who want to know exactly which Hugging Face repo was used."""
    from app.gui.views.history_view import HistoryTableModel

    entry = FakeEntry(
        timestamp=0.0,
        text="x",
        duration=1.0,
        model="onnx-community/whisper-large-v3",
        language="ru",
    )
    model = HistoryTableModel([entry])
    tooltip = model.data(model.index(0, 2), Qt.ToolTipRole)
    assert tooltip == "onnx-community/whisper-large-v3"


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
    from PySide6.QtGui import QKeyEvent

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
