"""Spacing comes off the token scale, and every card agrees on it.

``TOKENS.spacing`` is five steps: 4, 8, 12, 16, 24. Every gap used to be
written as a bare number, and two of them were on no step of it — 10 and
14 both sit between two steps, which is the thing a scale exists to
decide. The one that mattered most was ``10`` in ``_make_section_card``:
it set the vertical gap between rows of *every* settings-shaped screen on
the app, and nobody chose it.

The trap these tests close is that the shared helper is not the only
place the card's chrome is written down. ``shortcuts_view`` builds two of
its cards by hand — Storage and Hugging Face, both on the same screen —
so fixing the helper alone left those two visibly tighter than their
neighbours a scroll away. Both are on the *same* settings screen, so the
selector here is "every card that has a section header", not "the card
the helper builds": that is the only form of the assertion that fails
when the copies drift instead of when the helper does.

These read the built widget tree rather than the source, so a number has
to be right where it is painted, not only where it is written.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QFrame, QLabel, QWidget


def _section_cards(view: QWidget) -> list[QFrame]:
    """Every card on a page that carries a section header.

    Matches ``_make_section_card`` and its hand-rolled copies alike — a
    card is a card because of how it looks, not because of which line of
    which file built it.
    """
    return [
        frame
        for frame in view.findChildren(QFrame)
        if frame.property("role") == "card"
        and any(
            child.property("role") == "section-header"
            for child in frame.findChildren(QLabel)
        )
    ]


@pytest.fixture
def shortcuts(qtbot):
    from app.gui.views.shortcuts_view import ShortcutsView

    view = ShortcutsView()
    qtbot.addWidget(view)
    view.resize(1100, 1400)
    view.show()
    return view


# The settings screen's full set, five of them built by the shared helper
# and two by hand. Asserted as a floor rather than an equality: a card
# added later is a change the test should not block, but a card that
# *disappears* means the selector stopped matching and every assertion
# below it became vacuous.
_SETTINGS_CARDS = {
    "AudioInputCard",
    "HotkeysCard",
    "ClipboardCard",
    "AppearanceCard",
    "StorageCard",
    "HfCard",
}


def test_every_card_on_the_settings_screen_has_the_same_row_rhythm(shortcuts):
    """Ten pixels between rows, on two of the cards and not the other five.

    That is not a preference complaint — the two hand-built cards sat on
    the same page as the helper-built ones, so the page carried two
    different rhythms and the seam moved as you scrolled past it.
    """
    from app.gui.theme import TOKENS

    by_name = {
        frame.objectName(): frame.layout().spacing()
        for frame in _section_cards(shortcuts)
    }
    missing = _SETTINGS_CARDS - set(by_name)
    assert not missing, f"selector stopped finding {sorted(missing)}"
    assert set(by_name.values()) == {TOKENS.spacing["md"]}, by_name


def test_a_card_spreads_its_labels_wider_than_its_rows_are_tall(shortcuts):
    """``lg`` across, ``md`` down.

    A label column that crowds its field reads as one dense block; the
    rows below it want less, or the card turns into stripes. Both are
    scale steps now, so the relationship between them is a fact rather
    than two numbers somebody typed near each other.
    """
    from app.gui.theme import TOKENS
    from app.gui.views._section_card import _make_section_card

    card, form = _make_section_card("Rhythm", shortcuts)
    assert form.verticalSpacing() == TOKENS.spacing["md"]
    assert form.horizontalSpacing() == TOKENS.spacing["lg"]


@pytest.mark.parametrize(
    "module, cls, step",
    [
        ("models_view", "ModelsView", "lg"),
        ("shortcuts_view", "ShortcutsView", "lg"),
        ("history_view", "HistoryView", "md"),
        ("logs_view", "LogsView", "md"),
    ],
)
def test_a_page_takes_its_outer_rhythm_from_the_scale(module, cls, step, qtbot):
    """14 and 10 were both page-level and both off the scale.

    Card-heavy pages take ``lg`` and list pages ``md`` — the rhythm has
    to sit a step above whatever it separates, or a page of cards and a
    page of rows end up separated by the same distance.
    """
    import importlib

    from app.gui.theme import TOKENS

    view = getattr(importlib.import_module(f"app.gui.views.{module}"), cls)()
    qtbot.addWidget(view)

    if module == "shortcuts_view":
        # The one page that scrolls, so its root lives on the scroll's
        # content widget rather than on the view itself.
        content = view.findChild(QWidget, "ShortcutsScrollContent")
        assert content is not None
    else:
        content = view

    assert content.layout().spacing() == TOKENS.spacing[step]
