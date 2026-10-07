"""Tests for the LogsView widget."""

from PySide6.QtWidgets import QCheckBox, QPlainTextEdit, QPushButton


def _text(view) -> str:
    return view.findChild(QPlainTextEdit).toPlainText()


def test_logs_view_starts_empty(qtbot):
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    assert _text(view) == ""


def test_logs_view_textbox_is_read_only(qtbot):
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    textbox = view.findChild(QPlainTextEdit)
    assert textbox.isReadOnly()


def test_logs_view_wraps_long_lines(qtbot):
    """Long log lines should wrap to widget width, not push a horizontal scrollbar."""
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    textbox = view.findChild(QPlainTextEdit)
    assert textbox.lineWrapMode() == QPlainTextEdit.WidgetWidth


def test_records_arrive_in_order(qtbot):
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    for index, word in enumerate(("one", "two", "three")):
        view.append_record(f"12:00:0{index}", "INFO", "app.state_manager", word)
    content = _text(view)
    assert "one" in content and "two" in content and "three" in content
    assert content.index("one") < content.index("two") < content.index("three")


def test_append_record_renders_message_text(qtbot):
    """Structured records still surface their message text in the
    plain-text view (so ``toPlainText`` can be searched / copied)."""
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    view.append_record("12:00:01", "INFO", "app.state_manager", "switching model")
    content = _text(view)
    assert "switching model" in content
    assert "INFO" in content
    assert "app.state_manager" in content


def test_append_record_emits_inline_color_for_levels(qtbot):
    """Each record renders inline-styled HTML with a level-specific
    colour so the eye can pick errors out of a busy stream."""
    from app.gui.theme import TOKENS
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    view.append_record("12:00:01", "ERROR", "app.state_manager", "boom")

    textbox = view.findChild(QPlainTextEdit)
    html = textbox.document().toHtml()
    assert "[ERROR]" in html
    # Asserted against the token, not a literal hex. This test used to
    # hardcode #fca5a5 and broke on the Gruvbox switch without telling
    # anyone the log's red had changed — a test that pins a palette
    # value measures the palette, not the behaviour.
    assert TOKENS.colors["danger"] in html.lower()


def test_log_level_ink_clears_aa_on_the_console():
    """Every level colour has to be readable on the pane it renders on.

    The log console sits on bg_primary, and that is not a styling
    preference: Gruvbox's brightest red measures 4.29:1 on bg_secondary
    and 3.82:1 on bg_elevated, so any lighter console drops the error
    level under AA. If the console is ever moved up the ladder, this
    fails instead of quietly shipping unreadable errors.

    DEBUG is the one exemption, and it is the app-wide muted debt rather
    than a local choice — DEBUG shares text_muted with timestamps and
    third-party module names. It is measured rather than waved through,
    so a palette that makes it worse is still visible.
    """
    from app.gui.theme import TOKENS

    colors = TOKENS.colors
    must_clear_aa = {
        "INFO": colors["accent"],
        "WARNING": colors["warning"],
        "ERROR": colors["danger"],
        "CRITICAL": colors["danger"],
    }
    for level, color in must_clear_aa.items():
        ratio = _contrast(color, colors["bg_primary"])
        assert ratio >= 4.5, f"{level} ink {ratio:.2f}:1 on the log console"

    debug_ratio = _contrast(colors["text_muted"], colors["bg_primary"])
    assert debug_ratio >= 4.0, f"DEBUG ink degraded to {debug_ratio:.2f}:1"


def _contrast(a: str, b: str) -> float:
    """WCAG 2.1 relative-luminance contrast between two hex strings."""
    def channel(value: int) -> float:
        v = value / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    def luminance(hex_color: str) -> float:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_append_record_skips_network_loggers_by_default(qtbot):
    """``httpx`` floods the view with HTTP debug noise during model
    loads; hide it unless the user opts in via the toggle."""
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    view.append_record("12:00:01", "INFO", "httpx", "GET /foo 200")
    view.append_record("12:00:02", "INFO", "app.state_manager", "important")

    content = _text(view)
    assert "GET /foo" not in content
    assert "important" in content


def test_append_record_shows_network_when_toggle_on(qtbot):
    """Flipping the 'Show network logs' checkbox should let httpx
    records through."""
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    toggle = next(
        b for b in view.findChildren(QCheckBox) if b.objectName() == "ShowNetworkLogs"
    )
    toggle.setChecked(True)

    view.append_record("12:00:01", "INFO", "httpx", "GET /foo 200")
    assert "GET /foo" in _text(view)


def test_append_record_respects_buffer_cap(qtbot):
    """When the cap is reached, the oldest records should fall off.

    The words are spelled out rather than single letters because every
    rendered line carries the logger name — ``app.state_manager``
    contains an "a", and a one-letter marker would never be absent from
    the text it is searched in.
    """
    from app.gui.views.logs_view import LogsView

    view = LogsView(max_lines=3)
    qtbot.addWidget(view)
    for index, word in enumerate(("alpha", "bravo", "charlie", "delta")):
        view.append_record(f"12:00:0{index}", "INFO", "app.state_manager", word)

    content = _text(view)
    assert "alpha" not in content
    assert "bravo" in content and "charlie" in content and "delta" in content


def test_logs_view_has_search_field(qtbot):
    from PySide6.QtWidgets import QLineEdit
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    assert view.findChild(QLineEdit, "LogsSearchEdit") is not None


def test_logs_search_filters_buffered_records(qtbot):
    """Typing in the search field hides records that don't match;
    re-rendering uses the in-memory ring buffer so previously-shown
    entries can come back instantly when the filter clears."""
    from PySide6.QtWidgets import QLineEdit, QPlainTextEdit
    from app.gui.views.logs_view import LogsView

    # search_debounce_ms=0 so the timer fires on the next event-loop tick
    view = LogsView(search_debounce_ms=0)
    qtbot.addWidget(view)
    view.append_record("12:00:00", "INFO", "app.state_manager", "model loaded")
    view.append_record("12:00:01", "WARNING", "app.audio_recorder", "low gain")
    view.append_record("12:00:02", "INFO", "app.state_manager", "transcribed")

    text = view.findChild(QPlainTextEdit, "LogsTextArea").toPlainText()
    assert "model loaded" in text
    assert "low gain" in text

    search = view.findChild(QLineEdit, "LogsSearchEdit")
    search.setText("low")
    qtbot.wait(50)  # allow debounce timer to fire

    after = view.findChild(QPlainTextEdit, "LogsTextArea").toPlainText()
    assert "low gain" in after
    assert "model loaded" not in after
    assert "transcribed" not in after

    search.setText("")
    qtbot.wait(50)
    restored = view.findChild(QPlainTextEdit, "LogsTextArea").toPlainText()
    assert "model loaded" in restored
    assert "transcribed" in restored


def test_logs_search_matches_logger_name(qtbot):
    from PySide6.QtWidgets import QLineEdit, QPlainTextEdit
    from app.gui.views.logs_view import LogsView

    view = LogsView(search_debounce_ms=0)
    qtbot.addWidget(view)
    view.append_record("12:00:00", "INFO", "app.state_manager", "alpha")
    view.append_record("12:00:01", "INFO", "app.audio_recorder", "beta")

    search = view.findChild(QLineEdit, "LogsSearchEdit")
    search.setText("audio")
    qtbot.wait(50)
    text = view.findChild(QPlainTextEdit, "LogsTextArea").toPlainText()
    assert "beta" in text
    assert "alpha" not in text


# ---- Debounce ---------------------------------------------------------------


def test_logs_search_debounce_does_not_rerender_immediately(qtbot):
    """After typing, the textbox must NOT be filtered until the debounce
    timer fires.  Every keystroke rebuilding 5 000 HTML lines is the
    bug we're fixing."""
    from app.gui.views.logs_view import LogsView

    DEBOUNCE_MS = 120
    view = LogsView(search_debounce_ms=DEBOUNCE_MS)
    qtbot.addWidget(view)

    view.append_record("12:00:00", "INFO", "app.state_manager", "hello world")
    view.append_record("12:00:01", "INFO", "app.state_manager", "other line")

    # Simulate keystroke — timer is now armed but hasn't fired yet.
    view._on_search_changed("hello")

    # Immediately after: both records must still be visible (no rerender yet).
    assert "other line" in view._text.toPlainText(), (
        "_rerender must not fire synchronously on each keystroke"
    )

    # After the debounce window: only the matching record should survive.
    qtbot.wait(DEBOUNCE_MS + 60)
    assert "other line" not in view._text.toPlainText()
    assert "hello world" in view._text.toPlainText()


def test_logs_search_debounce_rapid_keystrokes_single_rerender(qtbot):
    """Five rapid keystrokes must produce exactly one rerender, not five.

    We verify this by checking that the textbox stays unfiltered right up
    until the debounce window, then filters correctly in one shot.
    """
    from app.gui.views.logs_view import LogsView

    DEBOUNCE_MS = 120
    view = LogsView(search_debounce_ms=DEBOUNCE_MS)
    qtbot.addWidget(view)

    for i in range(20):
        view.append_record("12:00:00", "INFO", "app.x", f"msg {i}")

    # Simulate rapid typing — each call restarts the timer.
    for prefix in ("e", "er", "err", "erro", "error"):
        view._on_search_changed(prefix)

    # Still unfiltered (timer keeps being restarted, hasn't fired).
    assert view._text.toPlainText() != "", (
        "Rapid keystrokes must not rerender until the debounce fires"
    )

    # Wait for the debounce to settle.
    qtbot.wait(DEBOUNCE_MS + 60)
    # "error" query matches nothing in "msg N" → textbox should be empty.
    assert view._text.toPlainText().strip() == ""


def test_logs_search_debounce_timer_is_single_shot(qtbot):
    """The debounce QTimer must be single-shot so it doesn't keep
    re-rendering the log on a fixed interval after the user stops typing."""
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    assert view._search_timer.isSingleShot()


def test_logs_clear_drops_buffered_records(qtbot):
    """Clear should wipe both the visible textbox AND the buffer
    feeding the filter — otherwise a stale search re-rendered from
    the buffer would resurrect the cleared entries."""
    from PySide6.QtWidgets import QPlainTextEdit
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    view.append_record("12:00:00", "INFO", "app.state_manager", "alpha")
    view.clear()
    # Re-trigger render via toggle — anything buffered would appear.
    view._on_toggle_network(True)
    text = view.findChild(QPlainTextEdit, "LogsTextArea").toPlainText()
    assert "alpha" not in text


def test_rerender_preserves_all_visible_records(qtbot):
    """_rerender must show every record that passes the current filter —
    the batched implementation (setUpdatesEnabled + beginEditBlock) must
    not drop or duplicate entries compared to the naive loop."""
    from PySide6.QtWidgets import QPlainTextEdit
    from app.gui.views.logs_view import LogsView

    view = LogsView(search_debounce_ms=0)
    qtbot.addWidget(view)

    messages = [f"msg-{i}" for i in range(20)]
    for i, msg in enumerate(messages):
        view.append_record(f"12:00:{i:02d}", "INFO", "app.state_manager", msg)

    # Force a full _rerender via the network toggle.
    view._on_toggle_network(True)
    view._on_toggle_network(False)

    text = view.findChild(QPlainTextEdit, "LogsTextArea").toPlainText()
    for msg in messages:
        assert msg in text, f"record '{msg}' missing after _rerender"


def test_rerender_respects_search_filter(qtbot):
    """Records that do not match the search query must be absent after
    _rerender — batched mode must apply the same _record_visible logic."""
    from PySide6.QtWidgets import QPlainTextEdit
    from app.gui.views.logs_view import LogsView

    view = LogsView(search_debounce_ms=0)
    qtbot.addWidget(view)

    view.append_record("12:00:00", "INFO", "app.state_manager", "apple")
    view.append_record("12:00:01", "INFO", "app.state_manager", "banana")
    view.append_record("12:00:02", "INFO", "app.state_manager", "cherry")

    # Simulate debounced search: set query and call _apply_search directly.
    view._search_query = "banana"
    view._rerender()

    text = view.findChild(QPlainTextEdit, "LogsTextArea").toPlainText()
    assert "banana" in text
    assert "apple" not in text
    assert "cherry" not in text


# ---- the three "Clear" buttons ---------------------------------------------
#
# The app had three buttons labelled "Clear" and meant three different
# things: this one empties the log buffer, History's deletes the on-disk
# history, Settings' discards a stored credential. Two of the three are
# irreversible, and the label is the only thing a user has before the
# click.


def test_clear_labels_name_what_they_destroy(qtbot):
    """One word cannot cover three objects, two of them irreversible."""
    from app.gui.views.history_view import HistoryView
    from app.gui.views.logs_view import LogsView
    from app.gui.views.shortcuts_view import ShortcutsView

    # Keep the views alive: a temporary parent collects its children and
    # the buttons come back as deleted C++ objects.
    logs_view, history_view, shortcuts_view = (
        LogsView(), HistoryView(), ShortcutsView()
    )
    for v in (logs_view, history_view, shortcuts_view):
        qtbot.addWidget(v)
    logs = next(
        b for b in logs_view.findChildren(QPushButton)
        if b.objectName() == "ClearLogsButton"
    )
    history = next(
        b for b in history_view.findChildren(QPushButton)
        if b.objectName() == "ClearHistoryButton"
    )
    token = next(
        b for b in shortcuts_view.findChildren(QPushButton)
        if b.objectName() == "ClearHfTokenButton"
    )
    labels = {logs.text(), history.text(), token.text()}
    assert len(labels) == 3, f"the three Clear buttons share a label: {labels}"
    for btn in (logs, history, token):
        assert btn.text() != "Clear", btn.objectName()
        assert len(btn.text()) > len("Clear"), btn.objectName()


def test_clear_logs_asks_before_discarding(qtbot, monkeypatch):
    """The old answer to "this is destructive" was red paint.

    Colour is not something to carry a warning by — it vanishes in a
    screenshot, in a forced-colours theme, and for anyone who cannot
    see it. The History view's Clear already confirms; this one did
    not, and it sits one click from the search box.
    """
    from app.gui.views import logs_view as module
    from app.gui.views.logs_view import LogsView

    asked = {}

    def _confirm(parent, title, text, **kw):
        asked["title"] = title
        asked["text"] = text
        asked.update(kw)
        return True

    monkeypatch.setattr(module, "confirm", _confirm)

    view = LogsView()
    qtbot.addWidget(view)
    view.append_record("2026-10-04 12:00:00", "INFO", "app.x", "hello")
    btn = next(
        b for b in view.findChildren(QPushButton)
        if b.objectName() == "ClearLogsButton"
    )
    btn.click()

    assert asked, "clearing the log buffer must ask first"
    assert "Clear logs?" == asked["title"]
    # Both buttons name the outcome, so the choice does not depend on
    # reading the title twice.
    assert asked["yes_label"] == "Clear logs"
    assert asked["cancel_label"] == "Keep logs"
    assert "1" in asked["text"]
    assert _text(view) == ""


def test_cancelling_clear_logs_keeps_the_buffer(qtbot, monkeypatch):
    from app.gui.views import logs_view as module
    from app.gui.views.logs_view import LogsView

    monkeypatch.setattr(module, "confirm", lambda *a, **kw: False)

    view = LogsView()
    qtbot.addWidget(view)
    view.append_record("2026-10-04 12:00:00", "INFO", "app.x", "hello")
    btn = next(
        b for b in view.findChildren(QPushButton)
        if b.objectName() == "ClearLogsButton"
    )
    btn.click()

    assert _text(view) != "", "cancelling must leave the log alone"
    assert len(view._records) == 1


def test_clear_logs_is_reachable_even_when_a_search_hid_everything(qtbot, monkeypatch):
    """A filtered-to-empty stream is still a full buffer, and still
    deserves a way out — the confirmation counts what is buffered."""
    from app.gui.views import logs_view as module
    from app.gui.views.logs_view import LogsView

    asked = {}
    monkeypatch.setattr(
        module, "confirm",
        lambda p, t, x, **kw: asked.update(title=t, text=x) or True,
    )

    # search_debounce_ms=0 so the filter lands on the next event-loop
    # tick, the same way the existing search tests do it.
    view = LogsView(search_debounce_ms=0)
    qtbot.addWidget(view)
    view.append_record("2026-10-04 12:00:00", "INFO", "app.x", "hello")
    view._search_edit.setText("absent")
    qtbot.wait(50)
    assert _text(view) == "", "precondition: the filter hid everything"

    btn = next(
        b for b in view.findChildren(QPushButton)
        if b.objectName() == "ClearLogsButton"
    )
    btn.click()

    assert asked, "the filter must not make the buffer unclearable"
    assert "1" in asked["text"]
    assert len(view._records) == 0


def test_everything_on_screen_came_from_the_buffer(qtbot):
    """The Clear button can read the buffer alone, because nothing else
    writes to the document.

    This is the invariant the old ``append_line`` path broke: it painted
    a line without recording it, so the guard had to read the document
    back as well — and the count in the confirmation dialog, which
    reports ``len(self._records)``, could disagree with what was on
    screen. A second way in would show up here.
    """
    from PySide6.QtWidgets import QPlainTextEdit
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    text_box = view.findChild(QPlainTextEdit, "LogsTextArea")
    # characterCount, not blockCount: a QTextDocument always has one
    # block, even empty, so a block count is true for an empty view.
    assert text_box.document().characterCount() == 1
    assert view._has_anything_to_clear() is False

    view.append_record("12:00:00", "INFO", "app.state_manager", "alpha")
    assert text_box.document().characterCount() > 1
    assert view._has_anything_to_clear() is True

    view.clear()
    assert text_box.document().characterCount() == 1
    assert view._has_anything_to_clear() is False


def test_a_filtered_out_record_still_counts_as_something_to_clear(qtbot):
    """The network logger is hidden by default, so its records reach the
    buffer without ever reaching the screen. They are still logs, and
    they are still clearable — which is the case a buffer-only guard
    covers and a screen-only one would miss.
    """
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    view.append_record("12:00:00", "INFO", "httpx", "GET https://example.com")

    assert view._records, "precondition: the record was buffered"
    assert view._has_anything_to_clear() is True


def test_the_view_has_exactly_one_way_in(qtbot):
    """No second method that paints a line without recording it.

    Source-level on purpose. Every behaviour test above passes with such
    a method sitting there unused, because nothing calls it — and the
    one caller that did (the screenshot generator) is what kept it
    alive through a cleanup. The failure mode it caused was not a crash
    but a lie: the Clear button counting fewer lines than the screen
    showed.
    """
    from pathlib import Path

    from app.gui.views import logs_view as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "def append_line" not in source, "a second way in is back"

    # Nothing reaches the document except a formatted record. Two
    # writers is right — one appends as records arrive, one replays the
    # buffer when a filter changes — and both must go through the same
    # formatter, or the replay draws something the buffer never held.
    assert "appendPlainText" not in source, "something else is painting lines"
    writers = [line.strip() for line in source.splitlines()
               if "self._text.append" in line]
    assert writers, "precondition: records are painted into the document"
    assert all("_format_record_html(" in line for line in writers), writers


# ---- which lines were addressed to the user --------------------------------


def _message_color_for(level, user_message):
    from app.gui.views.logs_view import _message_color

    return _message_color(level, user_message)


def test_a_line_the_app_spoke_is_rendered_at_full_brightness():
    """The whole mechanism is the ``user_message`` flag the recording
    stack has been setting all along. It was being dropped one frame
    upstream, so "Delivery sent" and "Clipboard access test successful"
    rendered identically."""
    from app.gui.views.logs_view import _COLOR_MESSAGE

    assert _message_color_for("INFO", True) == _COLOR_MESSAGE


def test_an_untagged_info_line_recedes():
    """Internal bookkeeping is genuinely less important than the one
    line the user needs. Both used to be full brightness, so finding the
    answer meant reading every line in between."""
    from app.gui.views.logs_view import _COLOR_MESSAGE, _COLOR_MESSAGE_MUTED

    assert _message_color_for("INFO", False) == _COLOR_MESSAGE_MUTED
    assert _message_color_for("DEBUG", False) == _COLOR_MESSAGE_MUTED
    assert _message_color_for("INFO", True) != _COLOR_MESSAGE_MUTED


def test_a_problem_is_never_muted_even_when_untagged():
    """Brightness answers "was this for you" — an error is for you
    whether or not it was tagged."""
    from app.gui.views.logs_view import _COLOR_MESSAGE

    for level in ("WARNING", "ERROR", "CRITICAL"):
        assert _message_color_for(level, False) == _COLOR_MESSAGE


def test_the_tag_survives_into_the_rendered_html(qtbot):
    """End to end through the view's own writer, so this fails if the
    fifth argument is dropped anywhere between the signal and the
    document rather than only if the helper regresses."""
    from app.gui.views.logs_view import (
        LogsView,
        _COLOR_MESSAGE,
        _COLOR_MESSAGE_MUTED,
    )

    view = LogsView()
    qtbot.addWidget(view)

    view.append_record("12:00:00", "INFO", "app.state_manager", "spoken", True)
    view.append_record("12:00:01", "INFO", "app.clipboard", "bookkeeping")

    html = view._text.document().toHtml()
    spoken_at = html.index("spoken")
    bookkeeping_at = html.index("bookkeeping")
    assert _COLOR_MESSAGE in html[spoken_at - 400:spoken_at + 400], (
        "the line addressed to the user was rendered muted"
    )
    assert _COLOR_MESSAGE_MUTED in html[
        bookkeeping_at - 400:bookkeeping_at + 400
    ], "internal bookkeeping was rendered at full brightness"


def test_the_buffer_remembers_the_tag_across_a_rerender(qtbot):
    """A search replays the buffer rather than the document. If the tag
    were not buffered with the line, every re-render would flatten the
    whole view back to one weight."""
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)

    view.append_record("12:00:00", "INFO", "app.state_manager", "spoken", True)
    assert any(record[-1] for record in view._records), view._records

    view._search_edit.setText("spoken")
    view._rerender()

    assert view._records[0][-1] is True
    assert "spoken" in _text(view)


def test_the_older_four_argument_call_still_works(qtbot):
    """The screenshot generator is a real caller and passes four
    arguments; it must keep rendering rather than raising."""
    from app.gui.views.logs_view import LogsView, _COLOR_MESSAGE_MUTED

    view = LogsView()
    qtbot.addWidget(view)

    view.append_record("12:00:00", "INFO", "app.x", "no tag")

    assert view._records[0][-1] is False
    assert "no tag" in _text(view)
    assert _COLOR_MESSAGE_MUTED in view._text.document().toHtml()


def test_search_still_matches_the_message_of_an_untagged_line(qtbot):
    from app.gui.views.logs_view import LogsView

    view = LogsView()
    qtbot.addWidget(view)
    view.append_record("12:00:00", "INFO", "app.x", "hidden gem")

    view._search_edit.setText("hidden gem")

    assert "hidden gem" in _text(view)
