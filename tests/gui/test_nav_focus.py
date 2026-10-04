"""The sidebar's keyboard focus is a fill lift, not a mark on the pill.

The sidebar is one tab stop, so Qt puts focus on the ``QListWidget`` and
never on a row. Two shapes were tried and measured before this one:

- ``#SidebarList:focus`` in the stylesheet frames the *widget*: a border
  down the whole 200 x 601 px column, including the empty space under the
  last item. It read as a stray border.
- A delegate that stroked ``option.rect`` on the selected row was worse
  than useless. Qt hands a delegate the *unmargined* item rect (192 px)
  while the stylesheet paints the pill inset by its own margin
  (12..187), so the stroke landed ~11 px off the fill on one side and
  flush on the other: a white hook hanging off a blue pill.

So the focus state is the fill. The selected row lifts from accent to
accent_focus while the list holds keyboard focus. Nothing is added, so
nothing can drift: the pill keeps the stylesheet's own radius, padding
and position.

The last test is the one that matters most — it fails if anyone puts a
stroke back, because a stroke changes a few hundred pixels and a fill
changes thousands.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QListWidget,
    QStyledItemDelegate,
    QWidget,
)

from app.gui.theme import TOKENS


@pytest.fixture(autouse=True)
def _qapp(qtbot):
    """Offscreen Qt aborts the process without a QApplication, and the
    pixel tests need the real stylesheet, so ask for one per module."""


@pytest.fixture
def sidebar(qtbot):
    """A real Sidebar in an active window, with the real stylesheet.

    Offscreen Qt only grants focus to an active window, and the window
    only becomes active once its children exist — so activation has to
    happen after construction, or ``setFocus`` is a silent no-op and
    every assertion below passes vacuously.
    """
    from app.gui.theme import load_stylesheet
    from app.gui.widgets.sidebar import Sidebar

    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(load_stylesheet("dark"))
    try:
        window = QWidget()
        qtbot.addWidget(window)
        window.resize(320, 700)
        side = Sidebar(parent=window)
        window.show()
        window.activateWindow()
        QApplication.processEvents()
        yield side
    finally:
        app.setStyleSheet(previous)


def _count(pixmap, hex_colour: str) -> int:
    image = pixmap.toImage()
    target = hex_colour.lower()
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).name() == target
    )


def _fill_bbox(image, hex_colour: str):
    """Rows and columns that carry a given colour, as a tight bounding box."""
    target = hex_colour.lower()
    xs, ys = [], []
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).name() == target:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


# --- the state ----------------------------------------------------------


def test_focused_row_lifts_to_the_hover_accent(sidebar):
    nav = sidebar._list
    nav.setFocus()
    QApplication.processEvents()
    assert nav.hasFocus(), "offscreen did not grant focus; the rest is vacuous"

    shot = nav.grab()
    assert _count(shot, TOKENS.colors["accent_focus"]) > 0, (
        "the selected row did not lift while the list held focus"
    )
    assert _count(shot, TOKENS.colors["accent"]) == 0, (
        "the unfocused fill is still showing through"
    )


def test_unfocused_row_shows_the_base_accent(sidebar):
    nav = sidebar._list
    nav.setFocus()
    QApplication.processEvents()
    nav.clearFocus()
    QApplication.processEvents()
    assert not nav.hasFocus()

    shot = nav.grab()
    assert _count(shot, TOKENS.colors["accent"]) > 0
    assert _count(shot, TOKENS.colors["accent_focus"]) == 0


def test_focus_round_trips(sidebar):
    """Tab in, tab out, tab back in — a one-shot lift would strand the
    user with no indicator at all after the first visit."""
    nav = sidebar._list
    for _ in range(2):
        nav.setFocus()
        QApplication.processEvents()
        assert _count(nav.grab(), TOKENS.colors["accent_focus"]) > 0
        nav.clearFocus()
        QApplication.processEvents()
        assert _count(nav.grab(), TOKENS.colors["accent_focus"]) == 0


# --- what the state is made of ------------------------------------------


def test_focus_changes_the_fill_not_a_stroke(sidebar):
    """The regression this file exists for. A fill changes thousands of
    pixels inside the pill; a 1px outline changes a few hundred, and half
    of those land outside the pill where they read as a stray hook."""
    nav = sidebar._list

    nav.setFocus()
    QApplication.processEvents()
    focused = nav.grab().toImage()
    nav.clearFocus()
    QApplication.processEvents()
    plain = nav.grab().toImage()

    assert (focused.width(), focused.height()) == (plain.width(), plain.height())

    pill = _fill_bbox(plain, TOKENS.colors["accent"])
    assert pill is not None, "the selected row is not filled at all"

    changed = [
        (x, y)
        for y in range(plain.height())
        for x in range(plain.width())
        if focused.pixelColor(x, y) != plain.pixelColor(x, y)
    ]
    assert len(changed) > 2000, (
        f"only {len(changed)} pixels changed — that is a stroke, not a fill"
    )

    x0 = min(x for x, _ in changed)
    y0 = min(y for _, y in changed)
    x1 = max(x for x, _ in changed)
    y1 = max(y for _, y in changed)
    assert (x0, y0) == (pill[0], pill[1]), "the change starts off the pill"
    assert (x1, y1) == (pill[2], pill[3]), "the change runs past the pill"


def test_sidebar_uses_the_default_item_delegate(sidebar):
    """The architectural guard. A delegate is how the misaligned outline
    got there: Qt hands it a rect that is not the pill. Anything that
    paints a nav row has to be rejected, not tuned."""
    assert type(sidebar._list.itemDelegate()) is QStyledItemDelegate


def test_focus_lift_is_token_sourced(sidebar):
    """A hex literal here would be a second source of truth for a colour
    the palette already owns.

    Checked in the *source*, not in the applied stylesheet: a literal
    equal to the token's value produces the same string, so a runtime
    comparison cannot tell the two apart.
    """
    import re
    from pathlib import Path

    from app.gui.widgets import sidebar as sidebar_module

    source = Path(sidebar_module.__file__).read_text(encoding="utf-8")
    literals = re.findall(r"#[0-9a-fA-F]{6}\b", source)
    assert literals == [], f"hex literals in sidebar.py: {literals}"
    assert "TOKENS.colors['accent_focus']" in source, (
        "the focus lift should name the token, not a colour"
    )

    nav = sidebar._list
    nav.setFocus()
    QApplication.processEvents()
    sheet = nav.styleSheet()
    assert TOKENS.colors["accent_focus"] in sheet, sheet
    assert sheet.count("background-color") == 1, sheet


# --- the stylesheet -----------------------------------------------------


def test_stylesheet_does_not_frame_the_list(sidebar):
    """Regression guard. QSS can only frame the widget, so any rule on
    ``#SidebarList:focus`` re-creates the box down the whole column."""
    from app.gui.theme import _STYLES_DIR

    raw = (_STYLES_DIR / "dark.qss").read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in raw.splitlines()
        if line.strip().startswith("#SidebarList:focus")
    ]
    assert offenders == [], f"dark.qss frames the sidebar widget again: {offenders}"


def test_the_navigation_list_is_the_one_tab_stop(sidebar):
    """Five items, one tab stop. The lift only means something if Tab
    reaches the list at all."""
    assert isinstance(sidebar._list, QListWidget)
    assert sidebar._list.count() == 5
    assert sidebar._list.currentRow() == 0
