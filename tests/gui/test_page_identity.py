"""Every view has a name, one primary action, and the same left edge.

Three properties, all of which were false or unchecked before this:

- **Identity.** No real view set ``role="title"``; only ``placeholder.py``,
  the screen the app never shows. The token and the QSS rule existed and
  nothing used them, so four of five sections had no name on screen.
- **One primary action per view.** Nothing enforced "the accent-filled
  button is the one the user is meant to press", so Transcribe offered
  Browse / Copy / Save at identical weight and History put Clear next to
  Copy in the same grey.
- **The same left edge.** ``TranscribeView`` used 24px margins against
  the documented 28, so its content sat 4px left of every other view's.
  The rule was written down and not enforced, which is how it drifted.

The alignment check walks to the header rather than reading the layout
margins, because Settings nests its header in a wrapper — the property
that matters is where the content *lands*, not which layout holds it.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.gui.widgets.page_header import PageHeader


_VIEW_KEYS = ("models", "transcribe", "history", "logs", "shortcuts")

# The documented content frame, DESIGN.md "Fixed Spine Rule". Anything
# else and the sidebar's hard left edge stops being a line the eye can
# follow down the app.
_CONTENT_LEFT_PX = 28


@pytest.fixture
def window(qtbot):
    from app.gui.main_window import MainWindow
    from app.gui.theme import apply_theme

    app = QApplication.instance()
    apply_theme(app)
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1100, 780)
    win.show()
    win.activateWindow()
    # Offscreen Qt only lays out and grants focus to an *active* window,
    # and it only becomes active once its children exist.
    QApplication.processEvents()
    yield win


def _views(window):
    """Every real view, in tab order."""
    return [(key, window.get_view(key)) for key in _VIEW_KEYS]


# --- identity -----------------------------------------------------------


def test_every_view_has_a_page_header(window):
    missing = [key for key, view in _views(window) if not view.findChild(PageHeader)]
    assert missing == [], f"views with no page header: {missing}"


def test_every_header_names_its_section(window):
    """A header with an empty title is worse than none: it reserves the
    space and then says nothing."""
    for key, view in _views(window):
        header = view.findChild(PageHeader)
        assert header.title_label.text().strip(), f"{key}: empty title"
        assert header.subtitle_label.text().strip(), (
            f"{key}: no purpose line — the title alone does not say what "
            f"the section is for"
        )


def test_titles_are_the_section_names(window):
    """Spelled out rather than derived, because the whole point is that
    the header says the same thing the sidebar says."""
    expected = {
        "models": "Models",
        "transcribe": "Transcribe",
        "history": "History",
        "logs": "Logs",
        "shortcuts": "Settings",
    }
    for key, view in _views(window):
        header = view.findChild(PageHeader)
        assert header.title_label.text() == expected[key], key


def _first_content_widget(view):
    """The first widget in the view's root layout, unwrapping containers
    that hold nothing else.

    Settings nests its header in a wrapper so the description can sit
    above a scroll area; the wrapper is layout scaffolding, not content,
    and treating it as the first thing on screen would make the test
    assert the scaffolding rather than the design.
    """
    layout = view.layout()
    widgets = [
        layout.itemAt(i).widget()
        for i in range(layout.count())
        if layout.itemAt(i).widget() is not None
    ]
    if not widgets:
        return None
    first = widgets[0]
    if isinstance(first, PageHeader):
        return first
    children = [
        first.layout().itemAt(i).widget()
        for i in range(first.layout().count())
        if first.layout().itemAt(i).widget() is not None
    ] if first.layout() is not None else []
    if len(children) == 1 and isinstance(children[0], PageHeader):
        return children[0]
    return first


def test_the_header_is_the_first_thing_in_the_view(window):
    """A header below the toolbar reads as a caption for the toolbar."""
    for key, view in _views(window):
        first = _first_content_widget(view)
        assert first is not None, f"{key}: empty root layout"
        assert isinstance(first, PageHeader), (
            f"{key}: first thing on screen is {first.__class__.__name__}, "
            f"not a PageHeader"
        )


# --- one primary action -------------------------------------------------


def _primary_chrome_buttons(view) -> list:
    """Primary buttons that are actually on screen, outside card chrome.

    ``isHidden()`` and not ``isVisible()``: a widget whose *ancestor* is
    hidden is not visible either, and the window fixture leaves every
    view but the current one that way. Filtering on ``isVisible()``
    would count zero buttons here and turn the test below into a
    tautology. ``isHidden()`` answers the question this rule is really
    about — was this control deliberately taken off screen?
    """
    from PySide6.QtWidgets import QPushButton

    from app.gui.widgets.model_card import ModelCard

    def inside_a_card(button) -> bool:
        node = button.parentWidget()
        while node is not None:
            if isinstance(node, ModelCard):
                return True
            node = node.parentWidget()
        return False

    return [
        b
        for b in view.findChildren(QPushButton)
        if b.property("role") == "primary"
        and not inside_a_card(b)
        and not b.isHidden()
    ]


def test_at_most_one_primary_button_per_view(window):
    """More than one accent-filled button and neither is primary.

    Scoped to the view's own chrome. Models is exempt by design: it is a
    list of cards, and each card's Download/Select is the primary action
    *of that card*, which is the same rule one level down rather than a
    violation of it.

    Off-screen buttons are out of scope, and that is not a loosening: a
    control nobody can see cannot compete for the eye. The failure this
    guards against is two *visible* accents, not two `role="primary"`
    properties. Transcribe is the reason the distinction matters — which
    button is primary there is a function of state (Browse until there
    is a transcript, Copy once there is), so the view holds both
    properties at once and swaps them.
    """
    for key, view in _views(window):
        chrome = _primary_chrome_buttons(view)
        assert len(chrome) <= 1, (
            f"{key}: {len(chrome)} primary buttons in the view's own chrome — "
            f"{[b.text() for b in chrome]}"
        )
    # Guard the guard: if the helper ever stopped finding anything the
    # loop above would pass on every view and mean nothing.
    assert _primary_chrome_buttons(window.get_view("transcribe")), (
        "no primary button found in Transcribe — the scan is not looking "
        "at the right thing and the assertions above are vacuous"
    )


def test_the_primary_button_is_swapped_not_duplicated(window, tmp_path):
    """The state-dependent half of the rule above, checked where two
    primaries could actually collide.

    Without a result there is nothing to take away, so Copy does not
    exist yet and Browse is the accent. With one, Copy is the accent and
    Browse steps down. If both ever came back at once the first test
    would not see it — it only ever runs the empty state.
    """
    from app.gui.views.transcribe_view import TranscribeView

    view = window.get_view("transcribe")
    assert isinstance(view, TranscribeView)

    assert view._copy_btn.isHidden()
    assert view._browse_btn.property("role") == "primary"
    assert len(_primary_chrome_buttons(view)) == 1

    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"RIFF" + b"\0" * 64)
    view.set_busy(str(clip))
    view.set_result("four words came back from the model here")

    assert not view._copy_btn.isHidden()
    assert view._browse_btn.property("role") == "secondary"
    chrome = _primary_chrome_buttons(view)
    assert len(chrome) == 1, [b.text() for b in chrome]
    assert chrome[0] is view._copy_btn


def test_destructive_buttons_are_marked_dangerous(window):
    """Clear sits one click from a search box. Painted like its neutral
    neighbours it read as safe to press."""
    from PySide6.QtWidgets import QPushButton

    unmarked = []
    for key, view in _views(window):
        for button in view.findChildren(QPushButton):
            if button.text().strip().lower() in ("clear", "delete", "reset"):
                if button.property("role") != "danger":
                    unmarked.append(f"{key}:{button.objectName()}")
    assert unmarked == [], f"destructive buttons not marked danger: {unmarked}"


# --- the left edge ------------------------------------------------------


def test_every_view_lands_its_content_on_the_same_left_edge(window):
    """The Transcribe 24px drift, as a behaviour instead of a comment.

    Measured after the view is switched to, so the layout has run — a
    stacked widget only lays out the page it is showing.
    """
    offsets = {}
    for key in _VIEW_KEYS:
        window._activate_nav(key)
        QApplication.processEvents()
        view = window.get_view(key)
        header = view.findChild(PageHeader)
        assert header is not None, key
        origin = header.mapTo(view, QPoint(0, 0))
        offsets[key] = origin.x()

    assert offsets, "no views measured"
    drifted = {k: v for k, v in offsets.items() if v != _CONTENT_LEFT_PX}
    assert drifted == {}, (
        f"content frame is {_CONTENT_LEFT_PX}px, these views are not: {drifted} "
        f"(measured {offsets})"
    )


# --- the topbar telemetry ----------------------------------------------


def test_resource_meter_is_hidden_until_a_model_is_loaded(window):
    """A gauge pinned at 0% on every screen is a debug readout taking the
    best position on the window. It appears when there is a model whose
    size and load it can actually answer for."""
    resources = window.topbar._resources
    assert not resources.isVisible(), "pinned visible with no model loaded"

    window.topbar.set_active_model("Whisper Large v3")
    QApplication.processEvents()
    assert resources.isVisible(), (
        "hidden with a model loaded — the numbers now answer a real question"
    )

    window.topbar.set_active_model(None)
    QApplication.processEvents()
    assert not resources.isVisible()


# --- empty states -------------------------------------------------------


def test_empty_state_footer_is_centred_not_hard_right(qtbot):
    """A key cap pinned to the right edge under a centred sentence looks
    like a bug, and the first version did exactly that: the footer row
    spans the full width, so appending the widget after the leading
    stretch pushed it hard right."""
    from app.gui.widgets.empty_state import EmptyState, kbd_chip

    holder = QWidget()
    qtbot.addWidget(holder)
    holder.resize(600, 400)
    layout = QVBoxLayout(holder)
    empty = EmptyState("Nothing yet", "Press the key.")
    layout.addWidget(empty)
    chip = kbd_chip("Ctrl+F2", empty)
    empty.set_footer(chip)
    holder.show()
    QApplication.processEvents()

    empty_centre = empty.rect().center().x()
    chip_centre = chip.mapTo(empty, chip.rect().center()).x()
    assert abs(chip_centre - empty_centre) <= 2, (
        f"key cap centre at {chip_centre}, empty state centre at {empty_centre}"
    )


def test_logs_empty_state_follows_the_buffer_not_the_filter(window):
    """A search matching nothing must show an empty stream, not claim the
    app has never logged anything."""
    view = window.get_view("logs")
    assert view._stack.currentWidget() is view._empty

    view.append_record("10:00:00", "INFO", "app.gui", "model list built")
    QApplication.processEvents()
    assert view._stack.currentWidget() is view._text

    # A record that the network filter drops is still a record.
    view.append_record("10:00:01", "INFO", "urllib3.connectionpool", "GET /x")
    QApplication.processEvents()
    assert view._stack.currentWidget() is view._text, (
        "a filtered-out record sent the view back to the empty state"
    )

    view.clear()
    QApplication.processEvents()
    assert view._stack.currentWidget() is view._empty
