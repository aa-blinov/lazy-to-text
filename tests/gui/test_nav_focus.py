"""The sidebar's focus ring is painted on the row, not around the list.

The sidebar is one tab stop, so Qt puts focus on the ``QListWidget``
and never on an item. The obvious QSS — ``#SidebarList:focus`` — can
therefore only frame the *widget*, and it drew a border down the whole
200 × 601 px navigation column, including the empty space under the
last item. It read as a stray border, not as an indicator.

The ring is painted by a delegate instead. The regression is silent:
the stylesheet still parses, the sidebar still shows, the only thing
that is wrong is a box. So the tests below check the decision, the
geometry, the stylesheet, and the rendered pixels.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyleOptionViewItem,
    QWidget,
)

from app.gui.theme import TOKENS
from app.gui.widgets.sidebar import _NavFocusDelegate, _ring_rect


@pytest.fixture(autouse=True)
def _qapp(qtbot):
    """Every test in this file builds a real QWidget, including the
    decision-matrix ones: ``QStyleOptionViewItem.widget`` is a typed
    pointer, so a stub is not assignable. Offscreen Qt aborts the whole
    process without a QApplication, so ask for one once per module."""


class _FocusStub(QWidget):
    """A real QWidget with a decided focus state.

    ``QStyleOptionViewItem.widget`` is a typed pointer, so a stub object
    is not assignable — it has to be a genuine widget. Overriding
    ``hasFocus`` in Python is enough because the delegate looks the
    method up on the Python object.
    """

    def __init__(self, focused: bool) -> None:
        super().__init__()
        self._focused = focused

    def hasFocus(self) -> bool:  # noqa: N802 - Qt naming
        return self._focused


def _option(*, focused: bool, selected: bool, rect: QRect) -> QStyleOptionViewItem:
    """A view-item option with focus and selection decided by hand.

    ``_ring_rect`` only ever asks the widget for ``hasFocus()``, so
    deciding it here keeps the decision matrix clear of the offscreen
    focus chain — which only grants focus to an *active* window and is
    the flakiest part of this tree.
    """
    option = QStyleOptionViewItem()
    option.rect = rect
    option.widget = _FocusStub(focused)
    if selected:
        option.state |= QStyle.StateFlag.State_Selected
    return option


# The measured geometry of a nav row (app/gui/widgets/sidebar.py, 1100 × 780
# window): 192 × 46, inside a 200 × 601 list. The test row is the real one,
# because the regression is precisely a size error.
_ROW = QRect(0, 0, 192, 46)


# --- the decision -------------------------------------------------------


def test_ring_is_drawn_on_the_selected_row_when_the_list_has_focus():
    assert _ring_rect(_option(focused=True, selected=True, rect=_ROW)) is not None


def test_no_ring_when_the_list_does_not_have_focus():
    """Pointer use leaves the list unfocused — the ring must not stay."""
    assert _ring_rect(_option(focused=False, selected=True, rect=_ROW)) is None


def test_no_ring_without_a_selected_row():
    assert _ring_rect(_option(focused=True, selected=False, rect=_ROW)) is None


def test_no_widget_means_no_ring():
    option = _option(focused=True, selected=True, rect=_ROW)
    option.widget = None
    assert _ring_rect(option) is None


# --- the geometry -------------------------------------------------------


def test_ring_sits_inside_the_row():
    """Drawn inward, like every other ring in the app: it must not eat
    into the label or grow the item."""
    ring = _ring_rect(_option(focused=True, selected=True, rect=_ROW))
    assert ring is not None
    assert ring == _ROW.adjusted(1, 1, -2, -2)
    assert ring.contains(ring.topLeft()) and _ROW.contains(ring)


def test_ring_is_row_sized_not_column_sized():
    """The bug in one assertion: a frame around the list is 200 × 601,
    a ring on a row is neither tall nor wide."""
    ring = _ring_rect(_option(focused=True, selected=True, rect=_ROW))
    assert ring is not None
    assert ring.height() <= 50, f"ring is {ring.height()}px tall — that is a frame"
    assert ring.width() <= 200, f"ring is {ring.width()}px wide — that is a frame"


# --- the stylesheet -----------------------------------------------------


def test_stylesheet_does_not_frame_the_list():
    """Regression guard. QSS can only frame the widget, so any rule on
    ``#SidebarList:focus`` re-creates the box the delegate exists to
    avoid. The comment above the rule is the reason, not a licence."""
    from app.gui.theme import _STYLES_DIR

    raw = (_STYLES_DIR / "dark.qss").read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in raw.splitlines()
        if line.strip().startswith("#SidebarList:focus")
    ]
    assert offenders == [], (
        f"dark.qss frames the sidebar widget on focus again: {offenders}"
    )


def test_sidebar_installs_the_focus_delegate(qtbot):
    """The ring has no stylesheet behind it, so a refactor that drops
    the delegate leaves the sidebar with no focus indicator at all."""
    from app.gui.widgets.sidebar import Sidebar

    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    assert isinstance(sidebar._list.itemDelegate(), _NavFocusDelegate)


# --- what actually lands on screen --------------------------------------


def _ring_rgb() -> QColor:
    return QColor(TOKENS.colors["text_primary"])


def _count_ring_pixels(pixmap, rect: QRect) -> int:
    image = pixmap.toImage()
    target = _ring_rgb()
    found = 0
    for y in range(rect.top(), min(rect.bottom(), image.height())):
        for x in range(rect.left(), min(rect.right(), image.width())):
            if image.pixelColor(x, y) == target:
                found += 1
    return found


@pytest.fixture
def rendered_sidebar(qtbot):
    """A real sidebar in an active window, with the real stylesheet.

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
        window.resize(300, 700)
        sidebar = Sidebar(parent=window)
        window.show()
        window.activateWindow()
        QApplication.processEvents()
        yield sidebar
    finally:
        app.setStyleSheet(previous)


def test_ring_lands_on_the_row_and_not_in_the_empty_column(rendered_sidebar):
    """The regression, stated as pixels: the ring is on the current row,
    and the empty column below the last item is clean."""
    sidebar = rendered_sidebar
    nav = sidebar._list
    nav.setFocus()
    QApplication.processEvents()
    assert nav.hasFocus(), "offscreen did not grant focus; assertions would be vacuous"

    item = nav.item(0)
    row = nav.viewport().rect()
    row.setTop(nav.visualItemRect(item).top())
    row.setBottom(nav.visualItemRect(item).bottom() + 1)

    empty_below = QRect(
        0,
        nav.visualItemRect(nav.item(nav.count() - 1)).bottom() + 1,
        nav.viewport().width(),
        nav.viewport().height(),
    )
    assert empty_below.height() > 120, "no empty column to check — layout changed"

    pixmap = nav.viewport().grab()
    assert _count_ring_pixels(pixmap, row) > 0, "no focus ring on the current row"
    assert _count_ring_pixels(pixmap, empty_below) == 0, (
        "a ring was drawn in the empty column below the last item"
    )


def test_ring_disappears_when_focus_leaves(rendered_sidebar):
    from PySide6.QtWidgets import QLineEdit

    sidebar = rendered_sidebar
    nav = sidebar._list
    nav.setFocus()
    QApplication.processEvents()

    row = nav.visualItemRect(nav.item(0))
    with_focus = _count_ring_pixels(nav.viewport().grab(), row)
    assert with_focus > 0

    # A real sibling takes the focus, the way Tab does — not a poke at
    # the flag, so this also covers the redraw that has to follow.
    elsewhere = QLineEdit()
    elsewhere.show()
    elsewhere.setFocus()
    QApplication.processEvents()
    assert not nav.hasFocus(), "focus never left the list; the test is vacuous"

    assert _count_ring_pixels(nav.viewport().grab(), row) == 0, (
        "the ring outlived the focus that earned it"
    )
